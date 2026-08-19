from django.test import TestCase

from clients.models import Client
from clients.serializers import ClientSerializer


class ClientSerializerTests(TestCase):
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

    def test_serializes_existing_client(self):
        client = self._build(email='ada@example.com')

        data = ClientSerializer(client).data

        self.assertEqual(data['id'], client.id)
        self.assertEqual(data['first_name'], 'Ada')
        self.assertEqual(data['last_name'], 'Lovelace')
        self.assertEqual(data['phone'], client.phone)
        self.assertEqual(data['email'], 'ada@example.com')
        self.assertEqual(data['origin'], Client.Origin.INSTAGRAM)
        self.assertIn('created_at', data)

    def test_only_defined_fields_are_exposed(self):
        client = self._build()

        data = ClientSerializer(client).data

        self.assertEqual(
            set(data.keys()),
            {'id', 'first_name', 'last_name', 'phone', 'email', 'origin', 'created_at'},
        )

    def test_id_is_present_but_read_only(self):
        client = self._build()

        serializer = ClientSerializer(client, data=self._valid_payload(id=9999), partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()

        self.assertEqual(updated.id, client.id)

    def test_created_at_is_present_but_read_only(self):
        client = self._build()
        original_created_at = client.created_at

        serializer = ClientSerializer(
            client,
            data=self._valid_payload(created_at='2000-01-01T00:00:00Z'),
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()

        self.assertEqual(updated.created_at, original_created_at)

    def test_valid_payload_creates_client(self):
        serializer = ClientSerializer(data=self._valid_payload())
        serializer.is_valid(raise_exception=True)
        client = serializer.save()

        self.assertEqual(client.first_name, 'Ada')
        self.assertEqual(client.last_name, 'Lovelace')
        self.assertEqual(client.email, 'ada@example.com')

    def test_first_name_is_required(self):
        payload = self._valid_payload()
        payload.pop('first_name')

        serializer = ClientSerializer(data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn('first_name', serializer.errors)

    def test_last_name_is_required(self):
        payload = self._valid_payload()
        payload.pop('last_name')

        serializer = ClientSerializer(data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn('last_name', serializer.errors)

    def test_phone_is_optional(self):
        payload = self._valid_payload()
        payload.pop('phone')

        serializer = ClientSerializer(data=payload)

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_email_is_optional(self):
        payload = self._valid_payload()
        payload.pop('email')

        serializer = ClientSerializer(data=payload)

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_origin_rejects_invalid_choice(self):
        payload = self._valid_payload(origin='not-a-real-origin')

        serializer = ClientSerializer(data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn('origin', serializer.errors)

    def test_email_rejects_invalid_format(self):
        payload = self._valid_payload(email='not-an-email')

        serializer = ClientSerializer(data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn('email', serializer.errors)

    def test_email_must_be_unique(self):
        self._build(email='dup@example.com')
        payload = self._valid_payload(email='dup@example.com')

        serializer = ClientSerializer(data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn('email', serializer.errors)

    def test_partial_update_client(self):
        client = self._build(phone='123456789', email='ada@example.com')

        serializer = ClientSerializer(client, data={'phone': '987654321'}, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()

        self.assertEqual(updated.phone, '987654321')
        self.assertEqual(updated.first_name, 'Ada')
        self.assertEqual(updated.last_name, 'Lovelace')
        self.assertEqual(updated.email, 'ada@example.com')
        self.assertEqual(updated.origin, Client.Origin.INSTAGRAM)
