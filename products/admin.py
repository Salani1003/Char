from django.contrib import admin

from core.admin import BaseAdmin
from products.models import Brand, Category, Color, Product, ProductModel, ProductVariant, Size


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
