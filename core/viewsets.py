from rest_framework import viewsets

from core.permissions import DjangoObjectPermissionsWithView

__all__ = ['BaseModelViewSet']


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

    Uso:

        class WidgetViewSet(BaseModelViewSet):
            queryset = Widget.objects.all()
            serializer_class = WidgetSerializer
    """

    permission_classes = [DjangoObjectPermissionsWithView]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)
