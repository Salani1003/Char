from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from clients.models import Client
from clients.services import ClientService
from users.models import User


class ClientServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(email='client-admin@example.com', password='pass12345')

    def _payload(self, **overrides):
        data = {
            'first_name': 'Ada',
            'last_name': 'Lovelace',
            'phone': '123456789',
            'email': 'ada@example.com',
            'origin': Client.Origin.INSTAGRAM,
        }
        data.update(overrides)
        return data

    def test_creates_client_when_email_does_not_exist(self):
        client = ClientService.create_client(self._payload(), user=self.user)

        self.assertIsNotNone(client.pk)
        self.assertEqual(client.email, 'ada@example.com')
        self.assertFalse(client.is_deleted)

    def test_creates_client_when_no_email_provided(self):
        payload = self._payload()
        payload.pop('email')

        client = ClientService.create_client(payload, user=self.user)

        self.assertIsNotNone(client.pk)
        self.assertIsNone(client.email)

    def test_rejects_email_belonging_to_active_client(self):
        Client.objects.create(**self._payload())

        with self.assertRaises(ValidationError):
            ClientService.create_client(self._payload(first_name='Grace'), user=self.user)

    def test_restores_deleted_client_when_email_provided(self):
        existing = Client.objects.create(**self._payload())
        existing.delete(self.user)

        restored = ClientService.create_client(self._payload(), user=self.user)

        restored.refresh_from_db()
        self.assertFalse(restored.is_deleted)

    def test_restoring_updates_client_fields(self):
        existing = Client.objects.create(**self._payload())
        existing.delete(self.user)

        new_data = self._payload(
            first_name='Grace',
            last_name='Hopper',
            phone='987654321',
            email='ada@example.com',
            origin=Client.Origin.GOOGLE,
        )

        restored = ClientService.create_client(new_data, user=self.user)

        self.assertEqual(restored.first_name, 'Grace')
        self.assertEqual(restored.last_name, 'Hopper')
        self.assertEqual(restored.phone, '987654321')
        self.assertEqual(restored.email, 'ada@example.com')
        self.assertEqual(restored.origin, Client.Origin.GOOGLE)

    def test_restored_client_keeps_same_id(self):
        existing = Client.objects.create(**self._payload())
        existing.delete(self.user)

        restored = ClientService.create_client(self._payload(), user=self.user)

        self.assertEqual(restored.id, existing.id)

    def test_restored_client_is_active(self):
        existing = Client.objects.create(**self._payload())
        existing.delete(self.user)

        restored = ClientService.create_client(self._payload(), user=self.user)

        self.assertFalse(restored.is_deleted)
        self.assertTrue(Client.objects.filter(pk=restored.pk).exists())

    def test_restoring_performs_single_update_query(self):
        existing = Client.objects.create(**self._payload())
        existing.delete(self.user)

        new_data = self._payload(
            first_name='Grace',
            last_name='Hopper',
            phone='987654321',
            email='ada@example.com',
            origin=Client.Origin.GOOGLE,
        )

        with CaptureQueriesContext(connection) as captured:
            restored = ClientService.create_client(new_data, user=self.user)

        update_queries = [q for q in captured.captured_queries if q['sql'].strip().upper().startswith('UPDATE')]
        self.assertEqual(len(update_queries), 1)
        self.assertFalse(restored.is_deleted)

    def test_restoring_does_not_create_second_record(self):
        existing = Client.objects.create(**self._payload())
        existing.delete(self.user)

        ClientService.create_client(self._payload(), user=self.user)

        self.assertEqual(Client.all_objects.filter(email='ada@example.com').count(), 1)
