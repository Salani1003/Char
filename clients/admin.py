from django.contrib import admin

from clients.models import Client
from core.admin import BaseAdmin


@admin.register(Client)
class ClientAdmin(BaseAdmin):
    list_display = ('first_name', 'last_name', 'email', 'phone', 'origin')
    list_filter = BaseAdmin.list_filter + ('origin',)
    search_fields = ('first_name', 'last_name', 'email', 'phone')
    ordering = ('last_name', 'first_name')
