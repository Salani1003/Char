from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from clients.models import Client


class ClientModelTests(TestCase):
    """
    Prueba mínima del modelo Client: campos obligatorios, campos opcionales,
    choices de origin, almacenamiento de un email válido y unicidad de
    email entre clientes activos.
    """

    def _build(self, **overrides):
        data = {
            'first_name': 'Ada',
            'last_name': 'Lovelace',
            'origin': Client.Origin.INSTAGRAM,
        }
        data.update(overrides)
        return Client(**data)

    def test_first_name_is_required(self):
        client = self._build(first_name='')

        with self.assertRaises(ValidationError):
            client.full_clean()

    def test_last_name_is_required(self):
        client = self._build(last_name='')

        with self.assertRaises(ValidationError):
            client.full_clean()

    def test_origin_is_required(self):
        client = self._build(origin='')

        with self.assertRaises(ValidationError):
            client.full_clean()

    def test_phone_can_be_null(self):
        client = self._build(phone=None)
        client.full_clean()
        client.save()

        self.assertIsNone(client.phone)

    def test_email_can_be_null(self):
        client = self._build(email=None)
        client.full_clean()
        client.save()

        self.assertIsNone(client.email)

    def test_origin_accepts_defined_choices(self):
        for value, _ in Client.Origin.choices:
            client = self._build(origin=value)
            client.full_clean()

    def test_origin_rejects_value_outside_choices(self):
        client = self._build(origin='not-a-real-origin')

        with self.assertRaises(ValidationError):
            client.full_clean()

    def test_valid_email_can_be_stored(self):
        client = self._build(email='ada@example.com')
        client.full_clean()
        client.save()

        client.refresh_from_db()
        self.assertEqual(client.email, 'ada@example.com')

    def test_two_active_clients_cannot_share_email(self):
        self._build(email='dup@example.com').save()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._build(first_name='Grace', email='dup@example.com').save()
