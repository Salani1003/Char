from django.core.exceptions import FieldDoesNotExist
from django.db import models
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from core.models import ACTIVE

__all__ = ['AUDIT_FIELDS', 'BaseModelSerializer']

AUDIT_FIELDS = [
    'created_at',
    'updated_at',
    'created_by',
    'updated_by',
]


class BaseModelSerializer(serializers.ModelSerializer):
    """
    Serializer base y reutilizable para modelos que heredan de
    `core.models.BaseModel`.

    * Los campos de auditoría y de soft delete (`created_*`, `updated_*`,
      `is_deleted`, `deleted_*`) son siempre de sólo lectura: los completa
      `BaseModelViewSet`, nunca el cliente. Para exponerlos en la respuesta
      alcanza con listarlos en `Meta.fields` (hay un atajo en `AUDIT_FIELDS`).
    * Unicidad con soft delete, dos casos:
        - Campos con `unique=True`: la base sí ve los registros borrados, así
          que los `UniqueValidator` de DRF consultan `all_objects` (si no, el
          valor de un borrado pasaba la validación y reventaba con
          `IntegrityError`).
        - `core.models.unique_when_active(...)` (recomendado): la constraint
          sólo aplica entre activos y se valida acá contra `objects`, así un
          valor de un registro borrado se puede reutilizar.

    Uso:
        class WidgetSerializer(BaseModelSerializer):
            class Meta:
                model = Widget
                fields = ['id', 'name', *AUDIT_FIELDS]
    """

    SYSTEM_FIELDS = (
        'created_at',
        'updated_at',
        'created_by',
        'updated_by',
        'is_deleted',
        'deleted_at',
        'deleted_by',
    )

    def get_extra_kwargs(self):
        extra_kwargs = super().get_extra_kwargs()
        for name in self.SYSTEM_FIELDS:
            kwargs = extra_kwargs.setdefault(name, {})
            kwargs['read_only'] = True
            # `read_only` es incompatible con `required`/`queryset`.
            kwargs.pop('required', None)
            kwargs.pop('queryset', None)
        return extra_kwargs

    def get_fields(self):
        fields = super().get_fields()
        all_objects = getattr(self.Meta.model, 'all_objects', None)
        if all_objects is not None:
            for name, field in fields.items():
                try:
                    model_field = self.Meta.model._meta.get_field(field.source or name)
                except FieldDoesNotExist:
                    continue
                # Sólo `unique=True`: las constraints condicionales
                # (`unique_when_active`) deben validarse contra activos.
                # Las relaciones inversas (nested serializers) no tienen `unique`.
                if not getattr(model_field, 'unique', False):
                    continue
                for validator in field.validators:
                    if isinstance(validator, UniqueValidator):
                        validator.queryset = all_objects.all()
        return fields

    def validate(self, attrs):
        attrs = super().validate(attrs)
        model = self.Meta.model
        for constraint in model._meta.constraints:
            if not (
                isinstance(constraint, models.UniqueConstraint)
                and constraint.fields
                and constraint.condition == ACTIVE
            ):
                continue
            lookup = {}
            for name in constraint.fields:
                if name in attrs:
                    value = attrs[name]
                elif self.instance is not None:
                    value = getattr(self.instance, name)
                else:
                    value = None
                if value is None:
                    # NULL nunca choca en una unique constraint.
                    lookup = None
                    break
                lookup[name] = value
            if lookup is None:
                continue
            existing = model.objects.filter(**lookup)
            if self.instance is not None:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                message = 'Ya existe un registro con este valor.'
                if len(constraint.fields) == 1:
                    raise serializers.ValidationError({constraint.fields[0]: message})
                raise serializers.ValidationError(message)
        return attrs
