from django.http import Http404
from rest_framework.permissions import SAFE_METHODS, DjangoObjectPermissions

__all__ = ['DjangoObjectPermissionsWithView']


class DjangoObjectPermissionsWithView(DjangoObjectPermissions):
    """
    Clase de permiso genérica y reutilizable, basada en el sistema nativo
    de Permissions/Groups de Django.

    `DjangoObjectPermissions` de DRF sólo chequea permisos en requests de
    escritura (POST/PUT/PATCH/DELETE) y deja leer a cualquier usuario
    autenticado. Esta subclase exige además el permiso `view_<modelo>` en
    métodos seguros, así el acceso de lectura queda controlado igual que
    el de escritura: sólo a través de los `Permission`/`Group` de Django
    asignados al usuario (administrables desde el admin, sin lógica
    custom).

    Los permisos a nivel de endpoint funcionan de entrada: el backend de
    auth por defecto de Django evalúa permisos a nivel de modelo, así que
    `has_permission()` se aplica en cada request (ej. "puede listar/crear
    Widgets").

    Los permisos a nivel de objeto ya están preparados: DRF llama a
    `has_object_permission()` en retrieve/update/delete, y esta clase ya
    lo implementa delegando en `user.has_perm(perm, obj)`. Bajo el backend
    por defecto ese llamado es un no-op (el argumento `obj` se ignora), así
    que degrada silenciosamente a chequeo por modelo hasta que se agregue
    un backend de permisos de objeto (ej. `django-guardian`) a
    `AUTHENTICATION_BACKENDS` — en ese momento los permisos de objeto se
    activan solos, sin tocar esta clase ni las vistas que la usan.
    """

    perms_map = {
        **DjangoObjectPermissions.perms_map,
        'GET': ['%(app_label)s.view_%(model_name)s'],
        'OPTIONS': ['%(app_label)s.view_%(model_name)s'],
        'HEAD': ['%(app_label)s.view_%(model_name)s'],
    }

    def has_object_permission(self, request, view, obj):
        """
        Reimplementa `DjangoObjectPermissions.has_object_permission` con un
        fallback a nivel de modelo.

        Django's `ModelBackend.get_all_permissions()` devuelve un set
        vacío en cuanto se le pasa un `obj`, así que `user.has_perms(perms,
        obj)` siempre da `False` para usuarios no-superuser bajo el backend
        de auth por defecto, sin importar los Permissions/Groups que
        tengan asignados. Sin este fallback, cualquier retrieve/update/
        destroy de un objeto puntual quedaría bloqueado para todo el mundo
        salvo superusers, aunque tengan el Permission correspondiente.

        Se chequea el permiso a nivel de objeto (relevante en cuanto se
        agregue un backend como `django-guardian`) OR a nivel de modelo, de
        forma que hoy (sin backend de permisos de objeto) esto se comporta
        como un chequeo de modelo puro, y el día que se agregue ese backend,
        los permisos de objeto se suman sin quitarle acceso a quien ya
        tenía el permiso a nivel de modelo.
        """
        queryset = self._queryset(view)
        model_cls = queryset.model
        user = request.user

        perms = self.get_required_object_permissions(request.method, model_cls)

        if not (user.has_perms(perms, obj) or user.has_perms(perms)):
            if request.method in SAFE_METHODS:
                raise Http404

            read_perms = self.get_required_object_permissions('GET', model_cls)
            if not (user.has_perms(read_perms, obj) or user.has_perms(read_perms)):
                raise Http404

            return False

        return True
