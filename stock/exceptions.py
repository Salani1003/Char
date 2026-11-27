from rest_framework.exceptions import ValidationError

__all__ = ['StockError', 'InsufficientStock']


class StockError(ValidationError):
    """Movimiento de stock inválido (400)."""


class InsufficientStock(StockError):
    """Un egreso dejaría el saldo en negativo (400). Informa lo disponible."""

    def __init__(self, variant, available, requested):
        self.available = available
        self.requested = requested
        super().__init__({
            'detail': f'Stock insuficiente para {variant.sku}: disponible {available}, solicitado {requested}.',
            'variant': variant.pk,
            'available': available,
            'requested': requested,
        })
