from unittest import mock

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory, force_authenticate

from clients.models import Client
from clients.views import ClientViewSet
from users.models import User


class ClientViewSetTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_superuser(email='client-admin@example.com', password='pass12345')

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

    def _list(self, query_params=None):
        request = self.factory.get('/clients/', query_params or {})
        force_authenticate(request, user=self.user)
        return ClientViewSet.as_view({'get': 'list'})(request)

    def _retrieve(self, pk):
        request = self.factory.get(f'/clients/{pk}/')
        force_authenticate(request, user=self.user)
        return ClientViewSet.as_view({'get': 'retrieve'})(request, pk=pk)

    def _create(self, payload):
        request = self.factory.post('/clients/', payload, format='json')
        force_authenticate(request, user=self.user)
        return ClientViewSet.as_view({'post': 'create'})(request)

    def _update(self, pk, payload):
        request = self.factory.put(f'/clients/{pk}/', payload, format='json')
        force_authenticate(request, user=self.user)
        return ClientViewSet.as_view({'put': 'update'})(request, pk=pk)

    def _destroy(self, pk):
        request = self.factory.delete(f'/clients/{pk}/')
        force_authenticate(request, user=self.user)
        return ClientViewSet.as_view({'delete': 'destroy'})(request, pk=pk)

    def test_list_returns_active_clients(self):
        self._build(email='ada@example.com')
        self._build(first_name='Grace', last_name='Hopper', email='grace@example.com')

        response = self._list()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)

    def test_list_excludes_deleted_clients(self):
        client = self._build(email='ada@example.com')
        client.delete(self.user)

        response = self._list()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 0)

    def test_retrieve_returns_active_client(self):
        client = self._build(email='ada@example.com')

        response = self._retrieve(client.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], client.id)

    def test_retrieve_does_not_return_deleted_client(self):
        client = self._build(email='ada@example.com')
        client.delete(self.user)

        response = self._retrieve(client.pk)

        self.assertEqual(response.status_code, 404)

    def test_create_creates_client(self):
        response = self._create(self._valid_payload())

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Client.objects.filter(email='ada@example.com').exists())

    def test_create_assigns_created_by_from_request_user(self):
        response = self._create(self._valid_payload())

        client = Client.objects.get(pk=response.data['id'])
        self.assertEqual(client.created_by, self.user)

    def test_update_updates_client(self):
        client = self._build(email='ada@example.com')

        response = self._update(client.pk, self._valid_payload(phone='987654321'))

        self.assertEqual(response.status_code, 200)
        client.refresh_from_db()
        self.assertEqual(client.phone, '987654321')

    def test_update_assigns_updated_by_from_request_user(self):
        client = self._build(email='ada@example.com')

        self._update(client.pk, self._valid_payload(phone='987654321'))

        client.refresh_from_db()
        self.assertEqual(client.updated_by, self.user)

    def test_destroy_soft_deletes_client(self):
        client = self._build(email='ada@example.com')

        response = self._destroy(client.pk)

        self.assertEqual(response.status_code, 204)
        client.refresh_from_db()
        self.assertTrue(client.is_deleted)

    def test_destroy_assigns_deleted_by_from_request_user(self):
        client = self._build(email='ada@example.com')

        self._destroy(client.pk)

        client.refresh_from_db()
        self.assertEqual(client.deleted_by, self.user)

    def test_destroy_keeps_record_visible_via_all_objects(self):
        client = self._build(email='ada@example.com')

        self._destroy(client.pk)

        self.assertTrue(Client.all_objects.filter(pk=client.pk).exists())

    def test_create_restores_soft_deleted_client_with_same_email(self):
        existing = self._build(email='ada@example.com')
        existing.delete(self.user)

        response = self._create(self._valid_payload(first_name='Grace', last_name='Hopper'))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['id'], existing.id)
        existing.refresh_from_db()
        self.assertFalse(existing.is_deleted)
        self.assertEqual(existing.first_name, 'Grace')
        self.assertEqual(Client.all_objects.filter(email='ada@example.com').count(), 1)

    def test_list_search_matches_first_name_last_name_or_email(self):
        self._build(email='ada@example.com')
        self._build(first_name='Grace', last_name='Hopper', email='grace@example.com')

        response = self._list({'search': 'grace'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['email'], 'grace@example.com')

    def test_list_orders_by_first_name_ascending(self):
        self._build(first_name='Grace', last_name='Hopper', email='grace@example.com')
        self._build(first_name='Ada', last_name='Lovelace', email='ada@example.com')

        response = self._list({'ordering': 'first_name'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['first_name'] for row in response.data], ['Ada', 'Grace'])

    def test_list_orders_by_created_at_descending_by_default(self):
        first = self._build(first_name='Ada', last_name='Lovelace', email='ada@example.com')
        second = self._build(first_name='Grace', last_name='Hopper', email='grace@example.com')

        response = self._list()

        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in response.data], [second.id, first.id])

    def test_update_with_email_of_soft_deleted_client_returns_400_not_500(self):
        deleted = self._build(email='deleted@example.com')
        deleted.delete(self.user)
        client = self._build(email='ada@example.com')

        response = self._update(client.pk, self._valid_payload(email='deleted@example.com'))

        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.data)

    def test_create_translates_service_validation_error_into_drf_validation_error(self):
        """
        `ClientService.create_client` puede levantar `DjangoValidationError`
        (ej. bajo una condición de carrera que el validator de unicidad del
        serializer no llegó a atajar). `ClientViewSet.perform_create` debe
        traducir eso a un `rest_framework.exceptions.ValidationError`, que
        DRF sabe convertir en una respuesta 400 en vez de un 500.
        """
        request = self.factory.post('/clients/', {}, format='json')
        request.user = self.user
        view = ClientViewSet()
        view.request = request
        serializer = mock.Mock(validated_data=self._valid_payload())

        with mock.patch(
            'clients.views.ClientService.create_client',
            side_effect=DjangoValidationError('Ya existe un cliente con este email.'),
        ):
            with self.assertRaises(ValidationError):
                view.perform_create(serializer)
