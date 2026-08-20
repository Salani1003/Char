from django.contrib import admin

from clients.models import Client


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'email', 'phone', 'origin', 'is_deleted')
    list_filter = ('origin', 'is_deleted')
    search_fields = ('first_name', 'last_name', 'email', 'phone')
    ordering = ('last_name', 'first_name')
    readonly_fields = ('created_at', 'updated_at', 'created_by', 'updated_by', 'deleted_at', 'deleted_by')

    def get_queryset(self, request):
        return Client.all_objects.all()