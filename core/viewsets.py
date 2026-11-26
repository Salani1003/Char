from django.db import IntegrityError, transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from core.pagination import DefaultPagination
from core.permissions import DjangoObjectPermissionsWithView, DjangoRestorePermission

__all__ = ['BaseModelViewSet', 'RestoreModelMixin']


class RestoreModelMixin:
    """
    Agrega `POST <recurso>/{id}/restore/` a un viewset de un modelo que herede
    de `core.models.BaseModel`: revierte el soft delete. Requiere el permiso
    `change_<modelo>`. Sólo ve registros eliminados (uno activo da 404).

    Uso (el mixin va antes que `BaseModelViewSet`):

        class WidgetViewSet(RestoreModelMixin, BaseModelViewSet):
            ...
    """

    def get_permissions(self):
        # Se resuelve acá y no en el kwarg `permission_classes` del @action:
        # así vale también cuando la view se instancia sin router.
        if self.action == 'restore':
            return [DjangoRestorePermission()]
        return super().get_permissions()

    def get_queryset(self):
        if self.action == 'restore':
            return self.queryset.model.all_objects.filter(is_deleted=True)
        return super().get_queryset()

    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        instance = self.get_object()
        try:
            with transaction.atomic():
                instance.restore(request.user)
        except IntegrityError as exc:
            raise ValidationError(
                'No se puede restaurar: un valor único ya fue tomado por otro registro.'
            ) from exc
        return Response(self.get_serializer(instance).data)


class BaseModelViewSet(viewsets.ModelViewSet):
    """
    Viewset base y reutilizable que conecta los Groups/Permissions nativos
    de Django con DRF vía `DjangoObjectPermissionsWithView`. Al heredar de
    esta clase, cualquier modelo obtiene gratis:

      * Permisos a nivel de endpoint: cada método HTTP se mapea al permiso
        Django correspondiente (add/change/delete/view_<modelo>), chequeado
        contra los grupos/permisos del usuario que hace el request.
      * Permisos a nivel de objeto: listos para activarse en cuanto se
        configure un backend de permisos de objeto (ej. `django-guardian`);
        no hace falta tocar nada acá cuando eso pase.
      * Filtros (`filterset_fields`), búsqueda (`search_fields`) y orden
        (`?ordering=`, por defecto `-created_at`) listos para configurar
        por viewset.
      * Paginación por página vía `DefaultPagination` (20 resultados por
        página, ajustable con `?page_size=` hasta un máximo de 100).

    Uso:

        class WidgetViewSet(BaseModelViewSet):
            queryset = Widget.objects.all()
            serializer_class = WidgetSerializer
    """

    permission_classes = [DjangoObjectPermissionsWithView]
    pagination_class = DefaultPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    # Orden determinista: sin él, la paginación puede repetir/saltear filas.
    # Los modelos que no tengan `created_at` deben sobreescribirlo.
    ordering = ['-created_at', '-id']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    def perform_destroy(self, instance):
        instance.delete(self.request.user)
