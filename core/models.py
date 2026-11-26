from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.managers import AllObjectsManager, SoftDeleteManager


ACTIVE = Q(is_deleted=False)


def unique_when_active(*fields, name):
    """
    `UniqueConstraint` que sólo aplica entre registros NO eliminados. Es la
    convención del proyecto para unicidad en modelos con soft delete: usar
    `unique=True` haría que un valor de un registro borrado no pudiera
    reutilizarse nunca.

    Uso:
        class Widget(BaseModel):
            code = models.CharField(max_length=20)

            class Meta:
                constraints = [unique_when_active('code', name='widget_code_active_unique')]

    `BaseModelSerializer` valida estas constraints (contra registros activos)
    y devuelve 400 en vez de un `IntegrityError`. Ojo: `restore()` puede
    fallar con `IntegrityError` si el valor ya lo tomó otro registro activo.
    """
    return models.UniqueConstraint(fields=fields, condition=ACTIVE, name=name)


class BaseModel(models.Model):
    """
    Modelo abstracto base y reutilizable que agrega campos de auditoría
    (`created_at`/`updated_at`, `created_by`/`updated_by`) y soft delete
    (`is_deleted`, `deleted_at`, `deleted_by`) a cualquier modelo que
    herede de él. El manager por defecto (`objects`) excluye los registros
    borrados; `all_objects` incluye todo, incluidos los borrados.

    Uso:

        class Widget(BaseModel):
            name = models.CharField(max_length=100)

        widget = Widget.objects.create(name="Foo")
        widget.delete(user)     # soft delete, no borra el registro
        widget.restore()        # revierte el soft delete
        Widget.all_objects.all()  # incluye los borrados
    """

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    # `created_at` e `is_deleted` van indexados: `is_deleted` está en el
    # WHERE de cada consulta del manager por defecto y `created_at` es el
    # orden por defecto de los viewsets.
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        abstract = True

    _SOFT_DELETE_UPDATE_FIELDS = [
        "is_deleted",
        "deleted_at",
        "deleted_by",
        "updated_at",
        "updated_by",
    ]

    def delete(self, user=None, using=None, keep_parents=False):
        """
        Borrado lógico. Mantiene la firma de `Model.delete()` (todos los
        argumentos son opcionales) para que el admin y librerías de terceros
        no revienten; `using`/`keep_parents` se aceptan pero se ignoran
        porque no se borra ninguna fila.
        """
        if self.is_deleted:
            return
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.updated_by = user
        self.save(update_fields=self._SOFT_DELETE_UPDATE_FIELDS)

    def restore(self, user=None):
        if not self.is_deleted:
            return
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.updated_by = user
        self.save(update_fields=self._SOFT_DELETE_UPDATE_FIELDS)

    def set_created_by(self, user):
        self.created_by = user

    def set_updated_by(self, user):
        self.updated_by = user
