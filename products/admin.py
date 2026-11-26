from django.contrib import admin

from core.admin import BaseAdmin
from products.models import Categoria, Color, Producto, Stock, Variante


@admin.register(Categoria)
class CategoriaAdmin(BaseAdmin):
    list_display = ('id', 'nombre')
    search_fields = ('nombre',)


@admin.register(Color)
class ColorAdmin(BaseAdmin):
    list_display = ('id', 'nombre')
    search_fields = ('nombre',)


@admin.register(Producto)
class ProductoAdmin(BaseAdmin):
    list_display = ('id', 'nombre', 'categoria', 'precio_venta', 'precio_costo')
    search_fields = ('nombre',)
    list_filter = BaseAdmin.list_filter + ('categoria',)


@admin.register(Variante)
class VarianteAdmin(BaseAdmin):
    list_display = ('id', 'producto', 'talle', 'color')
    search_fields = ('producto__nombre', 'color__nombre')
    list_filter = BaseAdmin.list_filter + ('producto', 'talle', 'color')


@admin.register(Stock)
class StockAdmin(BaseAdmin):
    list_display = ('id', 'variante', 'fisica', 'reservada', 'disponible')
    search_fields = ('variante__producto__nombre', 'variante__color__nombre')
    list_filter = BaseAdmin.list_filter + ('variante__talle', 'variante__color')

    def disponible(self, obj):
        return obj.disponible
    disponible.short_description = 'Disponible'
