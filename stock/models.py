from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q

from core.models import BaseModel, unique_when_active


class StockLevel(models.Model):
    """
    Saldo actual de una variante (un único local). Se crea con el primer
    movimiento y sólo se modifica desde `stock.services` junto con el
    `StockMovement` que lo explica, bajo `select_for_update`. Nunca es negativo.
    """

    variant = models.OneToOneField(
        'products.ProductVariant', on_delete=models.PROTECT, related_name='stock_level', verbose_name='variante',
    )
    quantity = models.PositiveIntegerField('cantidad', default=0)
    updated_at = models.DateTimeField('actualizado', auto_now=True)

    class Meta:
        verbose_name = 'saldo de stock'
        verbose_name_plural = 'saldos de stock'
        ordering = ['variant_id']
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gte=0), name='stocklevel_quantity_gte_0'),
        ]

    def __str__(self):
        return f'{self.variant}: {self.quantity}'


class StockOperation(models.Model):
    """
    Operación de stock: el "documento" que agrupa uno o más movimientos hechos juntos. Un
    ingreso o egreso en lote, la confirmación de un recuento o una anulación son una operación
    cada uno; el historial lista operaciones y cada una se abre para ver sus líneas
    (`movements`). Todas sus líneas comparten tipo, motivo, nota, usuario y fecha. Es inmutable
    como los movimientos. Un recuento sin diferencias genera una operación sin líneas (queda
    constancia de que se contó).
    """

    kind = models.CharField('tipo', max_length=10, choices=[('ingreso', 'Ingreso'), ('egreso', 'Egreso'), ('ajuste', 'Ajuste')])
    reason = models.CharField('motivo', max_length=30)
    note = models.CharField('nota', max_length=500, blank=True)
    stock_count = models.OneToOneField(
        'stock.StockCount', null=True, blank=True, on_delete=models.PROTECT,
        related_name='operation', verbose_name='recuento',
    )
    # Documento de ventas que la originó (la venta, el cambio o sus anulaciones). Se anula desde ahí.
    sale = models.ForeignKey(
        'sales.Sale', null=True, blank=True, on_delete=models.PROTECT,
        related_name='stock_operations', verbose_name='venta',
    )
    exchange = models.ForeignKey(
        'sales.Exchange', null=True, blank=True, on_delete=models.PROTECT,
        related_name='stock_operations', verbose_name='cambio',
    )
    created_at = models.DateTimeField('fecha', auto_now_add=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='usuario',
    )

    class Meta:
        verbose_name = 'operación de stock'
        verbose_name_plural = 'operaciones de stock'
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.get_kind_display()} #{self.pk}'


class StockMovement(models.Model):
    """
    Movimiento de stock (una línea de una `StockOperation`). Es la fuente de verdad: inmutable (no se edita ni se
    borra; un error se corrige con otro movimiento, ver `reverses`). No es
    `BaseModel`: no tiene soft delete.
    """

    INGRESO = 'ingreso'
    EGRESO = 'egreso'
    AJUSTE = 'ajuste'
    KIND_CHOICES = [(INGRESO, 'Ingreso'), (EGRESO, 'Egreso'), (AJUSTE, 'Ajuste')]

    # Motivos de ingreso
    COMPRA = 'compra'
    CAMBIO_ENTRADA = 'cambio_entrada'
    STOCK_INICIAL = 'stock_inicial'
    # Motivos de egreso
    ROTURA_MERMA = 'rotura_merma'
    PERDIDA = 'perdida'
    USO_INTERNO = 'uso_interno'
    DEVOLUCION_PROVEEDOR = 'devolucion_proveedor'
    CAMBIO_SALIDA = 'cambio_salida'
    VENTA = 'venta'  # lo genera el módulo de ventas
    # Motivos de ajuste
    RECUENTO = 'recuento'
    CORRECCION = 'correccion'
    # Ingreso o egreso
    OTRO = 'otro'
    # Anulación de otro movimiento (lo genera el sistema)
    ANULACION = 'anulacion'

    REASON_CHOICES = [
        (COMPRA, 'Compra'),
        (CAMBIO_ENTRADA, 'Cambio (entra prenda devuelta)'),
        (STOCK_INICIAL, 'Stock inicial'),
        (ROTURA_MERMA, 'Rotura / merma'),
        (PERDIDA, 'Pérdida'),
        (USO_INTERNO, 'Uso interno'),
        (DEVOLUCION_PROVEEDOR, 'Devolución a proveedor'),
        (CAMBIO_SALIDA, 'Cambio (sale prenda nueva)'),
        (VENTA, 'Venta'),
        (RECUENTO, 'Recuento'),
        (CORRECCION, 'Corrección'),
        (OTRO, 'Otro'),
        (ANULACION, 'Anulación'),
    ]
    # Motivos válidos por tipo (los valida el servicio/serializer).
    REASONS_BY_KIND = {
        INGRESO: {COMPRA, CAMBIO_ENTRADA, STOCK_INICIAL, OTRO, ANULACION},
        EGRESO: {ROTURA_MERMA, PERDIDA, USO_INTERNO, DEVOLUCION_PROVEEDOR, CAMBIO_SALIDA, VENTA, OTRO, ANULACION},
        AJUSTE: {RECUENTO, CORRECCION},
    }

    operation = models.ForeignKey(
        StockOperation, on_delete=models.PROTECT, related_name='movements', verbose_name='operación',
    )
    variant = models.ForeignKey(
        'products.ProductVariant', on_delete=models.PROTECT, related_name='stock_movements', verbose_name='variante',
    )
    kind = models.CharField('tipo', max_length=10, choices=KIND_CHOICES)
    quantity = models.IntegerField('cantidad', help_text='Variación con signo: positiva suma, negativa resta.')
    stock_before = models.PositiveIntegerField('stock antes')
    stock_after = models.PositiveIntegerField('stock después')
    reason = models.CharField('motivo', max_length=30, choices=REASON_CHOICES)
    note = models.CharField('nota', max_length=500, blank=True)
    reverses = models.OneToOneField(
        'self', null=True, blank=True, on_delete=models.PROTECT,
        related_name='reversed_by', verbose_name='anula a',
    )
    created_at = models.DateTimeField('fecha', auto_now_add=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='usuario',
    )

    class Meta:
        verbose_name = 'movimiento de stock'
        verbose_name_plural = 'movimientos de stock'
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['variant', '-created_at'], name='stockmovement_variant_date_idx')]
        constraints = [
            models.CheckConstraint(condition=~Q(quantity=0), name='stockmovement_quantity_not_zero'),
            models.CheckConstraint(
                condition=Q(stock_after=F('stock_before') + F('quantity')),
                name='stockmovement_after_eq_before_plus_qty',
            ),
            models.CheckConstraint(
                condition=(
                    Q(kind='ingreso', quantity__gt=0)
                    | Q(kind='egreso', quantity__lt=0)
                    | Q(kind='ajuste')
                ),
                name='stockmovement_sign_matches_kind',
            ),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} {self.quantity:+d} · {self.variant}'


class StockCount(BaseModel):
    """
    Recuento de stock (parcial: sólo se ajustan las variantes cargadas). Se arma
    en borrador y al confirmarse genera un movimiento de ajuste por diferencia.
    """

    BORRADOR = 'borrador'
    CONFIRMADO = 'confirmado'
    CANCELADO = 'cancelado'
    STATUS_CHOICES = [(BORRADOR, 'Borrador'), (CONFIRMADO, 'Confirmado'), (CANCELADO, 'Cancelado')]

    status = models.CharField('estado', max_length=12, choices=STATUS_CHOICES, default=BORRADOR, db_index=True)
    note = models.CharField('nota', max_length=500, blank=True)
    confirmed_at = models.DateTimeField('confirmado el', null=True, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='confirmado por',
    )

    class Meta:
        verbose_name = 'recuento de stock'
        verbose_name_plural = 'recuentos de stock'
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'Recuento #{self.pk} ({self.get_status_display()})'


class StockCountItem(models.Model):
    """
    Línea de un recuento: lo contado de una variante. `system_quantity` y
    `difference` se completan al confirmar, con el saldo bloqueado en ese momento.
    """

    count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name='items', verbose_name='recuento')
    variant = models.ForeignKey(
        'products.ProductVariant', on_delete=models.PROTECT, related_name='stock_count_items', verbose_name='variante',
    )
    counted_quantity = models.PositiveIntegerField('cantidad contada', validators=[MinValueValidator(0)])
    system_quantity = models.PositiveIntegerField('cantidad en sistema', null=True, blank=True)
    difference = models.IntegerField('diferencia', null=True, blank=True)

    class Meta:
        verbose_name = 'línea de recuento'
        verbose_name_plural = 'líneas de recuento'
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(fields=['count', 'variant'], name='stockcountitem_count_variant_unique'),
        ]

    def __str__(self):
        return f'{self.variant}: {self.counted_quantity}'
