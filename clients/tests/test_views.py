from django.test import TestCase
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

    def _list(self):
        request = self.factory.get('/clients/')
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
