from django.test import TestCase
from rest_framework.test import APIClient

from products.models import Categoria
from users.models import User


class CategoriaViewSetOrderingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_superuser(email='root@example.com', password='pass12345'))

    def test_list_is_ordered_by_nombre_by_default(self):
        Categoria.objects.create(nombre='Remeras')
        Categoria.objects.create(nombre='Buzos')
        Categoria.objects.create(nombre='Pantalones')

        response = self.client.get('/api/categorias/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['nombre'] for row in response.data['results']], ['Buzos', 'Pantalones', 'Remeras'])
