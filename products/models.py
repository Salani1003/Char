from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from core.models import ACTIVE, BaseModel, unique_when_active
from products.slugs import generate_unique_slug
from products.text import STYLE_CAPITALIZE, STYLE_SENTENCE, STYLE_UPPER, STYLE_WORDS, fold_text, normalize_name

__all__ = ['Category', 'Brand', 'ProductModel', 'Color', 'Size', 'Product', 'ProductVariant', 'SkuCounter', 'ProductImage']

SKU_PREFIX = 'CHAR'
class NormalizedNameMixin:
    """
    Evita catálogos con registros repetidos ("Nike" / "nike" / "NIKE",
    "MarketPlace" / "Marketplace"): el nombre se normaliza al guardar
    (`products.text.normalize_name`) y `clean()` rechaza uno que, sin
    distinguir mayúsculas, tildes ni espacios repetidos, ya exista entre los
    registros activos (dentro de `NAME_SCOPE`, si el nombre sólo es único por
    marca o por categoría padre). Al vivir en el modelo vale igual para la
    API, el admin y la consola; el índice `Lower(name)` de cada modelo queda
    como red de seguridad de la base (no ve tildes ni espacios).
    """

    NAME_STYLE = STYLE_SENTENCE
    NAME_SCOPE: tuple[str, ...] = ()  # campos FK que acotan la unicidad (ej. ('brand',))
    DUPLICATE_LABEL = 'el registro'  # "la marca", "el color"... para el mensaje

    def normalize_name(self):
        self.name = normalize_name(self.name, self.NAME_STYLE)

    def find_duplicate(self):
        """El registro activo que choca con el nombre de éste, o `None`."""
        key = fold_text(self.name)
        siblings = type(self).objects.filter(**{f'{f}_id': getattr(self, f'{f}_id') for f in self.NAME_SCOPE})
        if self.pk is not None:
            siblings = siblings.exclude(pk=self.pk)
        for pk, name in siblings.values_list('pk', 'name'):
            if fold_text(name) == key:
                return type(self).objects.get(pk=pk)
        return None

    def duplicate_message(self, other):
        return f'Ya existe {self.DUPLICATE_LABEL} «{other.name}».'

    def clean(self):
        super().clean()
        self.normalize_name()
        other = self.find_duplicate()
        if other is not None:
            raise ValidationError({'name': self.duplicate_message(other)})

    def save(self, *args, **kwargs):
        self.normalize_name()
        super().save(*args, **kwargs)


class SlugFallbackMixin:
    """
    Al crear un registro sin `slug` (admin, shell, tests, seeds) lo genera
    desde el nombre. La API ya lo genera en el serializer, con reintento ante
    carreras; esto es sólo la red de seguridad para el resto de los caminos.
    """

    def slug_prefix(self):
        return None

    def save(self, *args, **kwargs):
        if self._state.adding and not self.slug:
            self.slug = generate_unique_slug(type(self), self.name, prefix=self.slug_prefix())
        super().save(*args, **kwargs)


_ACTIVE_ROOT = Q(is_deleted=False, parent__isnull=True)


class Category(NormalizedNameMixin, SlugFallbackMixin, BaseModel):
    """
    Categoría de producto, con a lo sumo dos niveles: una categoría raíz
    ("Vestidos") y sus hijas ("Largos", "Cortos"). Los productos se asignan
    siempre a una categoría hoja; filtrar por una raíz incluye a sus hijas.
    """

    NAME_SCOPE = ('parent',)
    DUPLICATE_LABEL = 'la categoría'

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=140)
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='children',
    )

    class Meta:
        verbose_name = 'categoría'
        verbose_name_plural = 'categorías'
        ordering = ['name']
        constraints = [
            # El nombre es único entre las hermanas activas (mismo padre). Las
            # raíces (parent NULL) necesitan su propia constraint: en SQL un
            # NULL nunca choca con otro NULL.
            models.UniqueConstraint(
                Lower('name'),
                'parent',
                condition=ACTIVE,
                name='category_name_parent_active_unique',
            ),
            models.UniqueConstraint(
                Lower('name'),
                condition=_ACTIVE_ROOT,
                name='category_root_name_active_unique',
            ),
            unique_when_active('slug', name='category_slug_active_unique'),
        ]

    def __str__(self):
        return self.name if self.parent_id is None else f'{self.parent.name} / {self.name}'

    def slug_prefix(self):
        return self.parent.slug if self.parent_id else None

    @property
    def label(self):
        """Texto para mostrar: `Vestidos › Largos` (o sólo el nombre si es una principal)."""
        return f'{self.parent.name} › {self.name}' if self.parent_id else self.name

    def clean(self):
        super().clean()
        if self.parent_id is None:
            return
        if self.pk is not None and self.parent_id == self.pk:
            raise ValidationError({'parent': 'Una categoría no puede ser su propio padre.'})
        if self.parent.parent_id is not None:
            raise ValidationError(
                {'parent': 'Sólo se permiten dos niveles: el padre debe ser una categoría raíz.'}
            )
        if self.pk is not None and self.children.filter(is_deleted=False).exists():
            raise ValidationError(
                {'parent': 'Una categoría con subcategorías no puede tener padre.'}
            )


class Brand(NormalizedNameMixin, SlugFallbackMixin, BaseModel):
    NAME_STYLE = STYLE_WORDS
    DUPLICATE_LABEL = 'la marca'

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=140)

    class Meta:
        verbose_name = 'marca'
        verbose_name_plural = 'marcas'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(Lower('name'), condition=ACTIVE, name='brand_name_active_unique'),
            unique_when_active('slug', name='brand_slug_active_unique'),
        ]

    def __str__(self):
        return self.name


class ProductModel(NormalizedNameMixin, BaseModel):
    """Modelo dentro de una marca (ej. marca X, modelo "Aurora")."""

    NAME_SCOPE = ('brand',)
    DUPLICATE_LABEL = 'el modelo'

    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name='models')
    name = models.CharField(max_length=100)

    class Meta:
        verbose_name = 'modelo'
        verbose_name_plural = 'modelos'
        ordering = ['brand__name', 'name']
        constraints = [
            models.UniqueConstraint(
                Lower('name'),
                'brand',
                condition=ACTIVE,
                name='productmodel_name_brand_active_unique',
            ),
        ]

    def __str__(self):
        return f'{self.brand.name} {self.name}'


class Color(NormalizedNameMixin, BaseModel):
    DUPLICATE_LABEL = 'el color'
    NAME_STYLE = STYLE_CAPITALIZE

    name = models.CharField(max_length=50)
    hex = models.CharField(
        'código hexadecimal',
        max_length=7,
        blank=True,
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Debe tener el formato #RRGGBB.')],
        help_text='Opcional, para mostrar el color en el front. Formato #RRGGBB.',
    )

    class Meta:
        verbose_name = 'color'
        verbose_name_plural = 'colores'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(Lower('name'), condition=ACTIVE, name='color_name_active_unique'),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # El tono se guarda siempre en mayúsculas (#14284B), venga como venga del selector.
        self.hex = self.hex.strip().upper()
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'hex' not in update_fields:
            kwargs['update_fields'] = [*update_fields, 'hex']
        super().save(*args, **kwargs)


class Size(NormalizedNameMixin, BaseModel):
    """
    Talle. Es un catálogo (y no un `choices`) porque conviven varias
    convenciones (1–6, XS–XL, talle único…); `order` define el orden de
    presentación (XS < S < M), que el alfabético no respeta.
    """

    NAME_STYLE = STYLE_UPPER
    DUPLICATE_LABEL = 'el talle'

    name = models.CharField(max_length=20)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = 'talle'
        verbose_name_plural = 'talles'
        ordering = ['order', 'name']
        constraints = [
            models.UniqueConstraint(Lower('name'), condition=ACTIVE, name='size_name_active_unique'),
        ]

    def __str__(self):
        return self.name


class Product(SlugFallbackMixin, BaseModel):
    """
    Producto: lo común a todas sus variantes (color/talle, que vienen
    después). `category` debe ser una categoría hoja. `brand` y
    `product_model` son opcionales; si hay modelo, su marca es la del producto.

    Publicación: `is_published` hace visible el producto en la tienda y sólo
    se puede activar si tiene al menos una variante activa (por eso un
    producto no puede nacer publicado: se crea, se le cargan las variantes y
    sus fotos y después se publica). Además al menos una de sus variantes debe
    tener una foto (una imagen de su color). Esa exigencia rige al *publicar*
    (un producto que ya estaba publicado no se revalida al editarlo) y, mientras
    esté publicado, la API no deja quitarle la última variante con foto
    (eliminar esa foto o esa variante, o cambiarles el color). Tampoco se puede eliminar su
    última variante activa (lo valida la API).

    Precios: `cost_price` (costo, sensible: requiere el permiso
    `products.view_cost_price`), `sale_price` (venta) y un precio promocional
    con vigencia `promo_start`–`promo_end` (ambas fechas inclusivas). El
    precio vigente (`current_price`) es el promocional si hoy cae dentro de
    ese rango y el de venta en caso contrario.
    """

    name = models.CharField(max_length=200)
    # Dirección del producto en la tienda: la genera el backend desde el nombre
    # si no se envía y no cambia sola al renombrar.
    slug = models.SlugField(max_length=220)
    description = models.TextField(blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    brand = models.ForeignKey(
        Brand, null=True, blank=True, on_delete=models.PROTECT, related_name='products'
    )
    product_model = models.ForeignKey(
        ProductModel, null=True, blank=True, on_delete=models.PROTECT, related_name='products'
    )
    cost_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    sale_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    promo_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    promo_start = models.DateField(null=True, blank=True)
    promo_end = models.DateField(null=True, blank=True)
    # Visible en la futura tienda online. Un producto nuevo nace sin publicar.
    is_published = models.BooleanField('publicado', default=False, db_index=True)

    class Meta:
        verbose_name = 'producto'
        verbose_name_plural = 'productos'
        ordering = ['name']
        permissions = [('view_cost_price', 'Puede ver y modificar el precio de costo')]
        constraints = [
            unique_when_active('slug', name='product_slug_active_unique'),
            models.CheckConstraint(
                condition=(
                    Q(promo_price__isnull=True, promo_start__isnull=True, promo_end__isnull=True)
                    | Q(promo_price__isnull=False, promo_start__isnull=False, promo_end__isnull=False)
                ),
                name='product_promo_all_or_none',
            ),
            models.CheckConstraint(
                condition=Q(promo_start__isnull=True) | Q(promo_start__lte=models.F('promo_end')),
                name='product_promo_range_valid',
            ),
        ]

    def __str__(self):
        return self.name

    def is_on_promo(self, today=None):
        if self.promo_price is None:
            return False
        today = today or timezone.localdate()
        return self.promo_start <= today <= self.promo_end

    def has_active_variants(self):
        return self.pk is not None and self.variants.filter(is_deleted=False).exists()

    def has_variant_with_image(self, *, without_image=None, without_variant=None, with_color=None):
        """
        ¿Alguna variante activa tiene al menos una foto (una imagen activa de su color)?
        Los argumentos permiten preguntar "¿y si...?" sin tocar nada: `without_image` /
        `without_variant` (pk) ignoran esa imagen o variante, y `with_color` suma ese color
        como si una variante lo usara (para cambios de color).
        """
        if self.pk is None:
            return False
        colors = set(
            self.variants.filter(is_deleted=False).exclude(pk=without_variant).values_list('color_id', flat=True)
        )
        if with_color is not None:
            colors.add(with_color.pk)
        return ProductImage.objects.filter(product=self, color_id__in=colors).exclude(pk=without_image).exists()

    def get_current_price(self, today=None):
        return self.promo_price if self.is_on_promo(today) else self.sale_price

    def _was_published(self):
        """¿Ya estaba publicado en la base? (la exigencia de fotos sólo rige al pasar a publicado)"""
        return self.pk is not None and type(self).all_objects.filter(pk=self.pk, is_published=True).exists()

    def clean(self):
        super().clean()
        errors = {}
        if self.category_id and self.category.children.filter(is_deleted=False).exists():
            errors['category'] = 'El producto debe asignarse a una categoría sin subcategorías.'
        if self.product_model_id:
            if self.brand_id is None:
                self.brand_id = self.product_model.brand_id
            elif self.brand_id != self.product_model.brand_id:
                errors['product_model'] = 'El modelo no pertenece a la marca elegida.'
        if self.is_published and not self.has_active_variants():
            errors['is_published'] = 'Sólo se pueden publicar productos que tengan variantes.'
        elif self.is_published and not self._was_published() and not self.has_variant_with_image():
            errors['is_published'] = 'Sólo se pueden publicar productos con al menos una variante que tenga foto.'
        promo = (self.promo_price, self.promo_start, self.promo_end)
        if any(v is not None for v in promo) and not all(v is not None for v in promo):
            errors['promo_price'] = 'La promoción requiere precio, fecha desde y fecha hasta.'
        elif self.promo_price is not None:
            if self.promo_start > self.promo_end:
                errors['promo_end'] = 'La fecha hasta no puede ser anterior a la fecha desde.'
            if self.sale_price is not None and self.promo_price >= self.sale_price:
                errors['promo_price'] = 'El precio promocional debe ser menor al precio de venta.'
        if errors:
            raise ValidationError(errors)


class SkuCounter(models.Model):
    """
    Contador de una sola fila (`pk=1`) para numerar los SKU. Se incrementa
    dentro de la misma transacción que crea la variante, bajo
    `select_for_update`: dos altas simultáneas no pueden obtener el mismo
    número y, si la creación falla y se revierte, el número no se pierde.
    """

    last_value = models.PositiveIntegerField(default=0)

    @classmethod
    def next_sku(cls):
        with transaction.atomic():
            counter, _ = cls.objects.select_for_update().get_or_create(pk=1)
            counter.last_value += 1
            counter.save(update_fields=['last_value'])
        return f'{SKU_PREFIX}-{counter.last_value:04d}'


class ProductVariant(BaseModel):
    """
    Combinación concreta de un producto: color + talle. Es única por
    (producto, color, talle) entre las activas. El stock se agrega más
    adelante, sobre esta misma entidad.

    El `sku` lo asigna el sistema al crearla (`CHAR-0001`, `CHAR-0002`…),
    nunca se reutiliza y no se puede modificar.
    """

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='variants')
    color = models.ForeignKey(Color, on_delete=models.PROTECT, related_name='variants')
    size = models.ForeignKey(Size, on_delete=models.PROTECT, related_name='variants')
    sku = models.CharField(max_length=64, editable=False, blank=True)

    class Meta:
        verbose_name = 'variante'
        verbose_name_plural = 'variantes'
        ordering = ['product__name', 'color__name', 'size__order']
        constraints = [
            unique_when_active('product', 'color', 'size', name='variant_product_color_size_active_unique'),
            models.UniqueConstraint(Lower('sku'), condition=ACTIVE, name='variant_sku_active_unique'),
        ]

    def __str__(self):
        return f'{self.product.name} / {self.color.name} / {self.size.name}'

    def save(self, *args, **kwargs):
        if self._state.adding and not self.sku:
            # Atómico con el INSERT: si éste falla, el número se revierte.
            with transaction.atomic():
                self.sku = SkuCounter.next_sku()
                super().save(*args, **kwargs)
            return
        super().save(*args, **kwargs)


class ProductImage(BaseModel):
    """
    Imagen de un producto en un color. Un producto-color puede tener varias
    (la galería de ese color en la tienda: la principal primero y después por
    `sort_order`); como mucho una es la principal (`is_primary`); no depende
    del talle. El archivo vive en el proveedor de imágenes (`core.media`): acá se
    guarda sólo su clave (`storage_key`), nunca el archivo. El producto no cambia
    una vez creada la imagen; el color sí (para corregir un error de carga).
    """

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='images', verbose_name='producto')
    color = models.ForeignKey(Color, on_delete=models.PROTECT, related_name='images', verbose_name='color')
    storage_key = models.CharField('clave de almacenamiento', max_length=500)
    alt_text = models.CharField('texto alternativo', max_length=200, blank=True)
    sort_order = models.PositiveIntegerField('orden', default=0)
    is_primary = models.BooleanField('principal', default=False)

    class Meta:
        verbose_name = 'imagen de producto'
        verbose_name_plural = 'imágenes de producto'
        ordering = ['product__name', 'color__name', '-is_primary', 'sort_order', 'id']
        indexes = [models.Index(fields=['product', 'color'], name='productimage_product_color_idx')]
        constraints = [
            # A lo sumo una principal activa por producto-color.
            models.UniqueConstraint(
                fields=['product', 'color'],
                condition=ACTIVE & Q(is_primary=True),
                name='productimage_one_primary_per_color',
            ),
        ]

    def __str__(self):
        return self.storage_key
