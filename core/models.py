from django.conf import settings
from django.db import models
from django.utils import timezone

from core.managers import AllObjectsManager, SoftDeleteManager


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

    created_at = models.DateTimeField(auto_now_add=True)
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
    is_deleted = models.BooleanField(default=False)
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

    def delete(self, user):
        if self.is_deleted:
            return

        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

    def restore(self):
        if not self.is_deleted:
            return

        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

    def set_created_by(self, user):
        self.created_by = user

    def set_updated_by(self, user):
        self.updated_by = user
