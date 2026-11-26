from django.contrib.auth.models import Group
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from users.models import User


class GroupNamesTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.gestor = Group.objects.create(name='Grupo A')
        self.consulta = Group.objects.create(name='Grupo B')

    def login(self, user):
        self.client.force_authenticate(user)

    def test_me_returns_the_group_names_without_needing_view_group(self):
        user = User.objects.create_user(email='g@example.com', password='pass12345')
        user.groups.set([self.gestor, self.consulta])
        self.login(user)
        response = self.client.get('/api/users/me/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['group_names'], ['Grupo A', 'Grupo B'])
        # `/groups/` sigue protegido: el usuario no lo necesita para conocer su rol.
        self.assertEqual(self.client.get('/api/groups/').status_code, 403)

    def test_me_without_groups_returns_an_empty_list(self):
        self.login(User.objects.create_user(email='s@example.com', password='pass12345'))
        self.assertEqual(self.client.get('/api/users/me/').data['group_names'], [])

    def test_me_returns_effective_permissions_from_groups(self):
        from django.contrib.auth.models import Permission
        self.gestor.permissions.set(Permission.objects.filter(
            content_type__app_label='clients', codename__in=['view_client', 'add_client']))
        user = User.objects.create_user(email='p@example.com', password='pass12345')
        user.groups.set([self.gestor])
        self.login(user)
        self.assertEqual(
            self.client.get('/api/users/me/').data['permissions'],
            ['clients.add_client', 'clients.view_client'],
        )

    def test_me_without_permissions_returns_empty_list(self):
        self.login(User.objects.create_user(email='n@example.com', password='pass12345'))
        self.assertEqual(self.client.get('/api/users/me/').data['permissions'], [])

    def test_users_list_does_not_include_permissions(self):
        admin = User.objects.create_superuser(email='a@example.com', password='pass12345')
        self.login(admin)
        self.assertNotIn('permissions', self.client.get('/api/users/').data['results'][0])

    def test_group_ids_are_still_returned(self):
        user = User.objects.create_user(email='g@example.com', password='pass12345')
        user.groups.set([self.gestor])
        self.login(user)
        self.assertEqual(self.client.get('/api/users/me/').data['groups'], [self.gestor.pk])

    def test_group_names_are_read_only(self):
        admin = User.objects.create_superuser(email='a@example.com', password='pass12345')
        self.login(admin)
        response = self.client.patch(
            f'/api/users/{admin.pk}/', {'group_names': ['Administrador']}, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['group_names'], [])
        self.assertFalse(admin.groups.exists())

    def test_user_list_does_not_query_groups_per_user(self):
        admin = User.objects.create_superuser(email='a@example.com', password='pass12345')
        for i in range(5):
            user = User.objects.create_user(email=f'u{i}@example.com', password='pass12345')
            user.groups.set([self.gestor])
        self.login(admin)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/api/users/')
        self.assertEqual(response.status_code, 200)
        group_queries = [q for q in queries if 'auth_group' in q['sql'] and 'users_user_groups' in q['sql']]
        self.assertLessEqual(len(group_queries), 1)
