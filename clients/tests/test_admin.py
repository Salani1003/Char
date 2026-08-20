from django.test import TestCase

from clients.admin import ClientAdmin
from clients.models import Client
from django.contrib.admin.sites import AdminSite
from users.models import User


class ClientAdminTests(TestCase):
    """
    El admin de Client debe operar sobre `all_objects` (no el manager
    `objects`, que excluye soft-deleted) para que el staff pueda ver y
    auditar también los clientes borrados.
    """

    def setUp(self):
        self.admin = ClientAdmin(Client, AdminSite())
        self.user = User.objects.create_superuser(email='admin@example.com', password='pass12345')

    def _build(self, **overrides):
        data = {
            'first_name': 'Ada',
            'last_name': 'Lovelace',
            'origin': Client.Origin.INSTAGRAM,
        }
        data.update(overrides)
        return Client.objects.create(**data)

    def test_queryset_includes_soft_deleted_clients(self):
        client = self._build(email='ada@example.com')
        client.delete(self.user)

        queryset = self.admin.get_queryset(request=None)

        self.assertIn(client, queryset)

    def test_queryset_includes_active_clients(self):
        client = self._build(email='ada@example.com')

        queryset = self.admin.get_queryset(request=None)

        self.assertIn(client, queryset)
