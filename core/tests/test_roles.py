from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase


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
