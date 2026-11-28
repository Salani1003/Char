from django.contrib import admin

from sales.models import Exchange, ExchangeItem, Sale, SaleItem


class ReadOnlyAdmin(admin.ModelAdmin):
    """Sólo consulta: las ventas y cambios se registran y anulan únicamente por `sales.services`."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class _ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class SaleItemInline(_ReadOnlyInline):
    model = SaleItem


class ExchangeItemInline(_ReadOnlyInline):
    model = ExchangeItem


@admin.register(Sale)
class SaleAdmin(ReadOnlyAdmin):
    list_display = ('id', 'created_at', 'client', 'total', 'payment_method', 'status', 'created_by')
    list_filter = ('status', 'payment_method')
    search_fields = ('id', 'client__first_name', 'client__last_name', 'client__email')
    date_hierarchy = 'created_at'
    inlines = [SaleItemInline]


@admin.register(Exchange)
class ExchangeAdmin(ReadOnlyAdmin):
    list_display = ('id', 'created_at', 'sale', 'difference', 'payment_method', 'status', 'created_by')
    list_filter = ('status',)
    date_hierarchy = 'created_at'
    inlines = [ExchangeItemInline]
