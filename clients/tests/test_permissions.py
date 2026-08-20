from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from clients.models import Client
from clients.views import ClientViewSet
from users.models import User


class ClientViewSetPermissionsTests(TestCase):
    """
    Verifica que ClientViewSet queda gobernado por el sistema nativo de
    Groups/Permissions de Django (vía DjangoObjectPermissionsWithView),
    sin lógica de permisos propia: cada método HTTP requiere el permiso
    Django correspondiente sobre el modelo Client.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(email='member@example.com', password='pass12345')
        self.content_type = ContentType.objects.get_for_model(Client)

    def _grant(self, *codenames):
        group, _ = Group.objects.get_or_create(name='has_' + '_'.join(codenames))
        for codename in codenames:
            permission = Permission.objects.get(content_type=self.content_type, codename=codename)
            group.permissions.add(permission)
        self.user.groups.add(group)

    def _build(self, **overrides):
        data = {
            'first_name': 'Ada',
            'last_name': 'Lovelace',
            'origin': Client.Origin.INSTAGRAM,
        }
        data.update(overrides)
        return Client.objects.create(**data)

    def _valid_payload(self, **overrides):
        data = {
            'first_name': 'Ada',
            'last_name': 'Lovelace',
            'phone': '123456789',
            'email': 'ada@example.com',
            'origin': Client.Origin.INSTAGRAM,
        }
        data.update(overrides)
        return data

    def test_list_denied_without_view_permission(self):
        request = self.factory.get('/clients/')
        force_authenticate(request, user=self.user)
        response = ClientViewSet.as_view({'get': 'list'})(request)
        self.assertEqual(response.status_code, 403)

    def test_list_allowed_with_view_permission(self):
        self._grant('view_client')
        request = self.factory.get('/clients/')
        force_authenticate(request, user=self.user)
        response = ClientViewSet.as_view({'get': 'list'})(request)
        self.assertEqual(response.status_code, 200)

    def test_create_denied_without_add_permission(self):
        request = self.factory.post('/clients/', self._valid_payload(), format='json')
        force_authenticate(request, user=self.user)
        response = ClientViewSet.as_view({'post': 'create'})(request)
        self.assertEqual(response.status_code, 403)

    def test_create_allowed_with_add_permission(self):
        self._grant('add_client')
        request = self.factory.post('/clients/', self._valid_payload(), format='json')
        force_authenticate(request, user=self.user)
        response = ClientViewSet.as_view({'post': 'create'})(request)
        self.assertEqual(response.status_code, 201)

    def test_update_denied_without_change_permission(self):
        client = self._build(email='ada@example.com')
        request = self.factory.put(f'/clients/{client.pk}/', self._valid_payload(), format='json')
        force_authenticate(request, user=self.user)
        response = ClientViewSet.as_view({'put': 'update'})(request, pk=client.pk)
        self.assertEqual(response.status_code, 403)

    def test_update_allowed_with_change_permission(self):
        client = self._build(email='ada@example.com')
        self._grant('change_client')
        request = self.factory.put(
            f'/clients/{client.pk}/', self._valid_payload(phone='987654321'), format='json'
        )
        force_authenticate(request, user=self.user)
        response = ClientViewSet.as_view({'put': 'update'})(request, pk=client.pk)
        self.assertEqual(response.status_code, 200)

    def test_destroy_denied_without_delete_permission(self):
        client = self._build(email='ada@example.com')
        request = self.factory.delete(f'/clients/{client.pk}/')
        force_authenticate(request, user=self.user)
        response = ClientViewSet.as_view({'delete': 'destroy'})(request, pk=client.pk)
        self.assertEqual(response.status_code, 403)

    def test_destroy_allowed_with_delete_permission(self):
        client = self._build(email='ada@example.com')
        self._grant('delete_client')
        request = self.factory.delete(f'/clients/{client.pk}/')
        force_authenticate(request, user=self.user)
        response = ClientViewSet.as_view({'delete': 'destroy'})(request, pk=client.pk)
        self.assertEqual(response.status_code, 204)

    def test_unauthenticated_request_denied(self):
        request = self.factory.get('/clients/')
        response = ClientViewSet.as_view({'get': 'list'})(request)
        self.assertEqual(response.status_code, 401)

    def test_vendedor_role_permissions_grant_crud_but_not_delete(self):
        """
        El rol "Vendedor" definido en core.roles.ROLES tiene add/view/change
        pero no delete sobre Client: confirma que ese diseño de permisos
        efectivamente restringe el borrado a nivel de endpoint.
        """
        self._grant('add_client', 'view_client', 'change_client')
        client = self._build(email='ada@example.com')

        request = self.factory.delete(f'/clients/{client.pk}/')
        force_authenticate(request, user=self.user)
        response = ClientViewSet.as_view({'delete': 'destroy'})(request, pk=client.pk)

        self.assertEqual(response.status_code, 403)
