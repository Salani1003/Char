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
