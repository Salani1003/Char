from django.contrib.auth.models import Group
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import (
    TokenBlacklistView,
    TokenObtainPairView,
    TokenRefreshView,
)

from core.permissions import DjangoObjectPermissionsWithView
from core.viewsets import BaseModelViewSet
from users.models import User
from users.schemas import (
    GROUP_VIEWSET_SCHEMA,
    ME_SCHEMA,
    TOKEN_BLACKLIST_SCHEMA,
    TOKEN_OBTAIN_SCHEMA,
    TOKEN_REFRESH_SCHEMA,
    USER_VIEWSET_SCHEMA,
)
from users.serializers import GroupSerializer, UserSerializer


@TOKEN_OBTAIN_SCHEMA
class DocumentedTokenObtainPairView(TokenObtainPairView):
    # Scope de throttling más estricto que el 'anon' default: este endpoint
    # es el blanco directo de fuerza bruta de contraseñas.
    throttle_scope = 'login'


@TOKEN_REFRESH_SCHEMA
class DocumentedTokenRefreshView(TokenRefreshView):
    throttle_scope = 'login'


@TOKEN_BLACKLIST_SCHEMA
class DocumentedTokenBlacklistView(TokenBlacklistView):
    """
    Logout real: mete el `refresh` token en la blacklist para que ya no
    pueda usarse para pedir nuevos `access` tokens. No invalida el `access`
    token vivo (sigue firmado y válido hasta que expire solo, típicamente
    unos minutos) — es la limitación inherente de un JWT stateless.
    """


@USER_VIEWSET_SCHEMA
class UserViewSet(BaseModelViewSet):
    """
    Administración de usuarios internos. No hay registro público: los
    usuarios se crean y gestionan acá por un Administrador autorizado
    (permisos `users.add_user`/`view_user`/`change_user`/`delete_user`,
    chequeados por `DjangoObjectPermissionsWithView` vía `BaseModelViewSet`).
    """

    queryset = User.objects.all().order_by('id')
    serializer_class = UserSerializer
    filterset_fields = ['is_active']

    def perform_create(self, serializer):
        serializer.save()

    def perform_update(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=['is_active'])

    @ME_SCHEMA
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def me(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)


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
