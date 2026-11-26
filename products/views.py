from django.db.models import Case, Count, DecimalField, Exists, F, IntegerField, OuterRef, Prefetch, Q, Value, When
from django.db.models.functions import Coalesce, Lower
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from core.viewsets import BaseModelViewSet, RestoreModelMixin
from products.filters import effective_price, CategoryFilter, ProductFilter, ProductModelFilter, ProductVariantFilter
from products.models import Brand, Category, Color, Product, ProductModel, ProductVariant, Size
from products.schemas import (
    BRAND_VIEWSET_SCHEMA,
    CATEGORY_VIEWSET_SCHEMA,
    COLOR_VIEWSET_SCHEMA,
    PRODUCT_MODEL_VIEWSET_SCHEMA,
    PRODUCT_VARIANT_VIEWSET_SCHEMA,
    PRODUCT_VIEWSET_SCHEMA,
    SIZE_VIEWSET_SCHEMA,
)
from products.serializers import (
    BrandSerializer,
    CategorySerializer,
    ColorSerializer,
    ProductModelSerializer,
    ProductSerializer,
    ProductVariantSerializer,
    ProductWithVariantsSerializer,
    SizeSerializer,
)


@CATEGORY_VIEWSET_SCHEMA
class CategoryViewSet(RestoreModelMixin, BaseModelViewSet):
    queryset = Category.objects.select_related('parent')
    serializer_class = CategorySerializer
    filterset_class = CategoryFilter
    search_fields = ['name', 'slug']
    ordering = ['group_key', 'level', 'name_key', 'id']

    def get_queryset(self):
        # Orden alfabético por categoría principal y, dentro de cada una, por
        # nombre (la principal primero): así un selector agrupado no
        # necesita reordenar en el front. `Lower` lo hace independiente de
        # mayúsculas aunque el collation de la base no lo sea.
        return super().get_queryset().annotate(
            group_key=Lower(Coalesce('parent__name', 'name')),
            level=Case(When(parent__isnull=True, then=Value(0)), default=Value(1), output_field=IntegerField()),
            name_key=Lower('name'),
            has_children=Exists(Category.objects.filter(parent=OuterRef('pk'), is_deleted=False)),
            products_count=Count('products', filter=Q(products__is_deleted=False)),
        )

    def perform_destroy(self, instance):
        if instance.children.filter(is_deleted=False).exists():
            raise ValidationError('No se puede eliminar una categoría que tiene subcategorías.')
        if instance.products.filter(is_deleted=False).exists():
            raise ValidationError('No se puede eliminar una categoría que tiene productos.')
        super().perform_destroy(instance)


@BRAND_VIEWSET_SCHEMA
class BrandViewSet(RestoreModelMixin, BaseModelViewSet):
    queryset = Brand.objects.all()
    serializer_class = BrandSerializer
    search_fields = ['name', 'slug']
    ordering = ['name_key', 'id']

    def get_queryset(self):
        return super().get_queryset().annotate(name_key=Lower('name'))

    def perform_destroy(self, instance):
        if instance.models.filter(is_deleted=False).exists():
            raise ValidationError('No se puede eliminar una marca que tiene modelos.')
        if instance.products.filter(is_deleted=False).exists():
            raise ValidationError('No se puede eliminar una marca que tiene productos.')
        super().perform_destroy(instance)


@PRODUCT_MODEL_VIEWSET_SCHEMA
class ProductModelViewSet(RestoreModelMixin, BaseModelViewSet):
    queryset = ProductModel.objects.select_related('brand')
    serializer_class = ProductModelSerializer
    filterset_class = ProductModelFilter
    search_fields = ['name', 'brand__name']
    ordering = ['brand_key', 'name_key', 'id']

    def get_queryset(self):
        return super().get_queryset().annotate(brand_key=Lower('brand__name'), name_key=Lower('name'))

    def perform_destroy(self, instance):
        if instance.products.filter(is_deleted=False).exists():
            raise ValidationError('No se puede eliminar un modelo que tiene productos.')
        super().perform_destroy(instance)


@COLOR_VIEWSET_SCHEMA
class ColorViewSet(RestoreModelMixin, BaseModelViewSet):
    queryset = Color.objects.all()
    serializer_class = ColorSerializer
    search_fields = ['name']
    ordering = ['name_key', 'id']

    def get_queryset(self):
        return super().get_queryset().annotate(name_key=Lower('name'))

    def perform_destroy(self, instance):
        if instance.variants.filter(is_deleted=False).exists():
            raise ValidationError('No se puede eliminar un color que tiene variantes.')
        super().perform_destroy(instance)


@SIZE_VIEWSET_SCHEMA
class SizeViewSet(RestoreModelMixin, BaseModelViewSet):
    queryset = Size.objects.all()
    serializer_class = SizeSerializer
    search_fields = ['name']
    ordering = ['order', 'name', 'id']

    def perform_destroy(self, instance):
        if instance.variants.filter(is_deleted=False).exists():
            raise ValidationError('No se puede eliminar un talle que tiene variantes.')
        super().perform_destroy(instance)


@PRODUCT_VIEWSET_SCHEMA
class ProductViewSet(RestoreModelMixin, BaseModelViewSet):
    queryset = Product.objects.select_related('category__parent', 'brand', 'product_model')
    serializer_class = ProductSerializer
    filterset_class = ProductFilter
    search_fields = ['name', 'slug', 'brand__name', 'product_model__name']
    ordering_fields = ['name', 'sale_price', 'effective_price', 'created_at', 'variants_count']
    ordering = ['name', 'id']

    def perform_destroy(self, instance):
        if instance.variants.filter(is_deleted=False).exists():
            raise ValidationError('No se puede eliminar un producto que tiene variantes.')
        super().perform_destroy(instance)

    @action(detail=True, methods=['get'], url_path='with-variants')
    def with_variants(self, request, pk=None):
        # Devuelve datos de variantes: además de `view_product` (lo exige el
        # permiso del viewset para GET) pide `view_productvariant`.
        if not request.user.has_perm('products.view_productvariant'):
            raise PermissionDenied()
        product = self.get_object()
        return Response(ProductWithVariantsSerializer(product, context=self.get_serializer_context()).data)

    def get_queryset(self):
        # `effective_price` espeja `Product.get_current_price` en SQL, para
        # poder filtrar/ordenar por el precio vigente.
        queryset = super().get_queryset()
        if self.action == 'with_variants':
            queryset = queryset.prefetch_related(
                Prefetch(
                    'variants',
                    queryset=ProductVariant.objects.select_related('color', 'size').order_by(
                        'color__name', 'size__order', 'id'
                    ),
                )
            )
        if self.action == 'list':
            queryset = queryset.prefetch_related(
                Prefetch(
                    'variants',
                    queryset=ProductVariant.objects.filter(is_deleted=False)
                    .select_related('color', 'size')
                    .order_by('color__name', 'size__order', 'id'),
                )
            )
        return queryset.annotate(
            effective_price=effective_price(),
            variants_count=Count('variants', filter=Q(variants__is_deleted=False)),
        )


@PRODUCT_VARIANT_VIEWSET_SCHEMA
class ProductVariantViewSet(RestoreModelMixin, BaseModelViewSet):
    queryset = ProductVariant.objects.select_related(
        'product__category__parent', 'product__brand', 'product__product_model', 'color', 'size'
    )
    serializer_class = ProductVariantSerializer
    filterset_class = ProductVariantFilter
    search_fields = ['sku', 'product__name', 'product__brand__name', 'product__product_model__name', 'color__name', 'size__name']
    ordering_fields = [
        'sku', 'created_at', 'product__name', 'color__name', 'size__order', 'effective_price', 'product__sale_price',
    ]
    ordering = ['product__name', 'color__name', 'size__order', 'id']

    def get_queryset(self):
        return super().get_queryset().annotate(effective_price=effective_price(prefix='product__'))

    def perform_destroy(self, instance):
        product = instance.product
        if product.is_published and not (
            product.variants.filter(is_deleted=False).exclude(pk=instance.pk).exists()
        ):
            raise ValidationError(
                'No se puede eliminar la última variante de un producto publicado. '
                'Despublicá el producto primero.'
            )
        super().perform_destroy(instance)
