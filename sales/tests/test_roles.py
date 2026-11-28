from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from products.tests.test_variants import VariantFixtureMixin
from sales.services import create_sale
from stock.models import StockMovement
from stock.services import apply_movements
from users.models import User

D = Decimal


class SalesRolesTests(VariantFixtureMixin, TestCase):
    """Con los roles reales (`seed_roles`): el Vendedor vende y cambia; el Administrador además anula y da descuento."""

    def setUp(self):
        super().setUp()
        call_command('seed_roles', stdout=StringIO(), stderr=StringIO())
        self.a = self.make()
        self.dear = self.make(color=self.red)
        apply_movements([(self.a, 10), (self.dear, 10)], StockMovement.INGRESO, StockMovement.COMPRA)
        self.seller_api = self.api('Vendedor')
        self.admin_api = self.api('Administrador')

    def api(self, role):
        user = User.objects.create_user(email=f'{role.lower()}@test.com', password='x')
        user.groups.add(Group.objects.get(name=role))
        client = APIClient()
        client.force_authenticate(User.objects.get(pk=user.pk))
        return client

    def sale_payload(self, **kw):
        return {'items': [{'variant': self.a.pk, 'quantity': 2}], 'payment_method': 'efectivo', **kw}

    def test_seller_sells_and_exchanges(self):
        r = self.seller_api.post('/api/sales/', self.sale_payload(), format='json')
        self.assertEqual(r.status_code, 201)
        sale = r.data
        self.assertEqual(self.seller_api.get('/api/sales/').status_code, 200)
        exchange = {
            'sale': sale['id'], 'returned_items': [{'sale_item': sale['items'][0]['id'], 'quantity': 1}],
            'new_items': [{'variant': self.dear.pk, 'quantity': 1}],
        }
        self.assertEqual(self.seller_api.post('/api/exchanges/preview/', exchange, format='json').status_code, 200)
        self.assertEqual(self.seller_api.post('/api/exchanges/', {**exchange, 'new_items': []}, format='json').status_code, 201)
        self.assertEqual(self.seller_api.get('/api/exchanges/').status_code, 200)

    def test_seller_cannot_discount_or_void(self):
        self.assertEqual(self.seller_api.post('/api/sales/', self.sale_payload(discount_percent=10), format='json').status_code, 403)
        sale, _ = create_sale(User.objects.first(), [(self.a, 1)], 'efectivo')
        self.assertEqual(self.seller_api.post(f'/api/sales/{sale.pk}/void/', {'reason': 'x'}, format='json').status_code, 403)

    def test_seller_cannot_void_an_exchange(self):
        sale = self.seller_api.post('/api/sales/', self.sale_payload(), format='json').data
        exchange = self.seller_api.post('/api/exchanges/', {
            'sale': sale['id'], 'returned_items': [{'sale_item': sale['items'][0]['id'], 'quantity': 1}],
        }, format='json').data
        self.assertEqual(self.seller_api.post(f'/api/exchanges/{exchange["id"]}/void/', {'reason': 'x'}, format='json').status_code, 403)

    def test_administrator_does_everything(self):
        sale = self.admin_api.post('/api/sales/', self.sale_payload(discount_percent=10), format='json')
        self.assertEqual((sale.status_code, sale.data['total']), (201, '180.00'))
        exchange = self.admin_api.post('/api/exchanges/', {
            'sale': sale.data['id'], 'returned_items': [{'sale_item': sale.data['items'][0]['id'], 'quantity': 1}],
        }, format='json')
        self.assertEqual(exchange.status_code, 201)
        self.assertEqual(self.admin_api.post(f'/api/exchanges/{exchange.data["id"]}/void/', {'reason': 'x'}, format='json').status_code, 200)
        self.assertEqual(self.admin_api.post(f'/api/sales/{sale.data["id"]}/void/', {'reason': 'x'}, format='json').status_code, 200)
