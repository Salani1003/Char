"""
Documentación OpenAPI (drf-spectacular) de las views de `products`.

Ver `core/schemas.py` para la convención general del proyecto: la
documentación vive acá, no en `views.py`. Los cinco catálogos comparten la
misma forma de CRUD + restore, así que se generan con `_catalog_schema`.
"""
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema, extend_schema_view

from core.schemas import FORBIDDEN, NOT_FOUND, UNAUTHORIZED, VALIDATION_ERROR
from products.serializers import ProductWithVariantsSerializer

__all__ = [
    'CATEGORY_VIEWSET_SCHEMA',
    'BRAND_VIEWSET_SCHEMA',
    'PRODUCT_MODEL_VIEWSET_SCHEMA',
    'COLOR_VIEWSET_SCHEMA',
    'SIZE_VIEWSET_SCHEMA',
    'PRODUCT_VIEWSET_SCHEMA',
    'PRODUCT_VARIANT_VIEWSET_SCHEMA',
    'PRODUCT_IMAGE_VIEWSET_SCHEMA',
]


_NAME_RULE = (
    'El nombre se normaliza al guardar (espacios colapsados; si llega todo en minúsculas se '
    'capitaliza, si ya trae mayúsculas se respeta) y no puede repetirse entre los activos sin '
    'distinguir mayúsculas, tildes ni espacios repetidos: “Nike”, “nike” y “NIKE” son la misma '
    'marca. Si ya existe, responde 400 con `name` (mensaje) y `existing` (`id` y `name` del '
    'registro existente, para ofrecer usarlo; el `id` viaja como texto).'
)


def _catalog_schema(*, tag, singular, plural, model, example, request_example, list_extra='', delete_extra='', create_extra=None, extra_views=None, restorable=True):
    """
    `singular`/`plural` con artículo ("una marca", "las marcas") ya resuelto
    por quien llama, para no adivinar género en español.
    `model` es el nombre del modelo en minúsculas (para los permisos).
    """
    perm = lambda action: f'`products.{action}_{model}`'  # noqa: E731
    id_param = OpenApiParameter(
        name='id',
        location=OpenApiParameter.PATH,
        description='Identificador único.',
        type=int,
    )
    response_example = OpenApiExample(tag, value=example, response_only=True)
    views = dict(
        list=extend_schema(
            tags=[tag],
            summary=f'Listar {plural}',
            description=(
                f'Lista {plural} (excluye las eliminadas). Requiere permiso {perm("view")}. '
                f'{list_extra}Admite `search` y `ordering`.'
            ),
            responses={401: UNAUTHORIZED, 403: FORBIDDEN},
            examples=[response_example],
        ),
        retrieve=extend_schema(
            tags=[tag],
            summary=f'Obtener {singular}',
            description=f'Requiere permiso {perm("view")}.',
            parameters=[id_param],
            responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
            examples=[response_example],
        ),
        create=extend_schema(
            tags=[tag],
            summary=f'Crear {singular}',
            description=(
                f'Requiere permiso {perm("add")}. '
                + (create_extra or _NAME_RULE)
            ),
            examples=[OpenApiExample('Alta', value=request_example, request_only=True), response_example],
            responses={401: UNAUTHORIZED, 403: FORBIDDEN, 400: VALIDATION_ERROR},
        ),
        update=extend_schema(
            tags=[tag],
            summary=f'Actualizar {singular}',
            description=f'Requiere permiso {perm("change")}.',
            parameters=[id_param],
            responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND, 400: VALIDATION_ERROR},
        ),
        partial_update=extend_schema(
            tags=[tag],
            summary=f'Actualizar parcialmente {singular}',
            description=f'Requiere permiso {perm("change")}.',
            parameters=[id_param],
            responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND, 400: VALIDATION_ERROR},
        ),
        restore=extend_schema(
            tags=[tag],
            summary=f'Restaurar {singular} eliminada',
            description=(
                f'Revierte el soft delete. Requiere permiso {perm("change")}. '
                'Si el registro no está eliminado, responde 404; si su nombre ya lo tomó '
                'otro registro activo, responde 400.'
            ),
            request=None,
            parameters=[id_param],
            responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND, 400: VALIDATION_ERROR},
            examples=[response_example],
        ),
        destroy=extend_schema(
            tags=[tag],
            summary=f'Eliminar {singular}',
            description=f'Elimina (soft delete). Requiere permiso {perm("delete")}. {delete_extra}',
            parameters=[id_param],
            responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND, 400: VALIDATION_ERROR},
        ),
        **(extra_views or {}),
    )
    if not restorable:
        views.pop('restore')
    return extend_schema_view(**views)


CATEGORY_VIEWSET_SCHEMA = _catalog_schema(
    tag='Categories',
    singular='una categoría',
    plural='las categorías',
    model='category',
    example={
        'id': 2,
        'name': 'Largos',
        'slug': 'largos',
        'parent': 1,
        'parent_name': 'Vestidos',
        'label': 'Vestidos › Largos',
        'has_children': False,
        'products_count': 12,
        'created_at': '2026-01-15T12:00:00Z',
    },
    request_example={'name': 'Largos', 'parent': 1},
    list_extra=(
        'Filtros: `parent` (id del padre, devuelve sus hijas) y `root` (`true` sólo raíces, '
        '`false` sólo subcategorías), `leaf` (`true` sólo las categorías sin subcategorías, que son las únicas '
        'asignables a un producto; `false` sólo las que tienen). Cada categoría trae `label` ("Vestidos › Largos"), `parent_name`, `has_children` y '
        '`products_count` (sólo activos, de sólo lectura): una categoría con productos no admite '
        'subcategorías y una con subcategorías no se asigna a productos. Hay dos niveles como máximo. Orden por defecto: alfabético por '
        'categoría principal (la principal primero) y luego por nombre, sin distinguir mayúsculas, '
        'listo para mostrar agrupado en un selector. '
    ),
    create_extra=(
        'El `slug` es opcional: si no se envía, se genera desde el nombre (si ya existe, se antepone '
        'el slug del padre y, si aún choca, se numera: `largos`, `vestidos-largos`, `largos-2`). '
        'Debe ser único entre las activas y se guarda en minúsculas. ' + _NAME_RULE + ' En categorías '
        'y modelos la unicidad es entre hermanas (mismo padre) o dentro de la misma marca.'
    ),
    delete_extra='No se puede eliminar una categoría que tiene subcategorías ni productos activos.',
)

BRAND_VIEWSET_SCHEMA = _catalog_schema(
    tag='Brands',
    singular='una marca',
    plural='las marcas',
    model='brand',
    example={'id': 1, 'name': 'Marca X', 'slug': 'marca-x', 'created_at': '2026-01-15T12:00:00Z'},
    request_example={'name': 'Marca X'},
    list_extra='Orden por defecto: alfabético por nombre, sin distinguir mayúsculas. ',
    create_extra=(
        'El `slug` es opcional: si no se envía, se genera desde el nombre y se numera si ya existe '
        '(`marca-x`, `marca-x-2`). Debe ser único entre las activas. ' + _NAME_RULE
    ),
    delete_extra='No se puede eliminar una marca que tiene modelos ni productos activos.',
)

PRODUCT_MODEL_VIEWSET_SCHEMA = _catalog_schema(
    tag='Product models',
    singular='un modelo',
    plural='los modelos',
    model='productmodel',
    example={'id': 1, 'name': 'Aurora', 'brand': 1, 'created_at': '2026-01-15T12:00:00Z'},
    request_example={'name': 'Aurora', 'brand': 1},
    list_extra=(
        'Filtro: `brand` (id de la marca). El nombre es único dentro de cada marca. Orden por defecto: '
        'alfabético por marca y luego por nombre, sin distinguir mayúsculas. '
    ),
)

COLOR_VIEWSET_SCHEMA = _catalog_schema(
    tag='Colors',
    singular='un color',
    plural='los colores',
    model='color',
    example={'id': 1, 'name': 'Azul', 'hex': '#1F4E9E', 'created_at': '2026-01-15T12:00:00Z'},
    request_example={'name': 'Azul', 'hex': '#1F4E9E'},
    list_extra=(
        'Orden por defecto: alfabético por nombre, sin distinguir mayúsculas. `hex` es opcional '
        '(`#RRGGBB`) y se guarda siempre en mayúsculas.'
    ),
)

SIZE_VIEWSET_SCHEMA = _catalog_schema(
    tag='Sizes',
    singular='un talle',
    plural='los talles',
    model='size',
    example={'id': 1, 'name': 'M', 'order': 3, 'created_at': '2026-01-15T12:00:00Z'},
    request_example={'name': 'M', 'order': 3},
    create_extra=(
        'El nombre se guarda siempre en MAYÚSCULAS ("xl" -> "XL") con los espacios colapsados, y no '
        'puede repetirse entre los activos sin distinguir mayúsculas, tildes ni espacios repetidos. '
        'Si ya existe, responde 400 con `name` (mensaje) y `existing` (`id` y `name` del existente). '
        '`order` define el orden de presentación (menor primero).'
    ),
    list_extra='Se ordenan por `order` y luego por nombre. ',
)

PRODUCT_VIEWSET_SCHEMA = _catalog_schema(
    tag='Products',
    singular='un producto',
    plural='los productos',
    model='product',
    example={
        'id': 1,
        'name': 'Vestido Aurora',
        'slug': 'vestido-aurora',
        'is_published': False,
        'description': 'Vestido largo de fiesta.',
        'category': 2,
        'category_label': 'Vestidos › Largos',
        'brand': 1,
        'brand_name': 'Marca X',
        'product_model': 1,
        'product_model_name': 'Aurora',
        'cost_price': '40000.00',
        'sale_price': '90000.00',
        'promo_price': '75000.00',
        'promo_start': '2026-12-01',
        'promo_end': '2026-12-31',
        'current_price': '75000.00',
        'is_on_promo': True,
        'created_at': '2026-01-15T12:00:00Z',
    },
    request_example={
        'name': 'Vestido Aurora',
        'description': 'Vestido largo de fiesta.',
        'category': 2,
        'product_model': 1,
        'cost_price': '40000.00',
        'sale_price': '90000.00',
        'promo_price': '75000.00',
        'promo_start': '2026-12-01',
        'promo_end': '2026-12-31',
    },
    list_extra=(
        'Filtros: `category` (si es una raíz incluye sus subcategorías), `brand`, `product_model`, '
        '`is_published` (`true`/`false`), `on_promo` (`true`/`false`: promoción vigente hoy), `has_variants` (`true`/`false`: con o sin variantes activas), `min_price` y `max_price` (sobre el '
        'precio vigente). `current_price` es el precio promocional si hoy está dentro de '
        '`promo_start`–`promo_end` (inclusive) y el de venta si no. `cost_price` sólo aparece '
        'para quien tiene el permiso `products.view_cost_price`. Orden: `name`, `sale_price`, '
        '`effective_price` (precio vigente), `created_at` y `variants_count`; `search` busca en nombre, slug, marca y modelo. '
        '`variants_count` (variantes activas) lo ve todo el que ve productos; en este listado, quien tiene '
        '`products.view_productvariant` recibe además `variants` (`id`, `sku`, `color {id, name, hex}`, '
        '`size {id, name, order}`), ordenadas por color y talle. '
        '`category_label` ("Vestidos › Largos"), `brand_name` y `product_model_name` son de sólo lectura '
        'y evitan consultar los catálogos aparte. '
    ),
    create_extra=(
        'El `slug` (dirección en la futura tienda) es opcional: si no se envía se genera desde el '
        'nombre y se numera si ya existe; no cambia solo al renombrar. Al editar, `slug: ""` lo '
        'regenera desde el nombre, pero sólo si el producto no está publicado. '
        '`is_published` indica si el producto es visible en la tienda (por defecto `false`) y sólo se '
        'puede poner en `true` si el producto tiene al menos una variante activa **con foto** (una imagen activa de '
        'su color): por eso se crea sin publicar, se le cargan variantes y fotos y después se publica (PATCH). '
        'La exigencia rige al pasar a publicado: un producto ya publicado se puede seguir editando. '
        'La categoría debe ser una hoja (sin subcategorías). `brand` y `product_model` son '
        'opcionales; si se envía sólo el modelo, la marca se completa con la del modelo, y si se '
        'envían ambos deben coincidir. La promoción exige `promo_price`, `promo_start` y '
        '`promo_end` juntos, con desde <= hasta y precio promocional menor al de venta. '
        '`cost_price` es opcional y sólo lo lee/escribe quien tiene `products.view_cost_price` '
        '(para el resto se ignora).'
    ),
    extra_views={
        'with_variants': extend_schema(
            tags=['Products'],
            summary='Obtener un producto con sus variantes',
            description=(
                'Igual que `GET /api/products/{id}/` pero incluye `variants`: las variantes activas '
                '(`id`, `sku`, `color` y `talle` completos), ordenadas por color y talle, e `images` (las imágenes activas, '
                'ordenadas por color y `sort_order`; cada una trae `color`, `url` y `thumbnail_url`). Requiere '
                'permisos `products.view_product` y `products.view_productvariant`. El costo sigue '
                'las mismas reglas que en el detalle normal.'
            ),
            request=None,
            responses={200: ProductWithVariantsSerializer, 401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
            parameters=[
                OpenApiParameter(name='id', location=OpenApiParameter.PATH, description='Identificador único.', type=int)
            ],
        ),
    },
)

PRODUCT_VARIANT_VIEWSET_SCHEMA = _catalog_schema(
    tag='Product variants',
    singular='una variante',
    plural='las variantes',
    model='productvariant',
    example={
        'id': 1, 'sku': 'CHAR-0001', 'created_at': '2026-01-15T12:00:00Z',
        'image_url': 'https://res.cloudinary.com/demo/image/upload/f_auto,q_auto/char/products/1/abc123',
        'thumbnail_url': 'https://res.cloudinary.com/demo/image/upload/c_fill,w_400,h_400/f_auto,q_auto/char/products/1/abc123',
        'product': 1, 'product_name': 'Vestido midi', 'is_published': True,
        'category': 5, 'category_label': 'Vestidos › Largos', 'brand': 2, 'brand_name': 'Nike',
        'product_model': None, 'product_model_name': None,
        'color': 1, 'color_name': 'Azul', 'color_hex': '#14284B', 'size': 3, 'size_name': 'M',
        'sale_price': '200.00', 'promo_price': '150.00', 'promo_start': '2026-11-01', 'promo_end': '2026-11-30',
        'current_price': '150.00', 'is_on_promo': True,
    },
    request_example={'product': 1, 'color': 1, 'size': 3},
    list_extra=(
        'Pensado para la grilla: cada fila trae nombres y precios del producto y `image_url`/`thumbnail_url` (la imagen principal del producto en el color de la variante o, si no hay, la de menor `sort_order`; `null` si no tiene). Filtros: `product`, `color`, '
        '`size`, `category` (una raíz incluye sus subcategorías), `brand`, `product_model`, `is_published`, '
        '`on_promo`, `min_price` y `max_price` (sobre el precio vigente). `search` busca en SKU, producto, marca, '
        'modelo, color y talle. `ordering`: `sku`, `created_at`, `product__name`, `color__name`, `size__order`, '
        '`effective_price`, `product__sale_price` (prefijo `-` para descendente). '
    ),
    delete_extra=(
        'No se puede eliminar la última variante activa de un producto publicado ni la última variante con foto: '
        'despublicalo primero. Tampoco se puede cambiar su color si eso deja al producto publicado sin ninguna variante con foto.'
    ),
    create_extra=(
        'Una variante es la combinación producto + color + talle, única entre las activas. '
        'El `sku` (`CHAR-0001`, `CHAR-0002`…) lo asigna el sistema, es de sólo lectura y nunca se '
        'reutiliza. El producto no se puede cambiar una vez creada la variante.'
    ),
)

PRODUCT_IMAGE_VIEWSET_SCHEMA = _catalog_schema(
    tag='Product images',
    singular='una imagen de producto',
    plural='las imágenes de producto',
    model='productimage',
    restorable=False,
    example={
        'id': 1, 'product': 1, 'color': 2, 'color_name': 'Azul', 'color_hex': '#14284B',
        'storage_key': 'char/products/1/abc123',
        'url': 'https://res.cloudinary.com/demo/image/upload/f_auto,q_auto/char/products/1/abc123',
        'thumbnail_url': 'https://res.cloudinary.com/demo/image/upload/c_fill,w_400,h_400/f_auto,q_auto/char/products/1/abc123',
        'alt_text': 'Vestido midi azul, frente', 'sort_order': 0, 'is_primary': True,
        'created_at': '2026-01-15T12:00:00Z', 'updated_at': '2026-01-15T12:00:00Z',
        'created_by': 1, 'updated_by': None,
    },
    request_example={'product': 1, 'color': 2, 'alt_text': 'Vestido midi azul, frente', 'is_primary': True},
    list_extra=(
        'Filtros: `product`, `color` (la galería de un producto-color) e `is_primary`. Orden por defecto: producto, '
        'color, la principal primero y después `sort_order`. '
    ),
    delete_extra=(
        'Borra también el archivo del proveedor de imágenes y no se puede deshacer; si el proveedor falla '
        'responde 502 y la imagen NO se elimina (503 si el almacenamiento no está configurado). Si el producto está '
        'publicado, no se puede eliminar (ni mover a otro color) la última foto que lo mantiene con una variante con foto: '
        'responde 400 y hay que despublicarlo primero.'
    ),
    create_extra=(
        'Se sube con `multipart/form-data`: campo `file` (JPEG, PNG o WEBP, máx. 5 MB) más `product`, `color`, '
        '`alt_text`, `sort_order` e `is_primary`. Un producto-color admite varias imágenes (se sube una por request); si no se '
        'envía `sort_order` queda al final de la galería de ese producto-color. El backend valida el archivo por su '
        'contenido, lo sube al proveedor y guarda su clave en `storage_key` (de sólo lectura). `url` y '
        '`thumbnail_url` son las direcciones públicas. El archivo y el producto no se pueden cambiar después: se '
        'elimina la imagen y se sube otra; sí se pueden editar `color`, `alt_text`, `sort_order` e `is_primary`. '
        '`is_primary` marca la imagen principal de ese producto-color (la que muestran la grilla y la tienda): '
        'hay una sola, así que al marcar una se desmarca la anterior; la primera que se sube no queda principal '
        'sola, y si se elimina la principal no se promueve otra (mientras no haya principal se usa la de menor '
        '`sort_order`). '
        'Responde 400 si el archivo no es válido, 503 si el almacenamiento no está configurado y 502 si el '
        'proveedor falla. Un color o un producto con imágenes activas no se pueden eliminar.'
    ),
)
