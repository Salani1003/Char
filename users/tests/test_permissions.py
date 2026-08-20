from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from users.models import User
from users.views import UserViewSet


class UserViewSetPermissionsTests(TestCase):
    """
    Verifica que UserViewSet queda gobernado por el sistema nativo de
    Groups/Permissions de Django (vía DjangoObjectPermissionsWithView),
    igual que cualquier otro BaseModelViewSet: cada método HTTP requiere
    el permiso Django correspondiente sobre el modelo User.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(email='member@example.com', password='pass12345')
        self.content_type = ContentType.objects.get_for_model(User)

    def _grant(self, *codenames):
        group, _ = Group.objects.get_or_create(name='has_' + '_'.join(codenames))
        for codename in codenames:
            permission = Permission.objects.get(content_type=self.content_type, codename=codename)
            group.permissions.add(permission)
        self.user.groups.add(group)

    def _valid_payload(self, **overrides):
        data = {
            'email': 'new-user@example.com',
            'password': 'pass12345',
            'first_name': 'Ada',
            'last_name': 'Lovelace',
        }
        data.update(overrides)
        return data

    def test_list_denied_without_view_permission(self):
        request = self.factory.get('/users/')
        force_authenticate(request, user=self.user)
        response = UserViewSet.as_view({'get': 'list'})(request)
        self.assertEqual(response.status_code, 403)

    def test_list_allowed_with_view_permission(self):
        self._grant('view_user')
        request = self.factory.get('/users/')
        force_authenticate(request, user=self.user)
        response = UserViewSet.as_view({'get': 'list'})(request)
        self.assertEqual(response.status_code, 200)

    def test_create_denied_without_add_permission(self):
        request = self.factory.post('/users/', self._valid_payload(), format='json')
        force_authenticate(request, user=self.user)
        response = UserViewSet.as_view({'post': 'create'})(request)
        self.assertEqual(response.status_code, 403)

    def test_create_allowed_with_add_permission(self):
        self._grant('add_user')
        request = self.factory.post('/users/', self._valid_payload(), format='json')
        force_authenticate(request, user=self.user)
        response = UserViewSet.as_view({'post': 'create'})(request)
        self.assertEqual(response.status_code, 201)

    def test_update_denied_without_change_permission(self):
        other = User.objects.create_user(email='other@example.com', password='pass12345')
        request = self.factory.patch(f'/users/{other.pk}/', {'first_name': 'Grace'}, format='json')
        force_authenticate(request, user=self.user)
        response = UserViewSet.as_view({'patch': 'partial_update'})(request, pk=other.pk)
        self.assertEqual(response.status_code, 403)

    def test_update_allowed_with_change_permission(self):
        other = User.objects.create_user(email='other@example.com', password='pass12345')
        self._grant('change_user')
        request = self.factory.patch(f'/users/{other.pk}/', {'first_name': 'Grace'}, format='json')
        force_authenticate(request, user=self.user)
        response = UserViewSet.as_view({'patch': 'partial_update'})(request, pk=other.pk)
        self.assertEqual(response.status_code, 200)

    def test_destroy_denied_without_delete_permission(self):
        other = User.objects.create_user(email='other@example.com', password='pass12345')
        request = self.factory.delete(f'/users/{other.pk}/')
        force_authenticate(request, user=self.user)
        response = UserViewSet.as_view({'delete': 'destroy'})(request, pk=other.pk)
        self.assertEqual(response.status_code, 403)

    def test_destroy_allowed_with_delete_permission(self):
        other = User.objects.create_user(email='other@example.com', password='pass12345')
        self._grant('delete_user')
        request = self.factory.delete(f'/users/{other.pk}/')
        force_authenticate(request, user=self.user)
        response = UserViewSet.as_view({'delete': 'destroy'})(request, pk=other.pk)
        self.assertEqual(response.status_code, 204)

    def test_unauthenticated_request_denied(self):
        request = self.factory.get('/users/')
        response = UserViewSet.as_view({'get': 'list'})(request)
        self.assertEqual(response.status_code, 401)

    def test_administrator_role_permissions_grant_full_crud(self):
        """
        El rol "Administrator" definido en core.roles.ROLES tiene
        add/view/change/delete sobre User: confirma que ese diseño de
        permisos efectivamente habilita el borrado (desactivación) a
        nivel de endpoint.
        """
        self._grant('add_user', 'view_user', 'change_user', 'delete_user')
        other = User.objects.create_user(email='other@example.com', password='pass12345')

        request = self.factory.delete(f'/users/{other.pk}/')
        force_authenticate(request, user=self.user)
        response = UserViewSet.as_view({'delete': 'destroy'})(request, pk=other.pk)

        self.assertEqual(response.status_code, 204)
