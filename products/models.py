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
