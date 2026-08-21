from django.contrib import admin
from products.models import Categoria, Color, Producto, Stock, Variante


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre')
    search_fields = ('nombre',)


@admin.register(Color)
class ColorAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre')
    search_fields = ('nombre',)


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'categoria', 'precio_venta', 'precio_costo')
    search_fields = ('nombre',)
    list_filter = ('categoria',)


@admin.register(Variante)
class VarianteAdmin(admin.ModelAdmin):
    list_display = ('id', 'producto', 'talle', 'color')
    search_fields = ('producto__nombre', 'color__nombre')
    list_filter = ('producto', 'talle', 'color')


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ('id', 'variante', 'fisica', 'reservada', 'disponible')
    search_fields = ('variante__producto__nombre', 'variante__color__nombre')
    list_filter = ('variante__talle', 'variante__color')

    def disponible(self, obj):
        return obj.disponible
    disponible.short_description = 'Disponible'
