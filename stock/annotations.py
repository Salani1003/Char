from django.db.models import BooleanField, ExpressionWrapper, F, IntegerField, Q, Value
from django.db.models.functions import Coalesce


def with_stock(queryset):
    """Anota `quantity` (0 sin movimientos) e `is_low_stock` sobre un queryset de variantes, sin consultas por fila."""
    return queryset.annotate(
        quantity=Coalesce('stock_level__quantity', Value(0), output_field=IntegerField()),
    ).annotate(
        is_low_stock=ExpressionWrapper(
            Q(min_stock__gt=0, quantity__lte=F('min_stock')), output_field=BooleanField()
        ),
    )
