import django_filters

from django.db.models import Case, DecimalField, Exists, F, OuterRef, Q, When
from django.utils import timezone

from products.models import Category, Product, ProductModel, ProductVariant

__all__ = ['CategoryFilter', 'ProductModelFilter', 'ProductFilter', 'ProductVariantFilter', 'effective_price']


def effective_price(today=None, prefix=''):
    """
    Precio vigente en SQL (espeja `Product.get_current_price`). `prefix` es la
    ruta hasta el producto (`'product__'` desde una variante).
    """
    today = today or timezone.localdate()
    return Case(
        When(
            Q(**{f'{prefix}promo_price__isnull': False, f'{prefix}promo_start__lte': today, f'{prefix}promo_end__gte': today}),
            then=F(f'{prefix}promo_price'),
        ),
        default=F(f'{prefix}sale_price'),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )


class CategoryFilter(django_filters.FilterSet):
    """
    Filtros del listado de categorías:

      * `parent`: id de la categoría padre (devuelve sus hijas).
      * `root`: `true` sólo raíces, `false` sólo subcategorías.
      * `leaf`: `true` sólo las categorías sin subcategorías (las únicas que
        se pueden asignar a un producto), `false` sólo las que tienen.
    """

    root = django_filters.BooleanFilter(field_name='parent', lookup_expr='isnull')
    leaf = django_filters.BooleanFilter(method='filter_leaf')

    class Meta:
        model = Category
        fields = ['parent', 'root', 'leaf']

    def filter_leaf(self, queryset, name, value):
        has_children = Exists(Category.objects.filter(parent=OuterRef('pk')))
        return queryset.filter(~has_children if value else has_children)


class ProductModelFilter(django_filters.FilterSet):
    class Meta:
        model = ProductModel
        fields = ['brand']


class ProductFilter(django_filters.FilterSet):
    """
    Filtros del listado de productos:

      * `category`: id de una categoría. Si es una raíz, incluye también los
        productos de sus subcategorías.
      * `brand`, `product_model`: ids.
      * `is_published`: `true`/`false` según esté publicado en la tienda.
      * `on_promo`: `true` sólo los que hoy tienen la promoción vigente,
        `false` los que no.
      * `min_price` / `max_price`: rango sobre el precio vigente (inclusivo).
      * `has_variants`: `true` los que tienen al menos una variante activa,
        `false` los que no tienen ninguna (todavía no se pueden publicar).
    """

    category = django_filters.NumberFilter(method='filter_category')
    on_promo = django_filters.BooleanFilter(method='filter_on_promo')
    has_variants = django_filters.BooleanFilter(method='filter_has_variants')
    min_price = django_filters.NumberFilter(field_name='effective_price', lookup_expr='gte')
    max_price = django_filters.NumberFilter(field_name='effective_price', lookup_expr='lte')

    class Meta:
        model = Product
        fields = [
            'category', 'brand', 'product_model', 'is_published', 'on_promo', 'has_variants',
            'min_price', 'max_price',
        ]

    def filter_has_variants(self, queryset, name, value):
        return queryset.filter(variants_count__gt=0) if value else queryset.filter(variants_count=0)

    def filter_category(self, queryset, name, value):
        return queryset.filter(Q(category_id=value) | Q(category__parent_id=value))

    def filter_on_promo(self, queryset, name, value):
        today = timezone.localdate()
        active = Q(promo_price__isnull=False, promo_start__lte=today, promo_end__gte=today)
        return queryset.filter(active) if value else queryset.exclude(active)


class ProductVariantFilter(django_filters.FilterSet):
    """
    Filtros del listado de variantes (la grilla):

      * `product`, `color`, `size`: ids.
      * `category`: id; si es una raíz incluye las subcategorías.
      * `brand`, `product_model`: ids del producto.
      * `is_published`: `true`/`false` según el producto esté publicado.
      * `on_promo`: `true` si hoy el producto tiene la promoción vigente.
      * `min_price` / `max_price`: rango sobre el precio vigente (inclusivo).
    """

    category = django_filters.NumberFilter(method='filter_category')
    brand = django_filters.NumberFilter(field_name='product__brand_id')
    product_model = django_filters.NumberFilter(field_name='product__product_model_id')
    is_published = django_filters.BooleanFilter(field_name='product__is_published')
    on_promo = django_filters.BooleanFilter(method='filter_on_promo')
    min_price = django_filters.NumberFilter(field_name='effective_price', lookup_expr='gte')
    max_price = django_filters.NumberFilter(field_name='effective_price', lookup_expr='lte')

    class Meta:
        model = ProductVariant
        fields = [
            'product', 'color', 'size', 'category', 'brand', 'product_model',
            'is_published', 'on_promo', 'min_price', 'max_price',
        ]

    def filter_category(self, queryset, name, value):
        return queryset.filter(Q(product__category_id=value) | Q(product__category__parent_id=value))

    def filter_on_promo(self, queryset, name, value):
        today = timezone.localdate()
        active = Q(
            product__promo_price__isnull=False, product__promo_start__lte=today, product__promo_end__gte=today
        )
        return queryset.filter(active) if value else queryset.exclude(active)
