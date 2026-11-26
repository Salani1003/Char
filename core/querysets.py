from django.db import models
from django.utils import timezone


class SoftDeleteQuerySet(models.QuerySet):
    def delete(self, user=None):
        """
        Borrado lógico masivo. `user` es opcional para respetar el contrato de
        `QuerySet.delete()` (el admin de Django, por ejemplo, lo llama sin
        argumentos).
        """
        now = timezone.now()
        return self.filter(is_deleted=False).update(
            is_deleted=True,
            deleted_at=now,
            deleted_by=user,
            updated_at=now,
            updated_by=user,
        )
