from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase
from rest_framework import generics, serializers
from rest_framework.test import APIRequestFactory, force_authenticate

from core.permissions import DjangoObjectPermissionsWithView
from users.models import User


class _UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email']


class _UserListCreateView(generics.ListCreateAPIView):
    queryset = User.objects.all()
    serializer_class = _UserSerializer
    permission_classes = [DjangoObjectPermissionsWithView]


class DjangoObjectPermissionsWithViewTests(TestCase):
    """
    Prueba de punta a punta la clase de permiso genérica contra una vista
    genérica de DRF, verificando que el acceso a nivel de endpoint queda
    totalmente gobernado por los Groups/Permissions nativos de Django
    (sin lógica de permisos custom).
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(email='member@example.com', password='pass12345')
        self.content_type = ContentType.objects.get_for_model(User)

    def _grant(self, codename):
        permission = Permission.objects.get(content_type=self.content_type, codename=codename)
        group, _ = Group.objects.get_or_create(name=f'has_{codename}')
        group.permissions.add(permission)
        self.user.groups.add(group)

    def test_read_denied_without_view_permission(self):
        request = self.factory.get('/fake-users/')
        force_authenticate(request, user=self.user)
        response = _UserListCreateView.as_view()(request)
        self.assertEqual(response.status_code, 403)

    def test_read_allowed_with_view_permission_granted_via_group(self):
        self._grant('view_user')
        request = self.factory.get('/fake-users/')
        force_authenticate(request, user=self.user)
        response = _UserListCreateView.as_view()(request)
        self.assertEqual(response.status_code, 200)

    def test_write_denied_without_add_permission(self):
        request = self.factory.post(
            '/fake-users/', {'email': 'new@example.com'}, format='json'
        )
        force_authenticate(request, user=self.user)
        response = _UserListCreateView.as_view()(request)
        self.assertEqual(response.status_code, 403)

    def test_write_allowed_with_add_permission_granted_via_group(self):
        self._grant('add_user')
        request = self.factory.post(
            '/fake-users/', {'email': 'new@example.com'}, format='json'
        )
        force_authenticate(request, user=self.user)
        response = _UserListCreateView.as_view()(request)
        self.assertEqual(response.status_code, 201)

    def test_unauthenticated_request_denied(self):
        request = self.factory.get('/fake-users/')
        response = _UserListCreateView.as_view()(request)
        self.assertEqual(response.status_code, 401)


class SeedRolesCommandTests(TestCase):
    """
    Verifica que `seed_roles` crea Groups y asigna Permissions nativos de
    Django a partir de `core.roles.ROLES`, que es idempotente, y que avisa
    claramente cuando se define un permiso inexistente.
    """

    def _run(self):
        out, err = StringIO(), StringIO()
        call_command('seed_roles', stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_creates_group_and_assigns_defined_permissions(self):
        roles = {'Editors': ['users.view_user', 'users.change_user']}
        with mock.patch('core.management.commands.seed_roles.ROLES', roles):
            self._run()

        group = Group.objects.get(name='Editors')
        codenames = set(group.permissions.values_list('codename', flat=True))
        self.assertEqual(codenames, {'view_user', 'change_user'})

    def test_is_idempotent(self):
        roles = {'Editors': ['users.view_user']}
        with mock.patch('core.management.commands.seed_roles.ROLES', roles):
            self._run()
            self._run()

        self.assertEqual(Group.objects.filter(name='Editors').count(), 1)
        group = Group.objects.get(name='Editors')
        self.assertEqual(group.permissions.count(), 1)

    def test_removes_stale_permissions_on_rerun(self):
        roles = {'Editors': ['users.view_user', 'users.change_user']}
        with mock.patch('core.management.commands.seed_roles.ROLES', roles):
            self._run()

        roles = {'Editors': ['users.view_user']}
        with mock.patch('core.management.commands.seed_roles.ROLES', roles):
            self._run()

        group = Group.objects.get(name='Editors')
        codenames = set(group.permissions.values_list('codename', flat=True))
        self.assertEqual(codenames, {'view_user'})

    def test_warns_on_unknown_permission(self):
        roles = {'Editors': ['users.this_permission_does_not_exist']}
        with mock.patch('core.management.commands.seed_roles.ROLES', roles):
            _, err = self._run()

        self.assertIn('this_permission_does_not_exist', err)
        group = Group.objects.get(name='Editors')
        self.assertEqual(group.permissions.count(), 0)

    def test_warns_on_malformed_permission(self):
        roles = {'Editors': ['not-a-valid-codename']}
        with mock.patch('core.management.commands.seed_roles.ROLES', roles):
            _, err = self._run()

        self.assertIn('not-a-valid-codename', err)
