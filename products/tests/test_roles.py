from io import StringIO

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase


class ProductRolesTests(TestCase):
    def setUp(self):
        call_command('seed_roles', stdout=StringIO(), stderr=StringIO())

    def _codenames(self, role):
        return set(
            Group.objects.get(name=role).permissions.filter(content_type__app_label='products')
            .values_list('codename', flat=True)
        )

    def test_vendedor_can_only_view_catalogs(self):
        self.assertTrue(self._codenames('Vendedor'))
        self.assertTrue(all(c.startswith('view_') for c in self._codenames('Vendedor')))

    def test_administrador_has_full_catalog_access(self):
        codenames = self._codenames('Administrador')
        for model in ('category', 'brand', 'productmodel', 'color', 'size'):
            for action in ('add', 'view', 'change', 'delete'):
                self.assertIn(f'{action}_{model}', codenames)
