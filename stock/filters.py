import django_filters
from django.db.models import Exists, OuterRef, Q

from products.models import ProductVariant
from stock.models import StockCount, StockMovement, StockOperation

__all__ = ['StockFilter', 'StockMovementFilter', 'StockOperationFilter', 'StockCountFilter']


class StockFilter(django_filters.FilterSet):
    """
    Filtros de la grilla de stock:

      * `product`, `color`, `size`, `brand`: ids.
      * `category`: id; si es una raíz incluye las subcategorías.
      * `in_stock`: `true` con stock (> 0), `false` sin stock.
      * `out_of_stock`: `true` sin stock, `false` con stock.
      * `low_stock`: `true` con stock bajo (`min_stock > 0` y `quantity <= min_stock`;
        incluye las agotadas que tengan mínimo), `false` el resto.
    """

    category = django_filters.NumberFilter(method='filter_category')
    brand = django_filters.NumberFilter(field_name='product__brand_id')
    in_stock = django_filters.BooleanFilter(method='filter_in_stock')
    out_of_stock = django_filters.BooleanFilter(method='filter_out_of_stock')
    low_stock = django_filters.BooleanFilter(field_name='is_low_stock')

    class Meta:
        model = ProductVariant
        fields = ['product', 'color', 'size', 'category', 'brand', 'in_stock', 'out_of_stock', 'low_stock']

    def filter_category(self, queryset, name, value):
        return queryset.filter(Q(product__category_id=value) | Q(product__category__parent_id=value))

    def filter_in_stock(self, queryset, name, value):
        return queryset.filter(quantity__gt=0) if value else queryset.filter(quantity=0)

    def filter_out_of_stock(self, queryset, name, value):
        return queryset.filter(quantity=0) if value else queryset.filter(quantity__gt=0)


class StockMovementFilter(django_filters.FilterSet):
    """
    Filtros de las líneas (movimientos): `variant`, `product`, `operation`, `kind`, `reason`, `created_by`,
    `stock_count` (movimientos de un recuento) y rango de fechas `date_from` / `date_to`
    (YYYY-MM-DD, inclusivos, hora local).
    """

    product = django_filters.NumberFilter(field_name='variant__product_id')
    stock_count = django_filters.NumberFilter(field_name='operation__stock_count_id')
    date_from = django_filters.DateFilter(field_name='created_at', lookup_expr='date__gte')
    date_to = django_filters.DateFilter(field_name='created_at', lookup_expr='date__lte')

    class Meta:
        model = StockMovement
        fields = ['variant', 'product', 'operation', 'kind', 'reason', 'created_by', 'stock_count', 'date_from', 'date_to']


class StockOperationFilter(django_filters.FilterSet):
    """
    Filtros del historial de operaciones: `kind` (`ingreso`, `egreso`, `ajuste`), `reason`, `created_by`,
    `stock_count`, `variant` y `product` (operaciones que tocaron esa variante o ese producto),
    `search` (nota, SKU o nombre de producto) y fechas `date_from` / `date_to` (inclusivos, hora local).
    """

    variant = django_filters.NumberFilter(method='filter_variant')
    product = django_filters.NumberFilter(method='filter_product')
    search = django_filters.CharFilter(method='filter_search')
    date_from = django_filters.DateFilter(field_name='created_at', lookup_expr='date__gte')
    date_to = django_filters.DateFilter(field_name='created_at', lookup_expr='date__lte')

    class Meta:
        model = StockOperation
        fields = ['kind', 'reason', 'created_by', 'stock_count', 'variant', 'product', 'search', 'date_from', 'date_to']

    @staticmethod
    def _has_line(**lookups):
        # Exists en vez de join: no duplica filas ni altera las anotaciones de totales.
        return Exists(StockMovement.objects.filter(operation=OuterRef('pk'), **lookups))

    def filter_variant(self, queryset, name, value):
        return queryset.filter(self._has_line(variant_id=value))

    def filter_product(self, queryset, name, value):
        return queryset.filter(self._has_line(variant__product_id=value))

    def filter_search(self, queryset, name, value):
        value = value.strip()
        if not value:
            return queryset
        lines = Exists(
            StockMovement.objects.filter(operation=OuterRef('pk')).filter(
                Q(variant__sku__icontains=value) | Q(variant__product__name__icontains=value)
            )
        )
        return queryset.filter(Q(note__icontains=value) | lines)


class StockCountFilter(django_filters.FilterSet):
    """Filtros de recuentos: `status` (`borrador`, `confirmado`, `cancelado`), `created_by` y fechas de creación."""

    date_from = django_filters.DateFilter(field_name='created_at', lookup_expr='date__gte')
    date_to = django_filters.DateFilter(field_name='created_at', lookup_expr='date__lte')

    class Meta:
        model = StockCount
        fields = ['status', 'created_by', 'date_from', 'date_to']
