from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from products.models import ProductVariant
from sales.exceptions import SaleError
from sales.models import Exchange, ExchangeItem, PaymentMethod, Sale, SaleItem
from stock.exceptions import InsufficientStock
from stock.models import StockLevel, StockMovement
from stock.services import apply_movements, reverse_operation

__all__ = [
    'create_sale', 'void_sale', 'discounted_price', 'exchange_deadline',
    'create_exchange', 'preview_exchange', 'void_exchange',
]

CENT = Decimal('0.01')


def discounted_price(list_price, percent):
    """Precio unitario con `percent`% de descuento, redondeado al centavo (mitad hacia arriba)."""
    return (list_price * (100 - percent) / 100).quantize(CENT, rounding=ROUND_HALF_UP)


def exchange_deadline(sale):
    """Último día (hora local, inclusive) para pedir un cambio de la venta: `EXCHANGE_WINDOW_DAYS` desde que se hizo."""
    return timezone.localtime(sale.created_at).date() + timedelta(days=settings.EXCHANGE_WINDOW_DAYS)


def _load_variants(lines, field='items', allow_empty=False):
    """
    Valida las líneas `(variante, cantidad)` y devuelve `[(variante_fresca, cantidad)]`. Se vuelve a leer cada
    variante (con su producto) para vender al precio vigente de la base y no al de un objeto viejo. Los errores
    se informan bajo la clave `field`.
    """
    if not lines and not allow_empty:
        raise SaleError({field: 'Falta al menos un ítem.'})
    ids = [variant.pk for variant, _ in lines]
    if len(ids) != len(set(ids)):
        raise SaleError({field: 'Una variante no puede repetirse.'})
    if any(quantity <= 0 for _, quantity in lines):
        raise SaleError({field: 'Las cantidades deben ser mayores a 0.'})
    fresh = ProductVariant.objects.select_related('product').in_bulk(ids)  # `objects` excluye las eliminadas
    missing = [pk for pk in ids if pk not in fresh or fresh[pk].product.is_deleted]
    if missing:
        raise SaleError({field: f'Variantes inexistentes o eliminadas: {sorted(missing)}.'})
    return [(fresh[variant.pk], quantity) for variant, quantity in lines]


def _validate_sale(user, lines, payment_method, client, discount_percent):
    if payment_method not in PaymentMethod.values:
        raise SaleError({'payment_method': 'Medio de pago inválido.'})
    if discount_percent not in settings.SALE_DISCOUNT_CHOICES:
        options = ', '.join(str(p) for p in settings.SALE_DISCOUNT_CHOICES)
        raise SaleError({'discount_percent': f'El descuento debe ser uno de: {options}.'})
    if discount_percent and not (user and user.has_perm('sales.apply_discount')):
        raise PermissionDenied('No tenés permiso para aplicar descuentos.')
    if client is not None and client.is_deleted:
        raise SaleError({'client': 'El cliente fue eliminado.'})
    return _load_variants(lines)


def create_sale(
    user, lines, payment_method, client=None, discount_percent=0, discount_reason='', note='', idempotency_key=None,
):
    """
    Registra una venta y descuenta el stock en una sola transacción. `lines` es una lista de
    `(variante, cantidad)`; el precio NO se recibe: cada ítem congela el precio vigente del producto
    (promo o venta, `Product.get_current_price()`) y, si hay descuento (`SALE_DISCOUNT_CHOICES`; requiere
    `sales.apply_discount`), el precio final con descuento. Sin stock suficiente lanza `InsufficientStock`
    y no queda nada guardado.

    Con `idempotency_key`, reintentar la misma venta no la duplica: devuelve la ya registrada.
    Devuelve `(venta, creada)`.
    """
    if idempotency_key:
        existing = Sale.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing, False
    loaded = _validate_sale(user, lines, payment_method, client, discount_percent)

    try:
        with transaction.atomic():
            sale = Sale.objects.create(
                client=client, payment_method=payment_method, discount_percent=discount_percent,
                discount_reason=discount_reason, note=note, idempotency_key=idempotency_key or None,
                subtotal=Decimal('0'), total=Decimal('0'), created_by=user,
            )
            items, subtotal, total = [], Decimal('0'), Decimal('0')
            for variant, quantity in loaded:
                list_price = variant.product.get_current_price()
                unit_price = discounted_price(list_price, discount_percent)
                items.append(SaleItem(
                    sale=sale, variant=variant, quantity=quantity, list_price=list_price,
                    discount_percent=discount_percent, unit_price=unit_price, subtotal=unit_price * quantity,
                ))
                subtotal += list_price * quantity
                total += unit_price * quantity
            # Primero el stock: si falta, se revierte la venta entera.
            apply_movements(
                [(variant, quantity) for variant, quantity in loaded], StockMovement.EGRESO, StockMovement.VENTA,
                user=user, note=f'Venta #{sale.pk}', sale=sale,
            )
            SaleItem.objects.bulk_create(items)
            sale.subtotal, sale.total = subtotal, total
            sale.save(update_fields=['subtotal', 'total'])
            return sale, True
    except IntegrityError:
        # Dos pedidos simultáneos con la misma clave: gana uno y el otro devuelve esa venta.
        existing = Sale.objects.filter(idempotency_key=idempotency_key).first() if idempotency_key else None
        if existing is None:
            raise
        return existing, False


def void_sale(sale, user=None, reason=''):
    """
    Anula una venta: devuelve el stock (`reverse_operation`, una sola operación de anulación) y la marca
    `anulada`. Exige un motivo. No se anula una venta ya anulada ni una con cambios activos (primero se
    anulan los cambios). Bloquea la venta, así una anulación no corre a la vez con un cambio ni con otra
    anulación. Devuelve la venta.
    """
    reason = (reason or '').strip()
    if not reason:
        raise SaleError({'reason': 'Indicá el motivo de la anulación.'})
    with transaction.atomic():
        sale = Sale.objects.select_for_update().get(pk=sale.pk)
        if sale.status == Sale.Status.ANULADA:
            raise SaleError({'detail': 'La venta ya está anulada.'})
        if sale.exchanges.filter(status=Sale.Status.COMPLETADA).exists():
            raise SaleError({'detail': 'La venta tiene cambios: anulá primero los cambios.'})
        operation = sale.stock_operations.get(reason=StockMovement.VENTA)
        reverse_operation(operation, user=user, note=f'Anulación de venta #{sale.pk}')
        sale.status = Sale.Status.ANULADA
        sale.voided_at = timezone.now()
        sale.voided_by = user
        sale.void_reason = reason
        sale.save(update_fields=['status', 'voided_at', 'voided_by', 'void_reason'])
        return sale


# --- Cambios ---------------------------------------------------------------------------------------------


def _check_open_for_exchange(sale):
    """La venta debe estar completada y dentro del plazo de cambio."""
    if sale.status != Sale.Status.COMPLETADA:
        raise SaleError({'detail': 'La venta está anulada: no se puede cambiar.'})
    deadline = exchange_deadline(sale)
    if timezone.localdate() > deadline:
        raise SaleError({'detail': f'Pasó el plazo de cambio ({settings.EXCHANGE_WINDOW_DAYS} días): venció el {deadline:%d/%m/%Y}.'})


def _load_returned(sale, returned, lock):
    """
    Valida las líneas devueltas `(ítem de la venta, cantidad)` y devuelve `[(ítem_fresco, cantidad)]`. Con `lock`
    bloquea los ítems (`select_for_update`): dos cambios simultáneos no pueden devolver la misma unidad.
    """
    if not returned:
        raise SaleError({'returned_items': 'Falta al menos un ítem a devolver.'})
    ids = [item.pk for item, _ in returned]
    if len(ids) != len(set(ids)):
        raise SaleError({'returned_items': 'Un ítem no puede repetirse.'})
    if any(quantity <= 0 for _, quantity in returned):
        raise SaleError({'returned_items': 'Las cantidades deben ser mayores a 0.'})
    queryset = SaleItem.objects.filter(sale=sale, pk__in=ids).order_by('pk')
    fresh = {item.pk: item for item in (queryset.select_for_update() if lock else queryset)}
    if set(ids) - set(fresh):
        raise SaleError({'returned_items': 'Hay ítems que no pertenecen a la venta.'})
    for given, quantity in returned:
        item = fresh[given.pk]
        available = item.quantity - item.exchanged_quantity
        if quantity > available:
            raise SaleError({'returned_items': f'Se pueden cambiar como máximo {available} unidad(es) del ítem {item.pk}; pediste {quantity}.'})
    return [(fresh[item.pk], quantity) for item, quantity in returned]


def _price_exchange(sale, returned, new_lines, lock=False):
    """
    Valida y valúa un cambio. Lo devuelto vale lo que el cliente pagó (`unit_price` congelado, con el descuento
    de la venta); lo nuevo, el precio vigente hoy, sin descuento. Devuelve un dict con las líneas ya cargadas y
    los totales (`difference` = nuevo − devuelto).
    """
    _check_open_for_exchange(sale)
    returned_items = _load_returned(sale, returned, lock)
    new_items = _load_variants(new_lines, field='new_items', allow_empty=True)
    if {item.variant_id for item, _ in returned_items} & {variant.pk for variant, _ in new_items}:
        raise SaleError({'new_items': 'No se puede cambiar una variante por sí misma.'})
    returned_total = sum((item.unit_price * quantity for item, quantity in returned_items), Decimal('0'))
    prices = {variant.pk: variant.product.get_current_price() for variant, _ in new_items}
    new_total = sum((prices[variant.pk] * quantity for variant, quantity in new_items), Decimal('0'))
    difference = new_total - returned_total
    return {
        'returned': returned_items, 'new': new_items, 'prices': prices,
        'returned_total': returned_total, 'new_total': new_total, 'difference': difference,
        'unreturned_amount': max(-difference, Decimal('0')),
    }


def preview_exchange(sale, returned, new_lines):
    """
    Cuenta un cambio sin registrarlo: no guarda nada ni mueve stock. Aplica las mismas validaciones que
    `create_exchange` (plazo, cantidades) y además avisa si no hay stock de lo que se lleva (`InsufficientStock`;
    es una lectura sin bloqueo, la confirmación definitiva la hace `create_exchange`). Devuelve
    `returned_total`, `new_total`, `difference` y `unreturned_amount`.
    """
    priced = _price_exchange(sale, returned, new_lines)
    for variant, quantity in priced['new']:
        level = StockLevel.objects.filter(variant_id=variant.pk).first()
        available = level.quantity if level else 0
        if quantity > available:
            raise InsufficientStock(variant, available=available, requested=quantity)
    return {key: priced[key] for key in ('returned_total', 'new_total', 'difference', 'unreturned_amount')}


def create_exchange(user, sale, returned, new_lines, payment_method='', note=''):
    """
    Registra un cambio sobre `sale`: `returned` es una lista de `(ítem de la venta, cantidad)` (lo que vuelve) y
    `new_lines` una de `(variante, cantidad)` (lo que se lleva; puede estar vacía). Atómico: ingresa lo devuelto
    (`cambio_entrada`) y egresa lo nuevo (`cambio_salida`) en dos operaciones enlazadas al cambio; si falta stock
    de lo nuevo no queda nada.

    No hay devoluciones de dinero: con diferencia positiva el cliente paga y `payment_method` es obligatorio;
    con diferencia cero o negativa no hay pago (un `payment_method` enviado se ignora) y lo no compensado queda
    en `unreturned_amount`. Plazo: `EXCHANGE_WINDOW_DAYS` desde la venta. Se bloquea la venta (igual que
    `void_sale`) y los ítems devueltos. Devuelve el cambio.
    """
    with transaction.atomic():
        sale = Sale.objects.select_for_update().get(pk=sale.pk)
        priced = _price_exchange(sale, returned, new_lines, lock=True)
        difference = priced['difference']
        if difference > 0:
            if payment_method not in PaymentMethod.values:
                raise SaleError({'payment_method': 'El cambio tiene diferencia a pagar: indicá el medio de pago.'})
        else:
            payment_method = ''
        exchange = Exchange.objects.create(
            sale=sale, payment_method=payment_method, returned_total=priced['returned_total'],
            new_total=priced['new_total'], difference=difference, note=note, created_by=user,
        )
        label = f'Cambio #{exchange.pk} (venta #{sale.pk})'
        apply_movements(
            [(item.variant, quantity) for item, quantity in priced['returned']],
            StockMovement.INGRESO, StockMovement.CAMBIO_ENTRADA, user=user, note=label, exchange=exchange,
        )
        if priced['new']:
            apply_movements(
                priced['new'], StockMovement.EGRESO, StockMovement.CAMBIO_SALIDA, user=user, note=label, exchange=exchange,
            )
        ExchangeItem.objects.bulk_create(
            [ExchangeItem(
                exchange=exchange, direction=ExchangeItem.IN, variant_id=item.variant_id, quantity=quantity,
                unit_price=item.unit_price, sale_item=item,
            ) for item, quantity in priced['returned']]
            + [ExchangeItem(
                exchange=exchange, direction=ExchangeItem.OUT, variant_id=variant.pk, quantity=quantity,
                unit_price=priced['prices'][variant.pk],
            ) for variant, quantity in priced['new']]
        )
        for item, quantity in priced['returned']:
            SaleItem.objects.filter(pk=item.pk).update(exchanged_quantity=F('exchanged_quantity') + quantity)
        return exchange


def void_exchange(exchange, user=None, reason=''):
    """
    Anula un cambio: deshace sus dos operaciones de stock (vuelve a entrar lo que se llevó y sale lo que se había
    devuelto), libera las unidades para poder cambiarlas de nuevo y lo marca `anulado`. Exige un motivo. Falla
    (400, `InsufficientStock`) si las unidades que habían entrado ya se vendieron. Bloquea primero la venta,
    como `void_sale` y `create_exchange`. Devuelve el cambio.
    """
    reason = (reason or '').strip()
    if not reason:
        raise SaleError({'reason': 'Indicá el motivo de la anulación.'})
    with transaction.atomic():
        Sale.objects.select_for_update().get(pk=exchange.sale_id)
        exchange = Exchange.objects.select_for_update().get(pk=exchange.pk)
        if exchange.status == Exchange.Status.ANULADA:
            raise SaleError({'detail': 'El cambio ya está anulado.'})
        note = f'Anulación de cambio #{exchange.pk}'
        # Primero lo que salió (vuelve a entrar, no puede fallar) y después lo que había entrado.
        for reason_code in (StockMovement.CAMBIO_SALIDA, StockMovement.CAMBIO_ENTRADA):
            for operation in exchange.stock_operations.filter(reason=reason_code):
                reverse_operation(operation, user=user, note=note)
        for item in exchange.items.filter(direction=ExchangeItem.IN):
            SaleItem.objects.filter(pk=item.sale_item_id).update(exchanged_quantity=F('exchanged_quantity') - item.quantity)
        exchange.status = Exchange.Status.ANULADA
        exchange.voided_at = timezone.now()
        exchange.voided_by = user
        exchange.void_reason = reason
        exchange.save(update_fields=['status', 'voided_at', 'voided_by', 'void_reason'])
        return exchange
