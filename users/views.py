from django.contrib.auth.models import Group
from rest_framework import viewsets
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from core.permissions import DjangoObjectPermissionsWithView
from core.viewsets import BaseModelViewSet
from users.models import User
from users.schemas import (
    GROUP_VIEWSET_SCHEMA,
    TOKEN_OBTAIN_SCHEMA,
    TOKEN_REFRESH_SCHEMA,
    USER_VIEWSET_SCHEMA,
)
from users.serializers import GroupSerializer, UserSerializer


@TOKEN_OBTAIN_SCHEMA
class DocumentedTokenObtainPairView(TokenObtainPairView):
    pass


@TOKEN_REFRESH_SCHEMA
class DocumentedTokenRefreshView(TokenRefreshView):
    pass


@USER_VIEWSET_SCHEMA
class UserViewSet(BaseModelViewSet):
    """
    Administración de usuarios internos. No hay registro público: los
    usuarios se crean y gestionan acá por un Administrador autorizado
    (permisos `users.add_user`/`view_user`/`change_user`/`delete_user`,
    chequeados por `DjangoObjectPermissionsWithView` vía `BaseModelViewSet`).
    """

    queryset = User.objects.all().order_by('email')
    serializer_class = UserSerializer


@GROUP_VIEWSET_SCHEMA
class GroupViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Listado de Groups (roles) disponibles para asignar a un usuario.
    Sólo lectura: los roles en sí se gestionan vía `core.roles.ROLES` +
    `seed_roles`, no desde la API.
    """

    queryset = Group.objects.all().order_by('name')
    serializer_class = GroupSerializer
    permission_classes = [DjangoObjectPermissionsWithView]
