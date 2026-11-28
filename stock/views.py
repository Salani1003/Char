from django.db import transaction
from django.db.models import BooleanField, Count, ExpressionWrapper, F, IntegerField, Prefetch, Q, Sum, Value
from django.db.models.functions import Abs, Coalesce
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from core.pagination import DefaultPagination
from core.permissions import ActionPermission
from products.filters import variant_image_key
from products.models import ProductVariant
from stock.filters import StockCountFilter, StockFilter, StockMovementFilter, StockOperationFilter
from stock.models import StockCount, StockCountItem, StockMovement, StockOperation
from stock.schemas import (
    STOCK_COUNT_VIEWSET_SCHEMA,
    STOCK_MOVEMENT_VIEWSET_SCHEMA,
    STOCK_OPERATION_VIEWSET_SCHEMA,
    STOCK_VIEWSET_SCHEMA,
)
from stock.serializers import (
    ReverseSerializer,
    StockCountBulkItemsSerializer,
    StockCountCreateSerializer,
    StockCountItemSerializer,
    StockCountSerializer,
    StockMovementCreateSerializer,
    StockMovementSerializer,
    StockOperationDetailSerializer,
    StockOperationSerializer,
    StockSerializer,
)
from stock.annotations import with_stock
from stock.exceptions import StockError
from stock.services import apply_movements, cancel_count, confirm_count, reverse_movement


@STOCK_VIEWSET_SCHEMA
class StockViewSet(viewsets.ReadOnlyModelViewSet):
    """Saldo por variante: todas las variantes activas, tengan o no movimientos."""

    queryset = ProductVariant.objects.select_related(
        'product__category__parent', 'product__brand', 'color', 'size', 'stock_level'
    )
    serializer_class = StockSerializer
    permission_classes = [ActionPermission]
    required_perms = {
        'list': ['stock.view_stocklevel'],
        'retrieve': ['stock.view_stocklevel'],
        'summary': ['stock.view_stocklevel'],
    }
    pagination_class = DefaultPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = StockFilter
    search_fields = ['sku', 'product__name', 'product__brand__name', 'color__name', 'size__name']
    ordering_fields = ['quantity', 'min_stock', 'sku', 'product__name', 'color__name', 'size__order']
    ordering = ['product__name', 'color__name', 'size__order', 'id']

    def get_queryset(self):
        return with_stock(super().get_queryset()).annotate(image_key=variant_image_key())

    @action(detail=False, methods=['get'])
    def summary(self, request):
        totals = with_stock(ProductVariant.objects.all()).aggregate(
            variants=Count('id'),
            out_of_stock=Count('id', filter=Q(quantity=0)),
            low_stock=Count('id', filter=Q(is_low_stock=True)),
            units=Coalesce(Sum('quantity'), Value(0)),
        )
        return Response(totals)


_MOVEMENT_RELATED = (
    'variant__product', 'variant__color', 'variant__size', 'created_by', 'reversed_by', 'reverses', 'operation',
)


@STOCK_OPERATION_VIEWSET_SCHEMA
class StockOperationViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """
    Historial de operaciones: cada ingreso/egreso en lote, recuento confirmado o anulación es una
    operación con sus líneas (movimientos). Inmutable: se lista, se consulta y se crea (el alta es un
    ingreso o egreso en lote); no hay PUT/PATCH/DELETE.
    """

    queryset = StockOperation.objects.select_related('created_by').annotate(
        lines_count=Count('movements'),
        units=Coalesce(Sum(Abs('movements__quantity')), Value(0)),
    )
    permission_classes = [ActionPermission]
    required_perms = {
        'list': ['stock.view_stockmovement'],
        'retrieve': ['stock.view_stockmovement'],
        'create': ['stock.add_stockmovement'],
    }
    pagination_class = DefaultPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = StockOperationFilter
    ordering_fields = ['created_at', 'units', 'lines_count']
    ordering = ['-created_at', '-id']

    def get_serializer_class(self):
        if self.action == 'create':
            return StockMovementCreateSerializer
        if self.action == 'retrieve':
            return StockOperationDetailSerializer
        return StockOperationSerializer

    def _with_lines(self, queryset):
        lines = StockMovement.objects.select_related(*_MOVEMENT_RELATED).order_by(
            'variant__product__name', 'variant__color__name', 'variant__size__order', 'id'
        )
        return queryset.prefetch_related(Prefetch('movements', queryset=lines))

    def get_queryset(self):
        queryset = super().get_queryset()
        return self._with_lines(queryset) if self.action == 'retrieve' else queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        operation = apply_movements(
            [(item['variant'], item['quantity']) for item in data['items']],
            data['kind'], data['reason'], user=request.user, note=data['note'],
        )
        operation = self._with_lines(super().get_queryset()).get(pk=operation.pk)
        return Response(StockOperationDetailSerializer(operation).data, status=status.HTTP_201_CREATED)


@STOCK_MOVEMENT_VIEWSET_SCHEMA
class StockMovementViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Líneas del historial (un movimiento por variante). Se consultan y se anulan; no se editan ni se borran."""

    queryset = StockMovement.objects.select_related(*_MOVEMENT_RELATED)
    permission_classes = [ActionPermission]
    required_perms = {
        'list': ['stock.view_stockmovement'],
        'retrieve': ['stock.view_stockmovement'],
        'reverse': ['stock.add_stockmovement'],
    }
    pagination_class = DefaultPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = StockMovementFilter
    search_fields = ['variant__sku', 'variant__product__name', 'note']
    ordering_fields = ['created_at', 'quantity']
    ordering = ['-created_at', '-id']

    def get_serializer_class(self):
        if self.action == 'reverse':
            return ReverseSerializer
        return StockMovementSerializer

    @action(detail=True, methods=['post'])
    def reverse(self, request, pk=None):
        movement = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reversal = reverse_movement(movement, user=request.user, note=serializer.validated_data['note'])
        reversal = self.get_queryset().get(pk=reversal.pk)
        return Response(StockMovementSerializer(reversal).data, status=status.HTTP_201_CREATED)


@STOCK_COUNT_VIEWSET_SCHEMA
class StockCountViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Recuentos de stock. Se arman en borrador, se confirman (generan los ajustes) o se
    cancelan. No se borran (sin DELETE) y sólo se edita la nota (PATCH, sin PUT). Todo lo que escribe exige
    `add_stockcount`, también confirmar.
    """

    queryset = StockCount.objects.select_related('created_by', 'confirmed_by').annotate(items_count=Count('items'))
    permission_classes = [ActionPermission]
    required_perms = {
        'list': ['stock.view_stockcount'],
        'retrieve': ['stock.view_stockcount'],
        'create': ['stock.add_stockcount'],
        'partial_update': ['stock.add_stockcount'],
        'add_item': ['stock.add_stockcount'],
        'bulk_items': ['stock.add_stockcount'],
        'remove_item': ['stock.add_stockcount'],
        'confirm': ['stock.add_stockcount'],
        'cancel': ['stock.add_stockcount'],
    }
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']
    pagination_class = DefaultPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = StockCountFilter
    search_fields = ['note']
    ordering_fields = ['created_at', 'confirmed_at']
    ordering = ['-created_at', '-id']

    def get_serializer_class(self):
        if self.action == 'create':
            return StockCountCreateSerializer
        if self.action == 'add_item':
            return StockCountItemSerializer
        if self.action == 'bulk_items':
            return StockCountBulkItemsSerializer
        return StockCountSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['with_items'] = self.action != 'list'
        return context

    def _detail(self, pk):
        """Recuento con sus líneas, para responder."""
        queryset = self.get_queryset().prefetch_related('items__variant__product', 'items__variant__color', 'items__variant__size')
        return StockCountSerializer(queryset.get(pk=pk), context=self.get_serializer_context()).data

    def retrieve(self, request, *args, **kwargs):
        return Response(self._detail(self.get_object().pk))

    @staticmethod
    def _ensure_draft(count):
        if count.status != StockCount.BORRADOR:
            raise StockError({'detail': f'El recuento está {count.get_status_display().lower()} y no se puede modificar.'})

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data.get('items', [])
        with transaction.atomic():
            count = StockCount.objects.create(note=serializer.validated_data.get('note', ''), created_by=request.user)
            StockCountItem.objects.bulk_create([StockCountItem(count=count, **item) for item in items])
        return Response(self._detail(count.pk), status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        count = self.get_object()
        self._ensure_draft(count)
        serializer = StockCountSerializer(count, data=request.data, partial=True, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(self._detail(count.pk))

    @action(detail=True, methods=['post'], url_path='items')
    def add_item(self, request, pk=None):
        """Agrega una línea o cambia la cantidad contada si la variante ya estaba."""
        with transaction.atomic():
            count = StockCount.objects.select_for_update().get(pk=self.get_object().pk)
            self._ensure_draft(count)
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            StockCountItem.objects.update_or_create(
                count=count, variant=serializer.validated_data['variant'],
                defaults={'counted_quantity': serializer.validated_data['counted_quantity']},
            )
        return Response(self._detail(count.pk), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='items/bulk')
    def bulk_items(self, request, pk=None):
        """Agrega o corrige muchas líneas de una vez (atómico). Las que no se mencionan quedan como están."""
        with transaction.atomic():
            count = StockCount.objects.select_for_update().get(pk=self.get_object().pk)
            self._ensure_draft(count)
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            StockCountItem.objects.bulk_create(
                [StockCountItem(count=count, **item) for item in serializer.validated_data['items']],
                update_conflicts=True, unique_fields=['count', 'variant'], update_fields=['counted_quantity'],
            )
        return Response(self._detail(count.pk))

    @action(detail=True, methods=['delete'], url_path=r'items/(?P<variant_id>\d+)')
    def remove_item(self, request, pk=None, variant_id=None):
        with transaction.atomic():
            count = StockCount.objects.select_for_update().get(pk=self.get_object().pk)
            self._ensure_draft(count)
            deleted, _ = count.items.filter(variant_id=variant_id).delete()
        if not deleted:
            raise NotFound('La variante no está en el recuento.')
        return Response(self._detail(count.pk))

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        count = confirm_count(self.get_object(), user=request.user)
        return Response(self._detail(count.pk))

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        count = cancel_count(self.get_object(), user=request.user)
        return Response(self._detail(count.pk))
