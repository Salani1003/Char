"""
Documentación OpenAPI (drf-spectacular) de las views de `sales`.

Ver `core/schemas.py` para la convención general: la documentación vive acá, no en `views.py`.
"""
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema, extend_schema_view

from core.schemas import FORBIDDEN, NOT_FOUND, UNAUTHORIZED, VALIDATION_ERROR
from sales.serializers import (
    ExchangeCreateSerializer,
    ExchangeDetailSerializer,
    ExchangePreviewResultSerializer,
    ExchangePreviewSerializer,
    SaleCreateSerializer,
    SaleDetailSerializer,
    VoidSerializer,
)

__all__ = ['SALE_VIEWSET_SCHEMA', 'EXCHANGE_VIEWSET_SCHEMA']

_ITEM_EXAMPLE = {
    'id': 5, 'variant': 12, 'sku': 'CHAR-0012', 'product': 3, 'product_name': 'Vestido midi',
    'color_name': 'Azul', 'color_hex': '#14284B', 'size_name': 'M', 'quantity': 2,
    'list_price': '100.00', 'discount_percent': 10, 'unit_price': '90.00', 'subtotal': '180.00',
    'exchanged_quantity': 0, 'exchangeable_quantity': 2,
}
_SALE_EXAMPLE = {
    'id': 21, 'client': 4, 'client_name': 'Ana Paz', 'payment_method': 'tarjeta_debito',
    'payment_method_display': 'Tarjeta de débito', 'subtotal': '200.00', 'discount_percent': 10,
    'discount_reason': 'Cliente frecuente', 'total': '180.00', 'note': '', 'status': 'completada',
    'status_display': 'Completada', 'items_count': 1, 'units': 2, 'exchange_deadline': '2026-12-27',
    'created_at': '2026-11-27T15:00:00Z', 'created_by': 2, 'created_by_email': 'vendedor@demo.com',
    'voided_at': None, 'voided_by': None, 'voided_by_email': None, 'void_reason': '',
}
_DETAIL_EXAMPLE = {**_SALE_EXAMPLE, 'can_exchange': True, 'items': [_ITEM_EXAMPLE], 'exchanges': []}
_REQUEST_EXAMPLE = {
    'items': [{'variant': 12, 'quantity': 2}], 'payment_method': 'tarjeta_debito', 'client': 4,
    'discount_percent': 10, 'discount_reason': 'Cliente frecuente', 'idempotency_key': '0b9f6c1e-venta-21',
}

SALE_VIEWSET_SCHEMA = extend_schema_view(
    list=extend_schema(
        tags=['Sales'],
        summary='Listar ventas',
        description=(
            'Requiere `sales.view_sale`. Una fila por venta con sus totales (`items_count`, `units`); los ítems vienen '
            'en el detalle. Filtros: `client`, `status` (`completada`, `anulada`), `payment_method`, `created_by`, '
            '`product` / `variant` (ventas que los incluyen), `has_discount`, `has_exchanges` (con algún cambio activo), '
            '`min_total`, `max_total`, `date_from` y `date_to` (YYYY-MM-DD, inclusivos, hora de Buenos Aires). `search` '
            'busca en el cliente (nombre, apellido, email), la nota y el SKU de los ítems. `ordering`: `created_at`, '
            '`total`, `id` (prefijo `-` para descendente). Más nuevas primero. `exchange_deadline` es el último día para '
            'pedir un cambio.'
        ),
        examples=[OpenApiExample('Fila', value=_SALE_EXAMPLE, response_only=True)],
        responses={401: UNAUTHORIZED, 403: FORBIDDEN},
    ),
    retrieve=extend_schema(
        tags=['Sales'],
        summary='Ver una venta',
        description=(
            'Requiere `sales.view_sale`. Trae los ítems (con los precios congelados al vender y las unidades ya cambiadas), '
            'un resumen de sus cambios (`exchanges`) y `can_exchange` (completada, dentro del plazo y con unidades por '
            'cambiar). El stock de la venta se ve en `stock-operations/?sale={id}`.'
        ),
        examples=[OpenApiExample('Venta', value=_DETAIL_EXAMPLE, response_only=True)],
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
    create=extend_schema(
        tags=['Sales'],
        summary='Registrar una venta',
        description=(
            'Requiere `sales.add_sale`. Descuenta el stock en la misma transacción: si falta stock en cualquier ítem '
            'responde 400 (`detail`, `variant`, `available`, `requested`) y no se guarda nada. **El precio no se envía**: '
            'cada ítem congela el precio vigente del producto (promo si está en rango, si no el de venta). '
            '`discount_percent` admite 0, 5 o 10 y se aplica a todos los ítems; con 5 o 10 exige además '
            '`sales.apply_discount` (si no, 403). `client` es opcional. Con `idempotency_key`, reenviar la misma clave '
            '(ej. por un doble clic) devuelve la venta ya registrada con 200 en vez de duplicarla.'
        ),
        request=SaleCreateSerializer,
        examples=[OpenApiExample('Solicitud', value=_REQUEST_EXAMPLE, request_only=True)],
        responses={
            201: OpenApiResponse(SaleDetailSerializer, description='Venta registrada.'),
            200: OpenApiResponse(SaleDetailSerializer, description='La `idempotency_key` ya existía: es la venta original.'),
            400: VALIDATION_ERROR, 401: UNAUTHORIZED, 403: FORBIDDEN,
        },
    ),
    void=extend_schema(
        tags=['Sales'],
        summary='Anular una venta',
        description=(
            'Requiere `sales.void_sale`. Devuelve el stock (una sola operación de anulación, visible en '
            '`stock-operations/?sale={id}`) y deja la venta `anulada`. El motivo es obligatorio. Responde 400 si la '
            'venta ya está anulada o tiene cambios activos (primero se anulan los cambios).'
        ),
        request=VoidSerializer,
        examples=[OpenApiExample('Solicitud', value={'reason': 'Se cargó mal'}, request_only=True)],
        responses={
            200: OpenApiResponse(SaleDetailSerializer, description='Venta anulada.'),
            400: VALIDATION_ERROR, 401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND,
        },
    ),
)


_EXCHANGE_EXAMPLE = {
    'id': 8, 'sale': 21, 'client': 4, 'client_name': 'Ana Paz', 'status': 'completada', 'status_display': 'Completada',
    'returned_total': '90.00', 'new_total': '150.00', 'difference': '60.00', 'unreturned_amount': '0.00',
    'payment_method': 'qr', 'payment_method_display': 'QR', 'note': 'Le quedaba chico',
    'created_at': '2026-11-28T15:00:00Z', 'created_by': 2, 'created_by_email': 'vendedor@demo.com',
    'voided_at': None, 'voided_by': None, 'voided_by_email': None, 'void_reason': '',
}
_EXCHANGE_DETAIL_EXAMPLE = {**_EXCHANGE_EXAMPLE, 'items': [
    {'id': 1, 'direction': 'in', 'direction_display': 'Devuelve', 'variant': 12, 'sku': 'CHAR-0012', 'product': 3,
     'product_name': 'Vestido midi', 'color_name': 'Azul', 'color_hex': '#14284B', 'size_name': 'M', 'quantity': 1,
     'unit_price': '90.00', 'subtotal': '90.00', 'sale_item': 5},
    {'id': 2, 'direction': 'out', 'direction_display': 'Se lleva', 'variant': 15, 'sku': 'CHAR-0015', 'product': 4,
     'product_name': 'Abrigo', 'color_name': 'Negro', 'color_hex': '#000000', 'size_name': 'M', 'quantity': 1,
     'unit_price': '150.00', 'subtotal': '150.00', 'sale_item': None},
]}
_EXCHANGE_REQUEST = {
    'sale': 21, 'returned_items': [{'sale_item': 5, 'quantity': 1}], 'new_items': [{'variant': 15, 'quantity': 1}],
    'payment_method': 'qr', 'note': 'Le quedaba chico',
}

EXCHANGE_VIEWSET_SCHEMA = extend_schema_view(
    list=extend_schema(
        tags=['Exchanges'],
        summary='Listar cambios',
        description=(
            'Requiere `sales.view_exchange`. Filtros: `sale`, `client` (el de la venta), `status` (`completada`, '
            '`anulada`), `payment_method`, `created_by`, `date_from` y `date_to` (YYYY-MM-DD, inclusivos, hora de '
            'Buenos Aires). `search` busca en el cliente, la nota y el SKU de las líneas. `ordering`: `created_at`, '
            '`difference`, `id`. Más nuevos primero. Las líneas vienen en el detalle.'
        ),
        examples=[OpenApiExample('Fila', value=_EXCHANGE_EXAMPLE, response_only=True)],
        responses={401: UNAUTHORIZED, 403: FORBIDDEN},
    ),
    retrieve=extend_schema(
        tags=['Exchanges'],
        summary='Ver un cambio',
        description=(
            'Requiere `sales.view_exchange`. `items` trae lo que vuelve (`direction: in`, valuado a lo que el cliente pagó '
            'en la venta) y lo que se lleva (`direction: out`, a precio vigente sin descuento).'
        ),
        examples=[OpenApiExample('Cambio', value=_EXCHANGE_DETAIL_EXAMPLE, response_only=True)],
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
    create=extend_schema(
        tags=['Exchanges'],
        summary='Registrar un cambio',
        description=(
            'Requiere `sales.add_exchange`. Sobre una venta completada y dentro del plazo (`EXCHANGE_WINDOW_DAYS`, 30 '
            'días): `returned_items` son ítems de ESA venta (`sale_item`, hasta lo que aún no se cambió) y `new_items` '
            'las variantes que se lleva (puede ir vacío). Atómico: ingresa lo devuelto (`cambio_entrada`) y egresa lo nuevo '
            '(`cambio_salida`); si falta stock de lo nuevo responde 400 y no queda nada. **No hay devoluciones de '
            'dinero**: con `difference` > 0 el cliente paga y `payment_method` es obligatorio; con 0 o negativa no hay pago '
            '(un `payment_method` enviado se ignora) y lo no compensado queda en `unreturned_amount`. Para mostrar los '
            'números antes de confirmar usar `exchanges/preview/`.'
        ),
        request=ExchangeCreateSerializer,
        examples=[OpenApiExample('Solicitud', value=_EXCHANGE_REQUEST, request_only=True)],
        responses={
            201: OpenApiResponse(ExchangeDetailSerializer, description='Cambio registrado.'),
            400: VALIDATION_ERROR, 401: UNAUTHORIZED, 403: FORBIDDEN,
        },
    ),
    preview=extend_schema(
        tags=['Exchanges'],
        summary='Calcular un cambio sin registrarlo',
        description=(
            'Requiere `sales.add_exchange`. Recibe lo mismo que el alta (sin `payment_method` ni `note`) y devuelve '
            '`returned_total`, `new_total`, `difference` y `unreturned_amount`. No guarda nada ni mueve stock. Aplica las '
            'mismas validaciones (plazo, cantidades) y avisa con 400 si no hay stock de lo que se lleva. `difference` > 0 '
            'es lo que paga el cliente; `unreturned_amount` > 0 es valor que no se reintegra.'
        ),
        request=ExchangePreviewSerializer,
        examples=[OpenApiExample('Solicitud', value={k: v for k, v in _EXCHANGE_REQUEST.items() if k in ('sale', 'returned_items', 'new_items')}, request_only=True)],
        responses={
            200: OpenApiResponse(ExchangePreviewResultSerializer, description='Totales del cambio.'),
            400: VALIDATION_ERROR, 401: UNAUTHORIZED, 403: FORBIDDEN,
        },
    ),
    void=extend_schema(
        tags=['Exchanges'],
        summary='Anular un cambio',
        description=(
            'Requiere `sales.void_exchange`. Deshace las dos operaciones de stock y libera las unidades para cambiarlas '
            'de nuevo. El motivo es obligatorio. Responde 400 si ya está anulado o si las unidades que habían entrado '
            'ya se vendieron (no alcanza el stock para deshacerlo).'
        ),
        request=VoidSerializer,
        examples=[OpenApiExample('Solicitud', value={'reason': 'Se arrepintió'}, request_only=True)],
        responses={
            200: OpenApiResponse(ExchangeDetailSerializer, description='Cambio anulado.'),
            400: VALIDATION_ERROR, 401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND,
        },
    ),
)
