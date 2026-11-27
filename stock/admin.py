from django.contrib import admin

from stock.models import StockCount, StockCountItem, StockLevel, StockMovement


class ReadOnlyAdmin(admin.ModelAdmin):
    """Sólo consulta: el stock cambia únicamente por `stock.services` (movimientos y recuentos)."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockLevel)
class StockLevelAdmin(ReadOnlyAdmin):
    list_display = ('variant', 'quantity', 'updated_at')
    search_fields = ('variant__sku', 'variant__product__name')


@admin.register(StockMovement)
class StockMovementAdmin(ReadOnlyAdmin):
    list_display = ('created_at', 'variant', 'kind', 'reason', 'quantity', 'stock_before', 'stock_after', 'created_by')
    list_filter = ('kind', 'reason')
    search_fields = ('variant__sku', 'variant__product__name', 'note')
    date_hierarchy = 'created_at'


class StockCountItemInline(admin.TabularInline):
    model = StockCountItem
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(StockCount)
class StockCountAdmin(ReadOnlyAdmin):
    list_display = ('id', 'status', 'note', 'created_at', 'created_by', 'confirmed_at')
    list_filter = ('status',)
    inlines = [StockCountItemInline]
