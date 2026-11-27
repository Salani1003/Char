from rest_framework.permissions import BasePermission

__all__ = ['ActionPermission']


class ActionPermission(BasePermission):
    """
    Permisos de Django por acción de la view, para endpoints que no son un CRUD
    de un modelo. La view declara `required_perms = {'list': [...], 'create': [...]}`
    (`'<app>.<codename>'`); una acción sin entrada se deniega.
    """

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        perms = getattr(view, 'required_perms', {}).get(view.action)
        return bool(perms) and user.has_perms(perms)
