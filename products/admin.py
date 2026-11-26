from django.contrib import admin

from core.admin import BaseAdmin
from products.models import Brand, Category, Color, Product, ProductImage, ProductModel, ProductVariant, Size


@admin.register(Category)
class CategoryAdmin(BaseAdmin):
    list_display = ('name', 'slug', 'parent')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)


@admin.register(Brand)
class BrandAdmin(BaseAdmin):
    list_display = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)


@admin.register(ProductModel)
class ProductModelAdmin(BaseAdmin):
    list_display = ('name', 'brand')
    list_filter = BaseAdmin.list_filter + ('brand',)
    search_fields = ('name', 'brand__name')


@admin.register(Color)
class ColorAdmin(BaseAdmin):
    list_display = ('name', 'hex')
    search_fields = ('name',)


@admin.register(Size)
class SizeAdmin(BaseAdmin):
    list_display = ('name', 'order')
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(BaseAdmin):
    list_display = ('name', 'slug', 'category', 'brand', 'product_model', 'sale_price', 'is_published')
    list_filter = BaseAdmin.list_filter + ('is_published', 'category', 'brand')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name', 'brand__name', 'product_model__name')


@admin.register(ProductVariant)
class ProductVariantAdmin(BaseAdmin):
    list_display = ('sku', 'product', 'color', 'size')
    list_filter = BaseAdmin.list_filter + ('color', 'size')
    search_fields = ('sku', 'product__name')
    readonly_fields = ('sku',)


@admin.register(ProductImage)
class ProductImageAdmin(BaseAdmin):
    # Sólo consulta: alta y baja pasan por la API (suben/borran el archivo en el proveedor).
    list_display = ('product', 'color', 'is_primary', 'sort_order', 'storage_key')
    list_filter = BaseAdmin.list_filter + ('color',)
    search_fields = ('product__name', 'storage_key')
    readonly_fields = ('storage_key',)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        # Restaurar una imagen no recuperaría su archivo, que ya se borró del proveedor.
        actions = super().get_actions(request)
        actions.pop('restore_selected', None)
        return actions
