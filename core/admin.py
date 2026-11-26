from django.contrib import admin, messages
from django.db import IntegrityError, transaction

__all__ = ['BaseAdmin', 'DeletedFilter']


class DeletedFilter(admin.SimpleListFilter):
    title = 'estado'
    parameter_name = 'deleted'

    def lookups(self, request, model_admin):
        return [('no', 'Activos'), ('yes', 'Eliminados')]

    def queryset(self, request, queryset):
        if self.value() == 'no':
            return queryset.filter(is_deleted=False)
        if self.value() == 'yes':
            return queryset.filter(is_deleted=True)
        return queryset


class BaseAdmin(admin.ModelAdmin):
    """
    `ModelAdmin` base para modelos que heredan de `core.models.BaseModel`.

    * Lista TODOS los registros (`all_objects`), con una columna `is_deleted`
      y un filtro Activos/Eliminados.
    * Acción masiva "Restaurar seleccionados".
    * Borrar desde el admin es soft delete y registra `deleted_by`.
    * `created_by`/`updated_by`/`deleted_by` se completan solos y son de sólo
      lectura.

    Uso:
        @admin.register(Widget)
        class WidgetAdmin(BaseAdmin):
            list_display = ['name']
            list_filter = BaseAdmin.list_filter + ('category',)
    """

    list_filter = (DeletedFilter,)
    actions = ['restore_selected']
    audit_readonly_fields = ('created_by', 'updated_by', 'deleted_by', 'deleted_at')

    def get_queryset(self, request):
        queryset = self.model.all_objects.get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            queryset = queryset.order_by(*ordering)
        return queryset

    def get_list_display(self, request):
        list_display = list(super().get_list_display(request))
        if 'is_deleted' not in list_display:
            list_display.append('is_deleted')
        return list_display

    def get_readonly_fields(self, request, obj=None):
        return (*super().get_readonly_fields(request, obj), *self.audit_readonly_fields)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        obj.delete(request.user)

    def delete_queryset(self, request, queryset):
        queryset.delete(request.user)

    @admin.action(description='Restaurar seleccionados', permissions=['change'])
    def restore_selected(self, request, queryset):
        restored = 0
        for obj in queryset.filter(is_deleted=True):
            try:
                # Savepoint: un conflicto de unicidad no debe abortar el resto.
                with transaction.atomic():
                    obj.restore(request.user)
            except IntegrityError:
                self.message_user(
                    request,
                    f'No se pudo restaurar "{obj}": otro registro activo ya usa ese valor único.',
                    level=messages.ERROR,
                )
            else:
                restored += 1
        if restored:
            self.message_user(request, f'{restored} registro(s) restaurado(s).', level=messages.SUCCESS)
