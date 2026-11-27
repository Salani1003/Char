"""
Documentación OpenAPI (drf-spectacular) de las views de `stock`.

Ver `core/schemas.py` para la convención general: la documentación vive acá,
no en `views.py`.
"""
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema, extend_schema_view

from stock.serializers import (
    StockCountBulkItemsSerializer,
    StockCountCreateSerializer,
    StockCountSerializer,
    StockMovementCreateSerializer,
    StockOperationDetailSerializer,
)
from core.schemas import FORBIDDEN, NOT_FOUND, UNAUTHORIZED, VALIDATION_ERROR

__all__ = [
    'STOCK_VIEWSET_SCHEMA', 'STOCK_OPERATION_VIEWSET_SCHEMA', 'STOCK_MOVEMENT_VIEWSET_SCHEMA', 'STOCK_COUNT_VIEWSET_SCHEMA',
]

_STOCK_EXAMPLE = {
    'id': 12, 'sku': 'CHAR-0012', 'product': 3, 'product_name': 'Vestido midi',
    'category_label': 'Vestidos › Largos', 'brand_name': 'Nike',
    'color': 1, 'color_name': 'Azul', 'color_hex': '#14284B', 'size': 3, 'size_name': 'M',
    'quantity': 2, 'min_stock': 3, 'is_low_stock': True,
    'image_url': 'https://res.cloudinary.com/demo/image/upload/f_auto,q_auto/char/products/3/abc123',
    'thumbnail_url': 'https://res.cloudinary.com/demo/image/upload/c_fill,w_400,h_400/f_auto,q_auto/char/products/3/abc123',
}

_MOVEMENT_EXAMPLE = {
    'id': 40, 'variant': 12, 'sku': 'CHAR-0012', 'product': 3, 'product_name': 'Vestido midi',
    'color_name': 'Azul', 'size_name': 'M', 'kind': 'egreso', 'kind_display': 'Egreso',
    'reason': 'rotura_merma', 'reason_display': 'Rotura / merma', 'quantity': -1,
    'stock_before': 3, 'stock_after': 2, 'note': 'Se rasgó al probarse', 'stock_count': None, 'operation': 31,
    'reverses': None, 'reverses_operation': None, 'reversed_by': None, 'reversed_by_operation': None, 'created_at': '2026-11-26T12:00:00Z',
    'created_by': 1, 'created_by_email': 'admin@demo.com',
}

STOCK_VIEWSET_SCHEMA = extend_schema_view(
    list=extend_schema(
        tags=['Stock'],
        summary='Listar el stock por variante',
        description=(
            'Todas las variantes activas con su saldo (`quantity`, 0 si nunca tuvieron movimientos), `min_stock` '
            'e `is_low_stock` (`min_stock > 0` y `quantity <= min_stock`). Requiere `stock.view_stocklevel`. '
            'Filtros: `product`, `color`, `size`, `brand`, `category` (una raíz incluye sus subcategorías), '
            '`in_stock`, `out_of_stock` y `low_stock` (incluye las agotadas que tengan mínimo). `search` busca en '
            'SKU, producto, marca, color y talle. `ordering`: `quantity`, `min_stock`, `sku`, `product__name`, '
            '`color__name`, `size__order` (prefijo `-` para descendente). `image_url` / `thumbnail_url` (400x400): la foto de la '
            'variante con el mismo criterio que `product-variants` (la principal de su color o, si no hay, la de menor orden; '
            '`null` si el color no tiene fotos). Sólo se incluyen con `products.view_productimage`; sin él van en `null`.'
        ),
        examples=[OpenApiExample('Fila', value=_STOCK_EXAMPLE, response_only=True)],
        responses={401: UNAUTHORIZED, 403: FORBIDDEN},
    ),
    retrieve=extend_schema(
        tags=['Stock'],
        summary='Ver el stock de una variante',
        description=(
            'El `id` es el de la variante. Requiere `stock.view_stocklevel`. Trae `image_url` / `thumbnail_url` igual que el listado.'
        ),
        examples=[OpenApiExample('Variante', value=_STOCK_EXAMPLE, response_only=True)],
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
    summary=extend_schema(
        tags=['Stock'],
        summary='Resumen de stock',
        description=(
            'Totales de todas las variantes activas: `variants`, `out_of_stock` (sin stock), `low_stock` '
            '(stock bajo, incluye agotadas con mínimo) y `units` (unidades totales). Requiere `stock.view_stocklevel`.'
        ),
        examples=[OpenApiExample(
            'Resumen', value={'variants': 120, 'out_of_stock': 8, 'low_stock': 14, 'units': 530}, response_only=True,
        )],
        responses={200: OpenApiResponse(description='Totales.'), 401: UNAUTHORIZED, 403: FORBIDDEN},
    ),
)

_OPERATION_EXAMPLE = {
    'id': 31, 'kind': 'ingreso', 'kind_display': 'Ingreso', 'reason': 'compra', 'reason_display': 'Compra',
    'note': 'Pedido proveedor Norte', 'stock_count': None, 'lines_count': 2, 'units': 8,
    'created_at': '2026-11-27T12:00:00Z', 'created_by': 1, 'created_by_email': 'admin@demo.com',
}

STOCK_OPERATION_VIEWSET_SCHEMA = extend_schema_view(
    list=extend_schema(
        tags=['Stock operations'],
        summary='Historial de operaciones de stock',
        description=(
            'Es el historial principal: cada ingreso o egreso en lote, cada recuento confirmado y cada anulación es '
            'UNA operación (una fila), con `lines_count` (variantes) y `units` (unidades movidas). Para ver las '
            'líneas, `GET stock-operations/{id}/`. Requiere `stock.view_stockmovement`. Filtros: `kind` (`ingreso`, '
            '`egreso`, `ajuste`), `reason`, `created_by`, `stock_count`, `variant` y `product` (operaciones que '
            'tocaron esa variante o ese producto), `search` (nota, SKU o producto) y `date_from` / `date_to` '
            '(YYYY-MM-DD, inclusivos). `ordering`: `created_at`, `units`, `lines_count`. Más nuevas primero.'
        ),
        examples=[OpenApiExample('Operación', value=_OPERATION_EXAMPLE, response_only=True)],
        responses={401: UNAUTHORIZED, 403: FORBIDDEN},
    ),
    retrieve=extend_schema(
        tags=['Stock operations'],
        summary='Ver una operación con sus líneas',
        description=(
            'Trae los mismos campos que el listado más `movements`: una línea por variante (con SKU, producto, '
            'color, talle, cantidad con signo, stock antes y después, y `reversed_by` si fue anulada). Un recuento '
            'sin diferencias es una operación sin líneas. Requiere `stock.view_stockmovement`.'
        ),
        examples=[OpenApiExample(
            'Operación con líneas', value={**_OPERATION_EXAMPLE, 'movements': [_MOVEMENT_EXAMPLE]}, response_only=True,
        )],
        responses={200: StockOperationDetailSerializer, 401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
    create=extend_schema(
        tags=['Stock operations'],
        summary='Registrar un ingreso o egreso (en lote)',
        description=(
            'Requiere `stock.add_stockmovement`. Crea UNA operación con una línea (movimiento) por variante. Es '
            'atómico: si una línea falla (ej. un egreso sin stock suficiente: 400 con `detail`, `variant`, '
            '`available` y `requested`, que viajan como texto) no se aplica ninguna. Una variante no puede '
            'repetirse en el lote. Las cantidades son positivas; el signo lo da `kind`. Motivos de ingreso: '
            '`compra`, `cambio_entrada`, `stock_inicial`, `otro`. De egreso: `rotura_merma`, `perdida`, '
            '`uso_interno`, `devolucion_proveedor`, `cambio_salida`, `otro`. Responde con la operación y sus '
            'líneas. Nada se edita ni se elimina: un error se corrige anulando una línea con '
            '`POST stock-movements/{id}/reverse/`.'
        ),
        request=StockMovementCreateSerializer,
        examples=[
            OpenApiExample(
                'Ingreso de stock inicial',
                value={'kind': 'ingreso', 'reason': 'stock_inicial', 'note': '',
                       'items': [{'variant': 12, 'quantity': 5}, {'variant': 13, 'quantity': 3}]},
                request_only=True,
            ),
            OpenApiExample(
                'Stock insuficiente',
                value={'detail': 'Stock insuficiente para CHAR-0012: disponible 2, solicitado 3.',
                       'variant': '12', 'available': '2', 'requested': '3'},
                response_only=True, status_codes=['400'],
            ),
        ],
        responses={201: StockOperationDetailSerializer, 400: VALIDATION_ERROR, 401: UNAUTHORIZED, 403: FORBIDDEN},
    ),
)

STOCK_MOVEMENT_VIEWSET_SCHEMA = extend_schema_view(
    list=extend_schema(
        tags=['Stock movements'],
        summary='Listar las líneas (movimientos) de stock',
        description=(
            'Un movimiento por variante: sirve para ver el historial de UNA variante (`?variant=`). El historial general, '
            'agrupado por operación, es `stock-operations/`. Requiere `stock.view_stockmovement`. Filtros: `variant`, '
            '`product`, `operation`, `kind` (`ingreso`, `egreso`, `ajuste`), `reason`, `created_by`, `stock_count`, '
            '`date_from` y `date_to` (YYYY-MM-DD, inclusivos). `search` busca en SKU, producto y nota. Más nuevos primero.'
        ),
        examples=[OpenApiExample('Movimiento', value=_MOVEMENT_EXAMPLE, response_only=True)],
        responses={401: UNAUTHORIZED, 403: FORBIDDEN},
    ),
    retrieve=extend_schema(
        tags=['Stock movements'],
        summary='Ver un movimiento de stock',
        description='Requiere `stock.view_stockmovement`.',
        examples=[OpenApiExample('Movimiento', value=_MOVEMENT_EXAMPLE, response_only=True)],
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
    reverse=extend_schema(
        tags=['Stock movements'],
        summary='Anular un movimiento',
        description=(
            'Requiere `stock.add_stockmovement`. Crea el movimiento inverso (motivo `anulacion`, en su propia operación) enlazado al '
            'original. Un movimiento se anula una sola vez; no se anulan las anulaciones ni los ajustes (los de '
            'recuento se corrigen con otro recuento). Si el saldo ya no alcanza para deshacerlo, responde 400.'
        ),
        examples=[OpenApiExample('Solicitud', value={'note': 'Me equivoqué de talle'}, request_only=True)],
        responses={201: OpenApiResponse(description='Movimiento de anulación.'), 400: VALIDATION_ERROR,
                   401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
)

_COUNT_EXAMPLE = {
    'id': 7, 'status': 'confirmado', 'status_display': 'Confirmado', 'note': 'Recuento de vidriera',
    'items_count': 1,
    'items': [{
        'id': 21, 'variant': 12, 'sku': 'CHAR-0012', 'product_name': 'Vestido midi', 'color_name': 'Azul',
        'size_name': 'M', 'counted_quantity': 4, 'system_quantity': 5, 'difference': -1,
    }],
    'created_at': '2026-11-26T12:00:00Z', 'created_by': 1, 'created_by_email': 'admin@demo.com',
    'confirmed_at': '2026-11-26T12:30:00Z', 'confirmed_by': 1, 'confirmed_by_email': 'admin@demo.com',
}
_NOT_DRAFT = 'Sólo en borrador: un recuento confirmado o cancelado responde 400.'

STOCK_COUNT_VIEWSET_SCHEMA = extend_schema_view(
    list=extend_schema(
        tags=['Stock counts'],
        summary='Listar recuentos',
        description=(
            'Requiere `stock.view_stockcount`. Filtros: `status` (`borrador`, `confirmado`, `cancelado`), '
            '`created_by`, `date_from` y `date_to`. `search` busca en la nota. Trae `items_count` y no las líneas.'
        ),
        responses={401: UNAUTHORIZED, 403: FORBIDDEN},
    ),
    retrieve=extend_schema(
        tags=['Stock counts'],
        summary='Ver un recuento con sus líneas',
        description=(
            'Requiere `stock.view_stockcount`. `system_quantity` y `difference` se completan al confirmar (hasta '
            'entonces son `null`). Los ajustes generados se listan con `GET stock-movements/?stock_count={id}` o, agrupados, `GET stock-operations/?stock_count={id}`.'
        ),
        examples=[OpenApiExample('Recuento', value=_COUNT_EXAMPLE, response_only=True)],
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
    create=extend_schema(
        tags=['Stock counts'],
        summary='Crear un recuento en borrador',
        description=(
            'Requiere `stock.add_stockcount` (el mismo permiso sirve para armar, confirmar y cancelar). Puede '
            'traer las primeras líneas (`items`: `variant` y `counted_quantity`). El recuento es parcial: al '
            'confirmar sólo se ajustan las variantes cargadas.'
        ),
        request=StockCountCreateSerializer,
        examples=[OpenApiExample(
            'Solicitud', value={'note': 'Recuento de vidriera', 'items': [{'variant': 12, 'counted_quantity': 4}]},
            request_only=True,
        )],
        responses={201: StockCountSerializer, 400: VALIDATION_ERROR, 401: UNAUTHORIZED, 403: FORBIDDEN},
    ),
    partial_update=extend_schema(
        tags=['Stock counts'],
        summary='Editar la nota de un recuento',
        description='Requiere `stock.add_stockcount`. ' + _NOT_DRAFT,
        responses={200: StockCountSerializer, 400: VALIDATION_ERROR, 401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
    add_item=extend_schema(
        tags=['Stock counts'],
        summary='Agregar o corregir una línea',
        description=(
            'Requiere `stock.add_stockcount`. Si la variante ya está en el recuento se reemplaza la cantidad contada. '
            + _NOT_DRAFT
        ),
        examples=[OpenApiExample('Solicitud', value={'variant': 12, 'counted_quantity': 4}, request_only=True)],
        responses={201: StockCountSerializer, 400: VALIDATION_ERROR, 401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
    bulk_items=extend_schema(
        tags=['Stock counts'],
        summary='Agregar o corregir muchas líneas de una vez',
        description=(
            'Requiere `stock.add_stockcount`. Es atómico: agrega las variantes que no estaban y reemplaza la cantidad '
            'contada de las que sí; las que no se mencionan quedan como están. Una variante no puede repetirse. '
            + _NOT_DRAFT
        ),
        request=StockCountBulkItemsSerializer,
        examples=[OpenApiExample(
            'Solicitud',
            value={'items': [{'variant': 12, 'counted_quantity': 4}, {'variant': 13, 'counted_quantity': 0}]},
            request_only=True,
        )],
        responses={200: StockCountSerializer, 400: VALIDATION_ERROR, 401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
    remove_item=extend_schema(
        tags=['Stock counts'],
        summary='Quitar una línea',
        description='Requiere `stock.add_stockcount`. El segmento final es el id de la variante. ' + _NOT_DRAFT,
        request=None,
        responses={200: StockCountSerializer, 400: VALIDATION_ERROR, 401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
    confirm=extend_schema(
        tags=['Stock counts'],
        summary='Confirmar un recuento',
        description=(
            'Requiere `stock.add_stockcount`. Por cada línea lleva el stock a lo contado: guarda `system_quantity` '
            '(el saldo en ese momento) y `difference`, y crea un movimiento de ajuste (motivo `recuento`) si hubo '
            'diferencia. Es atómico y no hace falta una segunda aprobación. Falla si no tiene líneas. '
            + _NOT_DRAFT
        ),
        request=None,
        examples=[OpenApiExample('Recuento confirmado', value=_COUNT_EXAMPLE, response_only=True)],
        responses={200: StockCountSerializer, 400: VALIDATION_ERROR, 401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
    cancel=extend_schema(
        tags=['Stock counts'],
        summary='Cancelar un recuento',
        description='Requiere `stock.add_stockcount`. No toca el stock. ' + _NOT_DRAFT,
        request=None,
        responses={200: StockCountSerializer, 400: VALIDATION_ERROR, 401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
)
