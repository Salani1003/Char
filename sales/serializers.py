from datetime import date

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from clients.models import Client
from products.models import ProductVariant
from sales.models import Exchange, ExchangeItem, PaymentMethod, Sale, SaleItem
from sales.services import exchange_deadline

__all__ = [
    'SaleSerializer', 'SaleDetailSerializer', 'SaleCreateSerializer', 'VoidSerializer',
    'ExchangeSerializer', 'ExchangeDetailSerializer', 'ExchangeCreateSerializer', 'ExchangePreviewSerializer',
    'ExchangePreviewResultSerializer',
]


class SaleItemSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(source='variant.sku', read_only=True)
    product = serializers.IntegerField(source='variant.product_id', read_only=True)
    product_name = serializers.CharField(source='variant.product.name', read_only=True)
    color_name = serializers.CharField(source='variant.color.name', read_only=True)
    color_hex = serializers.CharField(source='variant.color.hex', read_only=True)
    size_name = serializers.CharField(source='variant.size.name', read_only=True)
    exchangeable_quantity = serializers.SerializerMethodField(help_text='Unidades que todavía se pueden cambiar.')

    class Meta:
        model = SaleItem
        fields = [
            'id', 'variant', 'sku', 'product', 'product_name', 'color_name', 'color_hex', 'size_name',
            'quantity', 'list_price', 'discount_percent', 'unit_price', 'subtotal',
            'exchanged_quantity', 'exchangeable_quantity',
        ]
        read_only_fields = fields

    def get_exchangeable_quantity(self, obj) -> int:
        return obj.quantity - obj.exchanged_quantity


class _SaleExchangeSerializer(serializers.ModelSerializer):
    """Resumen de un cambio dentro del detalle de la venta (el detalle completo es `exchanges/{id}/`)."""

    class Meta:
        model = Exchange
        fields = ['id', 'status', 'returned_total', 'new_total', 'difference', 'payment_method', 'created_at']
        read_only_fields = fields


class SaleSerializer(serializers.ModelSerializer):
    """Fila del listado: la venta con sus totales (sin los ítems)."""

    client_name = serializers.SerializerMethodField()
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_email = serializers.CharField(source='created_by.email', read_only=True, default=None)
    voided_by_email = serializers.CharField(source='voided_by.email', read_only=True, default=None)
    items_count = serializers.IntegerField(read_only=True, help_text='Cantidad de ítems (variantes distintas).')
    units = serializers.IntegerField(read_only=True, help_text='Unidades vendidas.')
    exchange_deadline = serializers.SerializerMethodField(help_text='Último día (YYYY-MM-DD) para pedir un cambio.')

    class Meta:
        model = Sale
        fields = [
            'id', 'client', 'client_name', 'payment_method', 'payment_method_display', 'subtotal',
            'discount_percent', 'discount_reason', 'total', 'note', 'status', 'status_display',
            'items_count', 'units', 'exchange_deadline', 'created_at', 'created_by', 'created_by_email',
            'voided_at', 'voided_by', 'voided_by_email', 'void_reason',
        ]
        read_only_fields = fields

    def get_client_name(self, obj) -> str | None:
        return f'{obj.client.first_name} {obj.client.last_name}'.strip() if obj.client_id else None

    def get_exchange_deadline(self, obj) -> date:
        return exchange_deadline(obj)


class SaleDetailSerializer(SaleSerializer):
    """Venta con sus ítems y un resumen de sus cambios."""

    items = SaleItemSerializer(many=True, read_only=True)
    exchanges = _SaleExchangeSerializer(many=True, read_only=True)
    can_exchange = serializers.SerializerMethodField(
        help_text='Completada, dentro del plazo y con unidades por cambiar.'
    )

    class Meta(SaleSerializer.Meta):
        fields = SaleSerializer.Meta.fields + ['can_exchange', 'items', 'exchanges']
        read_only_fields = fields

    def get_can_exchange(self, obj) -> bool:
        return (
            obj.status == Sale.Status.COMPLETADA
            and timezone.localdate() <= exchange_deadline(obj)
            and any(item.exchanged_quantity < item.quantity for item in obj.items.all())
        )


class _ItemInputSerializer(serializers.Serializer):
    variant = serializers.PrimaryKeyRelatedField(queryset=ProductVariant.objects.select_related('product'))
    quantity = serializers.IntegerField(min_value=1)


class SaleCreateSerializer(serializers.Serializer):
    """Alta de una venta. El precio no se envía: lo calcula el backend (vigente al vender)."""

    items = _ItemInputSerializer(many=True, allow_empty=False)
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices)
    client = serializers.PrimaryKeyRelatedField(queryset=Client.objects.all(), required=False, allow_null=True, default=None)
    discount_percent = serializers.IntegerField(
        required=False, default=0,
        help_text='Uno de los valores de `SALE_DISCOUNT_CHOICES` (hoy 0, 5 o 10). Con 5 o 10 requiere `sales.apply_discount`.',
    )
    discount_reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
    idempotency_key = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default='',
        help_text='Opcional. Reenviar la misma clave devuelve la venta ya registrada (200) en vez de duplicarla.',
    )


class VoidSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, help_text='Motivo de la anulación (obligatorio).')


class ExchangeItemSerializer(serializers.ModelSerializer):
    direction_display = serializers.CharField(source='get_direction_display', read_only=True)
    sku = serializers.CharField(source='variant.sku', read_only=True)
    product = serializers.IntegerField(source='variant.product_id', read_only=True)
    product_name = serializers.CharField(source='variant.product.name', read_only=True)
    color_name = serializers.CharField(source='variant.color.name', read_only=True)
    color_hex = serializers.CharField(source='variant.color.hex', read_only=True)
    size_name = serializers.CharField(source='variant.size.name', read_only=True)
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = ExchangeItem
        fields = [
            'id', 'direction', 'direction_display', 'variant', 'sku', 'product', 'product_name', 'color_name',
            'color_hex', 'size_name', 'quantity', 'unit_price', 'subtotal', 'sale_item',
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.DecimalField(max_digits=12, decimal_places=2))
    def get_subtotal(self, obj) -> str:
        return f'{obj.unit_price * obj.quantity:.2f}'


class ExchangeSerializer(serializers.ModelSerializer):
    """Fila del listado: el cambio con sus totales (sin las líneas)."""

    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payment_method_display = serializers.SerializerMethodField()
    client = serializers.IntegerField(source='sale.client_id', read_only=True)
    client_name = serializers.SerializerMethodField()
    unreturned_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True,
        help_text='Valor devuelto que no se compensó con lo que se lleva: no se reintegra (no hay devoluciones de dinero).',
    )
    created_by_email = serializers.CharField(source='created_by.email', read_only=True, default=None)
    voided_by_email = serializers.CharField(source='voided_by.email', read_only=True, default=None)

    class Meta:
        model = Exchange
        fields = [
            'id', 'sale', 'client', 'client_name', 'status', 'status_display', 'returned_total', 'new_total',
            'difference', 'unreturned_amount', 'payment_method', 'payment_method_display', 'note',
            'created_at', 'created_by', 'created_by_email', 'voided_at', 'voided_by', 'voided_by_email', 'void_reason',
        ]
        read_only_fields = fields

    def get_payment_method_display(self, obj) -> str:
        return obj.get_payment_method_display() if obj.payment_method else ''

    def get_client_name(self, obj) -> str | None:
        client = obj.sale.client
        return f'{client.first_name} {client.last_name}'.strip() if client else None


class ExchangeDetailSerializer(ExchangeSerializer):
    """Cambio con sus líneas: `direction='in'` lo que vuelve y `'out'` lo que se lleva."""

    items = ExchangeItemSerializer(many=True, read_only=True)

    class Meta(ExchangeSerializer.Meta):
        fields = ExchangeSerializer.Meta.fields + ['items']
        read_only_fields = fields


class _ReturnedInputSerializer(serializers.Serializer):
    sale_item = serializers.PrimaryKeyRelatedField(queryset=SaleItem.objects.all(), help_text='Id de un ítem de la venta.')
    quantity = serializers.IntegerField(min_value=1)


class ExchangePreviewSerializer(serializers.Serializer):
    """Qué se devuelve y qué se lleva. `new_items` puede ir vacío (el cliente no se lleva nada)."""

    sale = serializers.PrimaryKeyRelatedField(queryset=Sale.objects.all())
    returned_items = _ReturnedInputSerializer(many=True, allow_empty=False)
    new_items = _ItemInputSerializer(many=True, required=False, default=list)


class ExchangeCreateSerializer(ExchangePreviewSerializer):
    payment_method = serializers.ChoiceField(
        choices=PaymentMethod.choices, required=False, allow_blank=True, default='',
        help_text='Obligatorio sólo si hay diferencia a pagar (`difference` > 0). Si no la hay, se ignora.',
    )
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')


class ExchangePreviewResultSerializer(serializers.Serializer):
    returned_total = serializers.DecimalField(max_digits=12, decimal_places=2)
    new_total = serializers.DecimalField(max_digits=12, decimal_places=2)
    difference = serializers.DecimalField(max_digits=12, decimal_places=2, help_text='Nuevo − devuelto. Positiva: la paga el cliente.')
    unreturned_amount = serializers.DecimalField(max_digits=12, decimal_places=2, help_text='Valor devuelto que no se compensa y no se reintegra.')
