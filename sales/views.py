from django.db.models import Count, OuterRef, Prefetch, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from core.pagination import DefaultPagination
from core.permissions import ActionPermission
from sales.filters import ExchangeFilter, SaleFilter
from sales.models import Exchange, ExchangeItem, Sale, SaleItem
from sales.schemas import EXCHANGE_VIEWSET_SCHEMA, SALE_VIEWSET_SCHEMA
from sales.serializers import (
    ExchangeCreateSerializer,
    ExchangeDetailSerializer,
    ExchangePreviewResultSerializer,
    ExchangePreviewSerializer,
    ExchangeSerializer,
    SaleCreateSerializer,
    SaleDetailSerializer,
    SaleSerializer,
    VoidSerializer,
)
from sales.services import create_exchange, create_sale, preview_exchange, void_exchange, void_sale


def _per_sale(aggregate):
    """Subconsulta que agrega los ítems de cada venta (no multiplica filas como un JOIN con el buscador)."""
    return Coalesce(
        Subquery(SaleItem.objects.filter(sale=OuterRef('pk')).values('sale').annotate(v=aggregate).values('v')),
        Value(0),
    )


@SALE_VIEWSET_SCHEMA
class SaleViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Ventas. Se registran (descuentan stock), se consultan y se anulan (devuelven el stock). No se editan ni
    se borran: no hay PUT/PATCH/DELETE. Los permisos son por acción (`sales.view_sale`, `sales.add_sale`,
    `sales.void_sale`); aplicar descuento exige además `sales.apply_discount`.
    """

    queryset = Sale.objects.select_related('client', 'created_by', 'voided_by').annotate(
        items_count=_per_sale(Count('id')), units=_per_sale(Sum('quantity')),
    )
    permission_classes = [ActionPermission]
    required_perms = {
        'list': ['sales.view_sale'],
        'retrieve': ['sales.view_sale'],
        'create': ['sales.add_sale'],
        'void': ['sales.void_sale'],
    }
    pagination_class = DefaultPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = SaleFilter
    search_fields = ['client__first_name', 'client__last_name', 'client__email', 'note', 'items__variant__sku']
    ordering_fields = ['created_at', 'total', 'id']
    ordering = ['-created_at', '-id']

    def get_serializer_class(self):
        if self.action == 'create':
            return SaleCreateSerializer
        if self.action == 'void':
            return VoidSerializer
        return SaleDetailSerializer if self.action == 'retrieve' else SaleSerializer

    @staticmethod
    def _with_detail(queryset):
        items = SaleItem.objects.select_related('variant__product', 'variant__color', 'variant__size')
        return queryset.prefetch_related(
            Prefetch('items', queryset=items), Prefetch('exchanges', queryset=Exchange.objects.order_by('id')),
        )

    def get_queryset(self):
        queryset = super().get_queryset()
        return self._with_detail(queryset) if self.action == 'retrieve' else queryset

    def _detail(self, sale):
        sale = self._with_detail(super().get_queryset()).get(pk=sale.pk)
        return SaleDetailSerializer(sale, context=self.get_serializer_context()).data

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        sale, created = create_sale(
            request.user,
            [(item['variant'], item['quantity']) for item in data['items']],
            data['payment_method'],
            client=data['client'],
            discount_percent=data['discount_percent'],
            discount_reason=data['discount_reason'],
            note=data['note'],
            idempotency_key=data['idempotency_key'],
        )
        return Response(self._detail(sale), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def void(self, request, pk=None):
        sale = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sale = void_sale(sale, user=request.user, reason=serializer.validated_data['reason'])
        return Response(self._detail(sale))


@EXCHANGE_VIEWSET_SCHEMA
class ExchangeViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Cambios sobre una venta. Se registran, se consultan y se anulan; no se editan ni se borran. No hay
    devoluciones de dinero: ver `Exchange`. Permisos por acción (`sales.view_exchange`, `sales.add_exchange`,
    `sales.void_exchange`).
    """

    queryset = Exchange.objects.select_related('sale__client', 'created_by', 'voided_by')
    permission_classes = [ActionPermission]
    required_perms = {
        'list': ['sales.view_exchange'],
        'retrieve': ['sales.view_exchange'],
        'create': ['sales.add_exchange'],
        'preview': ['sales.add_exchange'],
        'void': ['sales.void_exchange'],
    }
    pagination_class = DefaultPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = ExchangeFilter
    search_fields = ['sale__client__first_name', 'sale__client__last_name', 'sale__client__email', 'note', 'items__variant__sku']
    ordering_fields = ['created_at', 'difference', 'id']
    ordering = ['-created_at', '-id']

    def get_serializer_class(self):
        return {
            'create': ExchangeCreateSerializer, 'preview': ExchangePreviewSerializer, 'void': VoidSerializer,
            'retrieve': ExchangeDetailSerializer,
        }.get(self.action, ExchangeSerializer)

    @staticmethod
    def _with_items(queryset):
        items = ExchangeItem.objects.select_related('variant__product', 'variant__color', 'variant__size')
        return queryset.prefetch_related(Prefetch('items', queryset=items))

    def get_queryset(self):
        queryset = super().get_queryset()
        return self._with_items(queryset) if self.action == 'retrieve' else queryset

    def _detail(self, exchange):
        exchange = self._with_items(super().get_queryset()).get(pk=exchange.pk)
        return ExchangeDetailSerializer(exchange, context=self.get_serializer_context()).data

    @staticmethod
    def _lines(data):
        returned = [(line['sale_item'], line['quantity']) for line in data['returned_items']]
        new = [(line['variant'], line['quantity']) for line in data['new_items']]
        return data['sale'], returned, new

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        sale, returned, new = self._lines(data)
        exchange = create_exchange(
            request.user, sale, returned, new, payment_method=data['payment_method'], note=data['note'],
        )
        return Response(self._detail(exchange), status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def preview(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = preview_exchange(*self._lines(serializer.validated_data))
        return Response(ExchangePreviewResultSerializer(result).data)

    @action(detail=True, methods=['post'])
    def void(self, request, pk=None):
        exchange = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        exchange = void_exchange(exchange, user=request.user, reason=serializer.validated_data['reason'])
        return Response(self._detail(exchange))
