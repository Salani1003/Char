from django.conf import settings
from django.db import models
from django.db.models import F, Q

__all__ = ['PaymentMethod', 'Sale', 'SaleItem', 'Exchange', 'ExchangeItem']


class PaymentMethod(models.TextChoices):
    TRANSFERENCIA = 'transferencia', 'Transferencia'
    EFECTIVO = 'efectivo', 'Efectivo'
    TARJETA_CREDITO = 'tarjeta_credito', 'Tarjeta de crédito'
    TARJETA_DEBITO = 'tarjeta_debito', 'Tarjeta de débito'
    QR = 'qr', 'QR'


class _Status(models.TextChoices):
    COMPLETADA = 'completada', 'Completada'
    ANULADA = 'anulada', 'Anulada'


def _user_fk(verbose_name):
    return models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name=verbose_name,
    )


class Sale(models.Model):
    """
    Venta. No es `BaseModel`: no se borra ni se edita, se anula (`status='anulada'`) y el stock vuelve
    con `stock.services.reverse_operation`. Los precios de sus ítems quedan congelados al vender. El
    stock se descuenta desde `sales.services`, nunca a mano.
    """

    Status = _Status

    client = models.ForeignKey(
        'clients.Client', null=True, blank=True, on_delete=models.PROTECT,
        related_name='sales', verbose_name='cliente',
    )
    payment_method = models.CharField('medio de pago', max_length=20, choices=PaymentMethod.choices)
    subtotal = models.DecimalField('subtotal', max_digits=12, decimal_places=2, help_text='A precio vigente, sin descuento.')
    discount_percent = models.PositiveSmallIntegerField('descuento (%)', default=0)
    discount_reason = models.CharField('motivo del descuento', max_length=200, blank=True)
    total = models.DecimalField('total', max_digits=12, decimal_places=2, help_text='Lo cobrado: suma de los ítems con descuento.')
    note = models.CharField('nota', max_length=500, blank=True)
    status = models.CharField('estado', max_length=12, choices=Status.choices, default=Status.COMPLETADA, db_index=True)
    idempotency_key = models.CharField(
        'clave de idempotencia', max_length=64, null=True, blank=True, unique=True,
        help_text='Evita registrar dos veces la misma venta si el cliente reintenta el POST.',
    )
    created_at = models.DateTimeField('fecha', auto_now_add=True, db_index=True)
    created_by = _user_fk('vendedor')
    voided_at = models.DateTimeField('anulada el', null=True, blank=True)
    voided_by = _user_fk('anulada por')
    void_reason = models.CharField('motivo de anulación', max_length=500, blank=True)

    class Meta:
        verbose_name = 'venta'
        verbose_name_plural = 'ventas'
        ordering = ['-created_at', '-id']
        permissions = [
            ('void_sale', 'Puede anular ventas'),
            ('apply_discount', 'Puede aplicar descuentos en una venta'),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(total__gte=0), name='sale_total_gte_0'),
            models.CheckConstraint(condition=Q(discount_percent__lte=100), name='sale_discount_lte_100'),
        ]

    def __str__(self):
        return f'Venta #{self.pk}'


class SaleItem(models.Model):
    """Línea de una venta, con el precio congelado al momento de vender."""

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='items', verbose_name='venta')
    variant = models.ForeignKey(
        'products.ProductVariant', on_delete=models.PROTECT, related_name='sale_items', verbose_name='variante',
    )
    quantity = models.PositiveIntegerField('cantidad')
    list_price = models.DecimalField('precio de lista', max_digits=12, decimal_places=2, help_text='Vigente al vender (promo o venta).')
    discount_percent = models.PositiveSmallIntegerField('descuento (%)', default=0)
    unit_price = models.DecimalField('precio unitario', max_digits=12, decimal_places=2, help_text='Lo que pagó el cliente por unidad.')
    subtotal = models.DecimalField('subtotal', max_digits=12, decimal_places=2, help_text='`unit_price` × `quantity`.')
    exchanged_quantity = models.PositiveIntegerField(
        'unidades cambiadas', default=0, help_text='Las que ya volvieron en cambios activos.',
    )

    class Meta:
        verbose_name = 'ítem de venta'
        verbose_name_plural = 'ítems de venta'
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(fields=['sale', 'variant'], name='saleitem_sale_variant_unique'),
            models.CheckConstraint(condition=Q(quantity__gt=0), name='saleitem_quantity_gt_0'),
            models.CheckConstraint(condition=Q(exchanged_quantity__lte=F('quantity')), name='saleitem_exchanged_lte_quantity'),
        ]

    def __str__(self):
        return f'{self.variant} × {self.quantity}'


class Exchange(models.Model):
    """
    Cambio sobre una venta: devuelve ítems de ella y se lleva otros. No hay devoluciones de dinero:
    `difference` (nuevo − devuelto) positiva se paga (`payment_method`); negativa o cero no mueve
    plata y lo no devuelto queda en `unreturned_amount`. Genera dos operaciones de stock atómicas
    (ingreso `cambio_entrada` y egreso `cambio_salida`). Como la venta, no se edita: se anula.
    """

    Status = _Status

    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name='exchanges', verbose_name='venta')
    payment_method = models.CharField(
        'medio de pago', max_length=20, choices=PaymentMethod.choices, blank=True,
        help_text='Sólo si hay diferencia a pagar.',
    )
    returned_total = models.DecimalField('total devuelto', max_digits=12, decimal_places=2)
    new_total = models.DecimalField('total nuevo', max_digits=12, decimal_places=2)
    difference = models.DecimalField('diferencia', max_digits=12, decimal_places=2, help_text='Nuevo − devuelto. Positiva: la paga el cliente.')
    note = models.CharField('nota', max_length=500, blank=True)
    status = models.CharField('estado', max_length=12, choices=Status.choices, default=Status.COMPLETADA, db_index=True)
    created_at = models.DateTimeField('fecha', auto_now_add=True, db_index=True)
    created_by = _user_fk('usuario')
    voided_at = models.DateTimeField('anulado el', null=True, blank=True)
    voided_by = _user_fk('anulado por')
    void_reason = models.CharField('motivo de anulación', max_length=500, blank=True)

    class Meta:
        verbose_name = 'cambio'
        verbose_name_plural = 'cambios'
        ordering = ['-created_at', '-id']
        permissions = [('void_exchange', 'Puede anular cambios')]
        constraints = [
            models.CheckConstraint(
                condition=Q(difference__gt=0) | Q(payment_method=''), name='exchange_payment_only_if_difference',
            ),
        ]

    @property
    def unreturned_amount(self):
        """Valor devuelto que no se compensó: no se reintegra (no hay devoluciones de dinero)."""
        return max(-self.difference, 0)

    def __str__(self):
        return f'Cambio #{self.pk}'


class ExchangeItem(models.Model):
    """Línea de un cambio: lo que vuelve (`in`, de un ítem de la venta) o lo que se lleva (`out`)."""

    IN, OUT = 'in', 'out'
    DIRECTION_CHOICES = [(IN, 'Devuelve'), (OUT, 'Se lleva')]

    exchange = models.ForeignKey(Exchange, on_delete=models.CASCADE, related_name='items', verbose_name='cambio')
    direction = models.CharField('sentido', max_length=3, choices=DIRECTION_CHOICES)
    variant = models.ForeignKey(
        'products.ProductVariant', on_delete=models.PROTECT, related_name='exchange_items', verbose_name='variante',
    )
    quantity = models.PositiveIntegerField('cantidad')
    unit_price = models.DecimalField(
        'precio unitario', max_digits=12, decimal_places=2,
        help_text='Devuelto: lo que pagó en la venta. Nuevo: precio vigente hoy, sin descuento.',
    )
    sale_item = models.ForeignKey(
        SaleItem, null=True, blank=True, on_delete=models.PROTECT, related_name='exchange_items',
        verbose_name='ítem de la venta', help_text='Sólo en lo que se devuelve.',
    )

    class Meta:
        verbose_name = 'ítem de cambio'
        verbose_name_plural = 'ítems de cambio'
        ordering = ['direction', 'id']
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name='exchangeitem_quantity_gt_0'),
            models.CheckConstraint(
                condition=(Q(direction='in', sale_item__isnull=False) | Q(direction='out', sale_item__isnull=True)),
                name='exchangeitem_sale_item_only_if_in',
            ),
        ]

    def __str__(self):
        return f'{self.get_direction_display()} {self.variant} × {self.quantity}'
