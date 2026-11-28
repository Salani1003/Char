import django_filters
from django.db.models import Exists, OuterRef

from sales.models import Exchange, PaymentMethod, Sale, SaleItem

__all__ = ['SaleFilter', 'ExchangeFilter']


class SaleFilter(django_filters.FilterSet):
    """
    Filtros de ventas: `client`, `status`, `payment_method`, `created_by`, `product` / `variant` (ventas que
    incluyen ese producto o variante), `has_discount`, `has_exchanges` (con algún cambio activo),
    `min_total` / `max_total` y rango de fechas `date_from` / `date_to` (inclusivos, hora local).
    """

    payment_method = django_filters.ChoiceFilter(choices=PaymentMethod.choices)
    date_from = django_filters.DateFilter(field_name='created_at', lookup_expr='date__gte')
    date_to = django_filters.DateFilter(field_name='created_at', lookup_expr='date__lte')
    min_total = django_filters.NumberFilter(field_name='total', lookup_expr='gte')
    max_total = django_filters.NumberFilter(field_name='total', lookup_expr='lte')
    product = django_filters.NumberFilter(method='filter_product')
    variant = django_filters.NumberFilter(method='filter_variant')
    has_discount = django_filters.BooleanFilter(method='filter_has_discount')
    has_exchanges = django_filters.BooleanFilter(method='filter_has_exchanges')

    class Meta:
        model = Sale
        fields = [
            'client', 'status', 'payment_method', 'created_by', 'product', 'variant', 'has_discount',
            'has_exchanges', 'min_total', 'max_total', 'date_from', 'date_to',
        ]

    def filter_product(self, queryset, name, value):
        return queryset.filter(Exists(SaleItem.objects.filter(sale=OuterRef('pk'), variant__product_id=value)))

    def filter_variant(self, queryset, name, value):
        return queryset.filter(Exists(SaleItem.objects.filter(sale=OuterRef('pk'), variant_id=value)))

    def filter_has_discount(self, queryset, name, value):
        return queryset.filter(discount_percent__gt=0) if value else queryset.filter(discount_percent=0)

    def filter_has_exchanges(self, queryset, name, value):
        active = Exists(Exchange.objects.filter(sale=OuterRef('pk'), status=Exchange.Status.COMPLETADA))
        return queryset.filter(active) if value else queryset.exclude(active)


class ExchangeFilter(django_filters.FilterSet):
    """
    Filtros de cambios: `sale`, `client` (el de la venta), `status`, `payment_method`, `created_by` y rango de
    fechas `date_from` / `date_to` (inclusivos, hora local).
    """

    client = django_filters.NumberFilter(field_name='sale__client_id')
    payment_method = django_filters.ChoiceFilter(choices=PaymentMethod.choices)
    date_from = django_filters.DateFilter(field_name='created_at', lookup_expr='date__gte')
    date_to = django_filters.DateFilter(field_name='created_at', lookup_expr='date__lte')

    class Meta:
        model = Exchange
        fields = ['sale', 'client', 'status', 'payment_method', 'created_by', 'date_from', 'date_to']
