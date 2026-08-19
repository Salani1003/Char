from rest_framework.permissions import DjangoObjectPermissions

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
