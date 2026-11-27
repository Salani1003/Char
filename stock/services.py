from django.db import transaction
from django.utils import timezone

from products.models import ProductVariant
from stock.exceptions import InsufficientStock, StockError
from stock.models import StockCount, StockLevel, StockMovement, StockOperation

__all__ = [
    'apply_movement', 'apply_movements', 'reverse_movement',
    'adjust_to_count', 'confirm_count', 'cancel_count',
]


def _lock_level(variant):
    """
    Devuelve el `StockLevel` de la variante bloqueado (`select_for_update`; se crea
    con el primer movimiento). Con el saldo bloqueado verifica que la variante siga
    activa: no se mueve stock de una variante eliminada. Debe llamarse dentro de una
    transacción.
    """
    # get_or_create tolera la carrera del primer movimiento de una variante.
    level, _ = StockLevel.objects.get_or_create(variant_id=variant.pk)
    level = StockLevel.objects.select_for_update().get(pk=level.pk)
    if not ProductVariant.objects.filter(pk=variant.pk).exists():
        raise StockError({'variant': 'La variante no existe o fue eliminada.'})
    return level


def _new_operation(kind, reason, user, note='', stock_count=None):
    return StockOperation.objects.create(kind=kind, reason=reason, note=note, stock_count=stock_count, created_by=user)


def _write_movement(level, variant, operation, delta, user, reverses):
    """
    Aplica `delta` al saldo ya bloqueado y crea el movimiento (una línea de `operation`, de la que
    toma tipo, motivo y nota). Nunca deja el saldo negativo.
    """
    before = level.quantity
    after = before + delta
    if after < 0:
        raise InsufficientStock(variant, available=before, requested=-delta)
    level.quantity = after
    level.save(update_fields=['quantity', 'updated_at'])
    return StockMovement.objects.create(
        operation=operation, variant_id=variant.pk, kind=operation.kind, quantity=delta,
        stock_before=before, stock_after=after, reason=operation.reason, note=operation.note,
        reverses=reverses, created_by=user,
    )


def apply_movement(variant, kind, delta, reason, user=None, note='', operation=None, reverses=None):
    """
    Punto de entrada para cambiar el stock: actualiza el saldo y crea el
    `StockMovement` que lo explica (como una línea de `operation`; si no se pasa una, crea una
    operación de una sola línea), en la misma transacción y con el saldo
    bloqueado (`select_for_update`). Si ya hay una transacción abierta (lote,
    recuento, cambio) se une a ella: si algo falla después, todo se revierte.

    `delta` lleva signo: positivo en un ingreso, negativo en un egreso, cualquiera
    (distinto de 0) en un ajuste. Nunca deja el saldo negativo (`InsufficientStock`).
    Devuelve el movimiento creado.
    """
    if kind not in StockMovement.REASONS_BY_KIND:
        raise StockError({'kind': f'Tipo de movimiento inválido: {kind}.'})
    if reason not in StockMovement.REASONS_BY_KIND[kind]:
        raise StockError({'reason': f'El motivo "{reason}" no corresponde a un {kind}.'})
    if not delta:
        raise StockError({'quantity': 'La cantidad no puede ser 0.'})
    if (kind == StockMovement.INGRESO and delta < 0) or (kind == StockMovement.EGRESO and delta > 0):
        raise StockError({'quantity': f'El signo de la cantidad no corresponde a un {kind}.'})

    with transaction.atomic():
        level = _lock_level(variant)
        operation = operation or _new_operation(kind, reason, user, note)
        return _write_movement(level, variant, operation, delta, user, reverses)


def apply_movements(lines, kind, reason, user=None, note=''):
    """
    Ingreso o egreso en lote, atómico: si una línea falla no se aplica ninguna.
    `lines` es una lista de `(variant, quantity)` con cantidad POSITIVA (el signo lo
    pone el tipo). Devuelve la `StockOperation` creada, con una línea por variante. Una variante no puede repetirse. Se procesa por id de variante para
    que dos lotes concurrentes bloqueen en el mismo orden (sin deadlocks).
    """
    if kind not in (StockMovement.INGRESO, StockMovement.EGRESO):
        raise StockError({'kind': 'Un lote sólo admite ingresos o egresos.'})
    if not lines:
        raise StockError({'items': 'Falta al menos una línea.'})
    ids = [variant.pk for variant, _ in lines]
    if len(ids) != len(set(ids)):
        raise StockError({'items': 'Una variante no puede repetirse en el mismo movimiento.'})
    for _, quantity in lines:
        if quantity <= 0:
            raise StockError({'items': 'Las cantidades deben ser mayores a 0.'})

    if reason not in StockMovement.REASONS_BY_KIND[kind]:
        raise StockError({'reason': f'El motivo "{reason}" no corresponde a un {kind}.'})

    sign = 1 if kind == StockMovement.INGRESO else -1
    with transaction.atomic():
        operation = _new_operation(kind, reason, user, note)
        for variant, quantity in sorted(lines, key=lambda line: line[0].pk):
            apply_movement(variant, kind, sign * quantity, reason, user=user, note=note, operation=operation)
        return operation


def reverse_movement(movement, user=None, note=''):
    """
    Anula un ingreso o egreso creando el movimiento inverso, enlazado con
    `reverses`. Un movimiento se anula una sola vez; no se anulan las anulaciones
    ni los ajustes (los de recuento se corrigen con otro recuento). Si el saldo ya
    no alcanza para deshacerlo (ej. anular un ingreso cuyas unidades ya salieron)
    lanza `InsufficientStock`. Devuelve el movimiento de anulación (en su propia operación).
    """
    with transaction.atomic():
        # Se bloquea el original: dos anulaciones simultáneas se serializan.
        movement = StockMovement.objects.select_for_update().select_related('variant').get(pk=movement.pk)
        if movement.kind == StockMovement.AJUSTE:
            raise StockError({'detail': 'Los ajustes no se anulan: corregilos con otro recuento.'})
        if movement.reason == StockMovement.ANULACION:
            raise StockError({'detail': 'Una anulación no se puede anular.'})
        if StockMovement.objects.filter(reverses=movement).exists():
            raise StockError({'detail': 'El movimiento ya fue anulado.'})
        kind = StockMovement.EGRESO if movement.kind == StockMovement.INGRESO else StockMovement.INGRESO
        return apply_movement(
            movement.variant, kind, -movement.quantity, StockMovement.ANULACION,
            user=user, note=note, reverses=movement,
        )


def adjust_to_count(variant, counted, operation, user=None):
    """
    Lleva el saldo a `counted`. La diferencia se calcula con el saldo bloqueado
    (no con una lectura previa), así un movimiento concurrente no se pisa. Devuelve
    `(saldo_en_sistema, movimiento)`; el movimiento (una línea de `operation`) es `None` si
    no había diferencia.
    """
    with transaction.atomic():
        level = _lock_level(variant)
        system = level.quantity
        delta = counted - system
        if delta == 0:
            return system, None
        movement = _write_movement(level, variant, operation, delta, user, None)
        return system, movement


def _lock_draft(count):
    count = StockCount.objects.select_for_update().get(pk=count.pk)
    if count.status != StockCount.BORRADOR:
        raise StockError({'detail': f'El recuento está {count.get_status_display().lower()} y no se puede modificar.'})
    return count


def confirm_count(count, user=None):
    """
    Confirma un recuento en borrador: por cada línea ajusta el stock a lo contado,
    guarda `system_quantity` y `difference` y crea un movimiento de ajuste si hubo
    diferencia. Atómico: si algo falla (ej. una variante eliminada) no cambia nada.
    Sólo se ajustan las variantes cargadas (recuento parcial).
    """
    with transaction.atomic():
        count = _lock_draft(count)
        items = list(count.items.select_related('variant').order_by('variant_id'))
        if not items:
            raise StockError({'items': 'El recuento no tiene líneas.'})
        # Una operación por recuento, aunque no haya diferencias (queda constancia de que se contó).
        operation = _new_operation(
            StockMovement.AJUSTE, StockMovement.RECUENTO, user, note=f'Recuento #{count.pk}', stock_count=count
        )
        for item in items:
            system, _ = adjust_to_count(item.variant, item.counted_quantity, operation, user=user)
            item.system_quantity = system
            item.difference = item.counted_quantity - system
            item.save(update_fields=['system_quantity', 'difference'])
        count.status = StockCount.CONFIRMADO
        count.confirmed_at = timezone.now()
        count.confirmed_by = user
        count.updated_by = user
        count.save(update_fields=['status', 'confirmed_at', 'confirmed_by', 'updated_by', 'updated_at'])
        return count


def cancel_count(count, user=None):
    """Cancela un recuento en borrador (no toca el stock)."""
    with transaction.atomic():
        count = _lock_draft(count)
        count.status = StockCount.CANCELADO
        count.updated_by = user
        count.save(update_fields=['status', 'updated_by', 'updated_at'])
        return count
