from rest_framework.exceptions import ValidationError

__all__ = ['SaleError']


class SaleError(ValidationError):
    """Venta, cambio o anulación inválidos (400)."""
