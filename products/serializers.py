import copy

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers

from core.serializers import BaseModelSerializer
from products.slugs import generate_unique_slug
from products.text import normalize_name
from products.models import Brand, Category, Color, Product, ProductModel, ProductVariant, Size

__all__ = [
    'CategorySerializer',
    'BrandSerializer',
    'ProductModelSerializer',
    'ColorSerializer',
    'SizeSerializer',
    'ProductSerializer',
    'ProductVariantSerializer',
    'ProductWithVariantsSerializer',
]


class AutoSlugMixin:
    """
    El `slug` es opcional al crear: si no llega, el backend lo genera desde
    el nombre y garantiza que sea único entre los registros activos (ver
    `products.slugs`). Al editar, omitirlo lo deja como está: la dirección no
    cambia sola cuando se renombra algo. Se normaliza a minúsculas.
    """

    SLUG_ATTEMPTS = 5

    def get_extra_kwargs(self):
        extra = super().get_extra_kwargs()
        extra.setdefault('slug', {})['required'] = False
        return extra

    def slug_prefix(self, validated_data):
        """Texto con el que desambiguar antes de numerar (por defecto, ninguno)."""
        return None

    def validate_slug(self, value):
        return value.strip().lower()

    def create(self, validated_data):
        if validated_data.get('slug'):
            return super().create(validated_data)
        tried = set()
        for _ in range(self.SLUG_ATTEMPTS):
            slug = generate_unique_slug(
                self.Meta.model,
                validated_data['name'],
                prefix=self.slug_prefix(validated_data),
                exclude=tried,
            )
            tried.add(slug)
            try:
                # Savepoint: si otra alta ganó el slug entre la consulta y el
                # INSERT, se reintenta con el siguiente candidato.
                with transaction.atomic():
                    return super().create({**validated_data, 'slug': slug})
            except IntegrityError:
                continue
        raise serializers.ValidationError(
            {'slug': 'No se pudo generar un identificador único. Enviá uno explícito.'}
        )


class UniqueNameSerializer(BaseModelSerializer):
    """
    Para los catálogos con `NormalizedNameMixin` (marca, modelo, categoría,
    color): normaliza `name` y rechaza (400) un nombre que ya exista entre los
    activos, sin distinguir mayúsculas, tildes ni espacios repetidos
    ("Nike" = "nike" = "NIKE"; "Ñandú" = "Nandu"). Las reglas viven en el
    modelo (`find_duplicate`), las mismas que usa el admin. El error trae
    `existing` con el registro que ya existe, para que el front pueda
    ofrecer "usar el existente" (el `id` viaja como texto: DRF convierte a
    string los valores de un error).
    """

    def validate_name(self, value):
        value = normalize_name(value, self.Meta.model.NAME_STYLE)
        if not value:
            raise serializers.ValidationError('Este campo no puede estar vacío.')
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        model = self.Meta.model
        if self.instance is not None and not any(f in attrs for f in ('name', *model.NAME_SCOPE)):
            return attrs  # PATCH que no toca ni el nombre ni su alcance
        candidate = copy.copy(self.instance) if self.instance is not None else model()
        for name, value in attrs.items():
            setattr(candidate, name, value)
        other = candidate.find_duplicate()
        if other is not None:
            raise serializers.ValidationError(
                {
                    'name': candidate.duplicate_message(other),
                    'existing': {'id': other.pk, 'name': other.name},
                }
            )
        return attrs


class CategorySerializer(AutoSlugMixin, UniqueNameSerializer):
    """
    Además de sus datos trae `label` y `parent_name` (para mostrar y agrupar
    sin cruzar listas) y `has_children` y `products_count` (sólo lectura)
    para que el front sepa qué categorías se pueden asignar a un producto
    (las que no tienen subcategorías) y cuáles admiten subcategorías (las que
    no tienen productos), sin recorrer toda la lista. Cuentan sólo registros
    activos. El viewset los anota en la consulta; si el serializer se usa sobre
    un objeto sin anotar (ej. la respuesta de un alta) los calcula.
    """

    has_children = serializers.SerializerMethodField()
    products_count = serializers.SerializerMethodField()
    label = serializers.SerializerMethodField(help_text='Ej.: "Vestidos › Largos" (o sólo el nombre si es principal).')
    parent_name = serializers.SerializerMethodField(help_text='Nombre de la categoría principal, o null.')

    def get_label(self, obj) -> str:
        return obj.label

    def get_parent_name(self, obj) -> str | None:
        return obj.parent.name if obj.parent_id else None

    def get_has_children(self, obj) -> bool:
        annotated = getattr(obj, 'has_children', None)
        if annotated is not None:
            return bool(annotated)
        return obj.children.filter(is_deleted=False).exists()

    def get_products_count(self, obj) -> int:
        annotated = getattr(obj, 'products_count', None)
        if annotated is not None:
            return annotated
        return obj.products.filter(is_deleted=False).count()

    def slug_prefix(self, validated_data):
        parent = validated_data.get('parent')
        return parent.slug if parent else None

    class Meta:
        model = Category
        fields = [
            'id',
            'name',
            'slug',
            'parent',
            'parent_name',
            'label',
            'has_children',
            'products_count',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def validate_parent(self, value):
        if value is None:
            return value
        if self.instance is not None and value.pk == self.instance.pk:
            raise serializers.ValidationError('Una categoría no puede ser su propio padre.')
        if value.parent_id is not None:
            raise serializers.ValidationError(
                'Sólo se permiten dos niveles: el padre debe ser una categoría raíz.'
            )
        if self.instance is not None and self.instance.children.filter(is_deleted=False).exists():
            raise serializers.ValidationError(
                'Una categoría con subcategorías no puede tener padre.'
            )
        if value.products.filter(is_deleted=False).exists():
            raise serializers.ValidationError(
                'No se pueden crear subcategorías bajo una categoría que ya tiene productos.'
            )
        return value


class BrandSerializer(AutoSlugMixin, UniqueNameSerializer):
    class Meta:
        model = Brand
        fields = ['id', 'name', 'slug', 'created_at']
        read_only_fields = ['id', 'created_at']


class ProductModelSerializer(UniqueNameSerializer):
    class Meta:
        model = ProductModel
        fields = ['id', 'name', 'brand', 'created_at']
        read_only_fields = ['id', 'created_at']


class ColorSerializer(UniqueNameSerializer):
    def validate_hex(self, value):
        # Se guarda siempre en mayúsculas (#14284B); el modelo lo repite al guardar.
        return value.strip().upper()

    class Meta:
        model = Color
        fields = ['id', 'name', 'hex', 'created_at']
        read_only_fields = ['id', 'created_at']


class SizeSerializer(UniqueNameSerializer):
    class Meta:
        model = Size
        fields = ['id', 'name', 'order', 'created_at']
        read_only_fields = ['id', 'created_at']


class _ListVariantSerializer(serializers.ModelSerializer):
    """Variante en el listado de productos: `color {id, name, hex}` y `size {id, name, order}`."""

    color = serializers.SerializerMethodField()
    size = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = ['id', 'sku', 'color', 'size']
        read_only_fields = fields

    def get_color(self, obj) -> dict:
        return {'id': obj.color_id, 'name': obj.color.name, 'hex': obj.color.hex}

    def get_size(self, obj) -> dict:
        return {'id': obj.size_id, 'name': obj.size.name, 'order': obj.size.order}


class ProductSerializer(AutoSlugMixin, BaseModelSerializer):
    """
    `current_price` e `is_on_promo` son de sólo lectura y se calculan con la
    fecha de hoy. `cost_price` sólo existe (lectura y escritura) para quien
    tiene el permiso `products.view_cost_price`; para el resto el campo se
    omite de la respuesta y se ignora si lo envía.

    `variants_count` (variantes activas) lo ve cualquiera que vea productos.
    `variants` (las activas, ordenadas por color y talle) sólo aparece en el
    listado y para quien tiene `products.view_productvariant`.
    """

    current_price = serializers.SerializerMethodField()
    is_on_promo = serializers.SerializerMethodField()
    # Nombres para mostrar sin consultar los catálogos aparte (sólo lectura).
    category_label = serializers.SerializerMethodField(help_text='Ej.: "Vestidos › Largos".')
    brand_name = serializers.SerializerMethodField()
    product_model_name = serializers.SerializerMethodField()
    variants_count = serializers.SerializerMethodField(help_text='Cantidad de variantes activas.')
    variants = _ListVariantSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            'id',
            'name',
            'slug',
            'is_published',
            'description',
            'category',
            'category_label',
            'brand',
            'brand_name',
            'product_model',
            'product_model_name',
            'cost_price',
            'sale_price',
            'promo_price',
            'promo_start',
            'promo_end',
            'current_price',
            'is_on_promo',
            'variants_count',
            'variants',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def get_extra_kwargs(self):
        extra = super().get_extra_kwargs()
        # `slug: ""` es válido: pide regenerar la dirección desde el nombre (ver `update`).
        extra['slug']['allow_blank'] = True
        return extra

    def update(self, instance, validated_data):
        """
        Un `slug` vacío regenera la dirección desde el nombre (con la
        numeración habitual si ya existe), pero sólo mientras el producto no
        esté publicado: la dirección de uno publicado ya puede estar en
        enlaces externos. Omitir `slug` lo deja como está; uno explícito se
        respeta (y puede dar 400 si ya está en uso).
        """
        if validated_data.get('slug', None) != '':
            return super().update(instance, validated_data)
        if validated_data.get('is_published', instance.is_published):
            raise serializers.ValidationError(
                {'slug': 'No se puede regenerar la dirección de un producto publicado.'}
            )
        name = validated_data.get('name', instance.name)
        tried = set()
        for _ in range(self.SLUG_ATTEMPTS):
            slug = generate_unique_slug(Product, name, exclude=tried, exclude_pk=instance.pk)
            tried.add(slug)
            try:
                with transaction.atomic():
                    return super().update(instance, {**validated_data, 'slug': slug})
            except IntegrityError:
                continue
        raise serializers.ValidationError(
            {'slug': 'No se pudo generar un identificador único. Enviá uno explícito.'}
        )

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if user is None or not user.has_perm('products.view_cost_price'):
            fields.pop('cost_price', None)
        if not self._include_variants(user):
            fields.pop('variants', None)
        return fields

    def _include_variants(self, user) -> bool:
        view = self.context.get('view')
        if getattr(view, 'action', None) != 'list':
            return False
        return user is not None and user.has_perm('products.view_productvariant')

    def get_variants_count(self, obj) -> int:
        annotated = getattr(obj, 'variants_count', None)
        if annotated is not None:
            return annotated
        return obj.variants.filter(is_deleted=False).count()

    def get_category_label(self, obj) -> str:
        return obj.category.label

    def get_brand_name(self, obj) -> str | None:
        return obj.brand.name if obj.brand_id else None

    def get_product_model_name(self, obj) -> str | None:
        return obj.product_model.name if obj.product_model_id else None

    def get_current_price(self, obj) -> str:
        return str(obj.get_current_price())

    def get_is_on_promo(self, obj) -> bool:
        return obj.is_on_promo()

    def validate(self, attrs):
        attrs = super().validate(attrs)
        # Las reglas viven en `Product.clean()`: se aplican sobre una copia
        # con los valores nuevos, sin tocar la instancia real.
        candidate = copy.copy(self.instance) if self.instance is not None else Product()
        for name, value in attrs.items():
            setattr(candidate, name, value)
        try:
            candidate.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        if candidate.brand_id is not None and attrs.get('brand') is None:
            attrs['brand'] = candidate.brand  # marca derivada del modelo
        return attrs


class ProductVariantSerializer(BaseModelSerializer):
    """
    Se escribe con `product`, `color` y `size` (ids). Los demás campos son de
    sólo lectura y evitan consultar otros endpoints para armar la grilla:
    nombres de producto/color/talle, categoría, marca, modelo y precios del
    producto (el costo no se expone acá).
    """

    product_name = serializers.CharField(source='product.name', read_only=True)
    category = serializers.IntegerField(source='product.category_id', read_only=True)
    category_label = serializers.CharField(source='product.category.label', read_only=True)
    brand = serializers.IntegerField(source='product.brand_id', read_only=True)
    brand_name = serializers.CharField(source='product.brand.name', read_only=True, default=None)
    product_model = serializers.IntegerField(source='product.product_model_id', read_only=True)
    product_model_name = serializers.CharField(source='product.product_model.name', read_only=True, default=None)
    is_published = serializers.BooleanField(source='product.is_published', read_only=True)
    color_name = serializers.CharField(source='color.name', read_only=True)
    color_hex = serializers.CharField(source='color.hex', read_only=True)
    size_name = serializers.CharField(source='size.name', read_only=True)
    sale_price = serializers.DecimalField(source='product.sale_price', max_digits=12, decimal_places=2, read_only=True)
    promo_price = serializers.DecimalField(source='product.promo_price', max_digits=12, decimal_places=2, read_only=True)
    promo_start = serializers.DateField(source='product.promo_start', read_only=True)
    promo_end = serializers.DateField(source='product.promo_end', read_only=True)
    current_price = serializers.SerializerMethodField()
    is_on_promo = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = [
            'id', 'sku', 'created_at',
            'product', 'product_name', 'is_published',
            'category', 'category_label', 'brand', 'brand_name', 'product_model', 'product_model_name',
            'color', 'color_name', 'color_hex', 'size', 'size_name',
            'sale_price', 'promo_price', 'promo_start', 'promo_end', 'current_price', 'is_on_promo',
        ]
        read_only_fields = ['id', 'sku', 'created_at']

    def get_current_price(self, obj) -> str:
        return str(obj.product.get_current_price())

    def get_is_on_promo(self, obj) -> bool:
        return obj.product.is_on_promo()

    def validate_product(self, value):
        if self.instance is not None and value.pk != self.instance.product_id:
            raise serializers.ValidationError('No se puede cambiar el producto de una variante.')
        return value

    def validate(self, attrs):
        # La unicidad (producto, color, talle) la valida BaseModelSerializer;
        # acá sólo se traduce su mensaje genérico a uno entendible.
        try:
            return super().validate(attrs)
        except serializers.ValidationError as exc:
            if isinstance(exc.detail, list):
                raise serializers.ValidationError(
                    'Ya existe una variante de este producto con ese color y talle.'
                ) from exc
            raise


class _VariantSummarySerializer(serializers.ModelSerializer):
    """Variante anidada en el producto, con color y talle ya resueltos."""

    color = ColorSerializer(read_only=True)
    size = SizeSerializer(read_only=True)

    class Meta:
        model = ProductVariant
        fields = ['id', 'sku', 'color', 'size']
        read_only_fields = fields


class ProductWithVariantsSerializer(ProductSerializer):
    """
    `ProductSerializer` más `variants` (sólo las activas, de sólo lectura,
    ordenadas por color y talle). Mismas reglas del costo que el producto.
    """

    variants = _VariantSummarySerializer(many=True, read_only=True)

    def _include_variants(self, user) -> bool:
        return True  # el endpoint ya exige `view_productvariant`
