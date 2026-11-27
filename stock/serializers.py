from rest_framework import serializers

from core.media import get_image_storage
from products.models import ProductVariant
from products.serializers import THUMBNAIL_SIZE
from stock.models import StockCount, StockCountItem, StockMovement, StockOperation

__all__ = [
    'StockSerializer', 'StockMovementSerializer', 'StockMovementCreateSerializer', 'ReverseSerializer',
    'StockCountItemSerializer', 'StockCountSerializer', 'StockCountCreateSerializer', 'StockCountBulkItemsSerializer',
    'StockOperationSerializer', 'StockOperationDetailSerializer',
]


class StockSerializer(serializers.Serializer):
    """Saldo de una variante (fila de la grilla de stock). Sólo lectura."""

    id = serializers.IntegerField(help_text='Id de la variante.')
    sku = serializers.CharField()
    product = serializers.IntegerField(source='product_id')
    product_name = serializers.CharField(source='product.name')
    category_label = serializers.CharField(source='product.category.label')
    brand_name = serializers.CharField(source='product.brand.name', default=None)
    color = serializers.IntegerField(source='color_id')
    color_name = serializers.CharField(source='color.name')
    color_hex = serializers.CharField(source='color.hex')
    size = serializers.IntegerField(source='size_id')
    size_name = serializers.CharField(source='size.name')
    quantity = serializers.IntegerField(help_text='Stock actual (0 si nunca tuvo movimientos).')
    min_stock = serializers.IntegerField(help_text='Umbral de reposición (0 = sin alerta).')
    is_low_stock = serializers.BooleanField(help_text='`min_stock > 0` y `quantity <= min_stock`.')
    image_url = serializers.SerializerMethodField(
        help_text='Foto completa de la variante (la principal de su color o, si no hay, la de menor orden), o null.'
    )
    thumbnail_url = serializers.SerializerMethodField(help_text='Miniatura 400x400 de esa misma foto, o null.')

    def _image_key(self, obj) -> str | None:
        # Sin `products.view_productimage` el usuario no ve fotos: los campos van en null.
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if user is None or not user.has_perm('products.view_productimage'):
            return None
        return getattr(obj, 'image_key', None)  # lo anota el viewset (`variant_image_key`), sin consultas por fila

    def get_image_url(self, obj) -> str | None:
        key = self._image_key(obj)
        return (get_image_storage().url(key) or None) if key else None

    def get_thumbnail_url(self, obj) -> str | None:
        key = self._image_key(obj)
        return (get_image_storage().url(key, width=THUMBNAIL_SIZE, height=THUMBNAIL_SIZE) or None) if key else None


class StockMovementSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(source='variant.sku', read_only=True)
    product = serializers.IntegerField(source='variant.product_id', read_only=True)
    product_name = serializers.CharField(source='variant.product.name', read_only=True)
    color_name = serializers.CharField(source='variant.color.name', read_only=True)
    size_name = serializers.CharField(source='variant.size.name', read_only=True)
    kind_display = serializers.CharField(source='get_kind_display', read_only=True)
    reason_display = serializers.CharField(source='get_reason_display', read_only=True)
    created_by_email = serializers.CharField(source='created_by.email', read_only=True, default=None)
    stock_count = serializers.IntegerField(source='operation.stock_count_id', read_only=True)
    reversed_by = serializers.SerializerMethodField(help_text='Id del movimiento que anuló a éste, o null.')
    reversed_by_operation = serializers.SerializerMethodField(
        help_text='Id de la operación de esa anulación (para enlazar al detalle sin otra consulta), o null.'
    )
    reverses_operation = serializers.IntegerField(
        source='reverses.operation_id', read_only=True, default=None,
        help_text='Si éste es una anulación: id de la operación del movimiento anulado.',
    )

    class Meta:
        model = StockMovement
        fields = [
            'id', 'operation', 'variant', 'sku', 'product', 'product_name', 'color_name', 'size_name',
            'kind', 'kind_display', 'reason', 'reason_display', 'quantity', 'stock_before', 'stock_after',
            'note', 'stock_count', 'reverses', 'reverses_operation', 'reversed_by', 'reversed_by_operation',
            'created_at', 'created_by', 'created_by_email',
        ]
        read_only_fields = fields

    @staticmethod
    def _reversal(obj):
        # El viewset hace select_related('reversed_by'): sin consulta por fila.
        try:
            return obj.reversed_by
        except StockMovement.reversed_by.RelatedObjectDoesNotExist:
            return None

    def get_reversed_by(self, obj) -> int | None:
        reversal = self._reversal(obj)
        return reversal.pk if reversal else None

    def get_reversed_by_operation(self, obj) -> int | None:
        reversal = self._reversal(obj)
        return reversal.operation_id if reversal else None


class StockOperationSerializer(serializers.ModelSerializer):
    """Fila del historial: una operación con sus totales (sin las líneas)."""

    kind_display = serializers.CharField(source='get_kind_display', read_only=True)
    reason_display = serializers.SerializerMethodField()
    created_by_email = serializers.CharField(source='created_by.email', read_only=True, default=None)
    lines_count = serializers.IntegerField(read_only=True, help_text='Cantidad de variantes (líneas).')
    units = serializers.IntegerField(read_only=True, help_text='Unidades movidas (suma de los valores absolutos).')

    class Meta:
        model = StockOperation
        fields = [
            'id', 'kind', 'kind_display', 'reason', 'reason_display', 'note', 'stock_count',
            'lines_count', 'units', 'created_at', 'created_by', 'created_by_email',
        ]
        read_only_fields = fields

    def get_reason_display(self, obj) -> str:
        return dict(StockMovement.REASON_CHOICES).get(obj.reason, obj.reason)


class StockOperationDetailSerializer(StockOperationSerializer):
    """Operación con sus líneas (`movements`), una por variante."""

    movements = StockMovementSerializer(many=True, read_only=True)

    class Meta(StockOperationSerializer.Meta):
        fields = StockOperationSerializer.Meta.fields + ['movements']
        read_only_fields = fields


class _LineSerializer(serializers.Serializer):
    variant = serializers.PrimaryKeyRelatedField(queryset=ProductVariant.objects.select_related('product'))
    quantity = serializers.IntegerField(min_value=1, help_text='Unidades (positiva; el signo lo da el tipo).')


class StockMovementCreateSerializer(serializers.Serializer):
    """Ingreso o egreso en lote (atómico: si una línea falla no se aplica ninguna)."""

    kind = serializers.ChoiceField(choices=[StockMovement.INGRESO, StockMovement.EGRESO])
    reason = serializers.ChoiceField(choices=StockMovement.REASON_CHOICES)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
    items = _LineSerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        allowed = StockMovement.REASONS_BY_KIND[attrs['kind']] - {StockMovement.ANULACION}
        if attrs['reason'] not in allowed:
            raise serializers.ValidationError({'reason': f'El motivo no corresponde a un {attrs["kind"]}.'})
        variants = [item['variant'].pk for item in attrs['items']]
        if len(variants) != len(set(variants)):
            raise serializers.ValidationError({'items': 'Una variante no puede repetirse en el mismo movimiento.'})
        return attrs


class ReverseSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')


class StockCountItemSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(source='variant.sku', read_only=True)
    product_name = serializers.CharField(source='variant.product.name', read_only=True)
    color_name = serializers.CharField(source='variant.color.name', read_only=True)
    size_name = serializers.CharField(source='variant.size.name', read_only=True)

    class Meta:
        model = StockCountItem
        fields = [
            'id', 'variant', 'sku', 'product_name', 'color_name', 'size_name',
            'counted_quantity', 'system_quantity', 'difference',
        ]
        read_only_fields = ['id', 'sku', 'product_name', 'color_name', 'size_name', 'system_quantity', 'difference']
        extra_kwargs = {'variant': {'queryset': ProductVariant.objects.all()}}


class StockCountSerializer(serializers.ModelSerializer):
    """Recuento. En el listado trae `items_count`; en el detalle las líneas (`items`)."""

    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_email = serializers.CharField(source='created_by.email', read_only=True, default=None)
    confirmed_by_email = serializers.CharField(source='confirmed_by.email', read_only=True, default=None)
    items_count = serializers.SerializerMethodField()
    items = StockCountItemSerializer(many=True, read_only=True)

    class Meta:
        model = StockCount
        fields = [
            'id', 'status', 'status_display', 'note', 'items_count', 'items',
            'created_at', 'created_by', 'created_by_email', 'confirmed_at', 'confirmed_by', 'confirmed_by_email',
        ]
        read_only_fields = ['id', 'status', 'created_at', 'created_by', 'confirmed_at', 'confirmed_by']

    def get_items_count(self, obj) -> int:
        return obj.items_count if hasattr(obj, 'items_count') else obj.items.count()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self.context.get('with_items'):
            data.pop('items')
        return data


def _no_duplicate_variants(items):
    ids = [item['variant'].pk for item in items]
    if len(ids) != len(set(ids)):
        raise serializers.ValidationError('Una variante no puede repetirse en el recuento.')
    return items


class StockCountBulkItemsSerializer(serializers.Serializer):
    """Varias líneas de un recuento en borrador de una vez (agrega o corrige)."""

    items = StockCountItemSerializer(many=True, allow_empty=False)

    def validate_items(self, items):
        return _no_duplicate_variants(items)


class StockCountCreateSerializer(serializers.ModelSerializer):
    """Alta de un recuento en borrador, opcionalmente con sus primeras líneas."""

    items = StockCountItemSerializer(many=True, required=False)

    class Meta:
        model = StockCount
        fields = ['note', 'items']

    def validate_items(self, items):
        return _no_duplicate_variants(items)
