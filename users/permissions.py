from rest_framework.permissions import SAFE_METHODS, BasePermission

__all__ = ['CanManageUser', 'can_manage_user']


def can_manage_user(actor, target):
    """
    Anti-toma de cuentas: un superuser gestiona a cualquiera; el resto sólo a
    usuarios que NO son superuser y cuyos roles y permisos son un subconjunto
    de los suyos. Sin esto, un rol intermedio con `users.change_user` podría
    cambiarle el email o la contraseña a un Administrador (y entrar con su
    cuenta) o quitarle sus roles.
    """
    if actor.is_superuser:
        return True
    if target.is_superuser:
        return False
    actor_groups = set(actor.groups.values_list('pk', flat=True))
    target_groups = set(target.groups.values_list('pk', flat=True))
    if not target_groups <= actor_groups:
        return False
    return target.get_all_permissions() <= actor.get_all_permissions()


class CanManageUser(BasePermission):
    """
    Permiso de objeto para `UserViewSet`, que se suma a los permisos de
    Django. Sólo restringe escrituras (la lectura queda a cargo de
    `view_user`):

    * No se puede modificar ni borrar a un usuario con más permisos que uno.
    * Nadie puede borrarse (desactivarse) a sí mismo: así siempre queda al
      menos un usuario activo capaz de administrar, y no hay lockout por
      accidente. (Desactivarse con `PATCH is_active=false` se bloquea en
      `UserSerializer.validate_is_active`.)
    """

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if request.method == 'DELETE' and obj.pk == request.user.pk:
            self.message = 'No podés eliminar tu propio usuario.'
            return False
        if not can_manage_user(request.user, obj):
            self.message = 'No podés modificar a un usuario con más permisos que vos.'
            return False
        return True
