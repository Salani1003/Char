from django.db import models

from core.models import BaseModel


class Categoria(BaseModel):
    nombre = models.CharField(max_length=100, blank=False)

    def __str__(self):
        return self.nombre


class Color(BaseModel):
    nombre = models.CharField(max_length=100, blank=False, unique=True)

    def __str__(self):
        return self.nombre


class Producto(BaseModel):
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, related_name='productos')
    nombre = models.CharField(max_length=150, blank=False)
    descripcion = models.TextField(blank=True)
    precio_venta = models.DecimalField(max_digits=12, decimal_places=2)
    precio_costo = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return self.nombre


class Variante(BaseModel):
    class Talle(models.TextChoices):
        XS = 'XS', 'XS'
        S = 'S', 'S'
        M = 'M', 'M'
        L = 'L', 'L'
        XL = 'XL', 'XL'
        XXL = 'XXL', 'XXL'
        UNICO = 'UNICO', 'Único'

    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name='variantes')
    talle = models.CharField(max_length=5, choices=Talle.choices)
    color = models.ForeignKey(Color, on_delete=models.PROTECT, related_name='variantes')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['producto', 'talle', 'color'],
                name='unique_variante_producto_talle_color',
            ),
        ]

    def __str__(self):
        return f'{self.producto.nombre} - {self.talle} - {self.color.nombre}'


class Stock(BaseModel):
    variante = models.OneToOneField(Variante, on_delete=models.PROTECT, related_name='stock')
    fisica = models.PositiveIntegerField(default=0)
    reservada = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(reservada__lte=models.F('fisica')),
                name='stock_reservada_lte_fisica',
            ),
        ]

    @property
    def disponible(self):
        return self.fisica - self.reservada

    def __str__(self):
        return f'{self.variante} - disponible: {self.disponible}'
