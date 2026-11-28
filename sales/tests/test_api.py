from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from clients.models import Client
from products.tests.test_variants import VariantFixtureMixin
from sales.models import Exchange, PaymentMethod, Sale
from sales.services import create_sale
from sales.tests.test_services import qty, user_with
from stock.models import StockMovement
from stock.services import apply_movements

D = Decimal
BASE = '/api/sales/'


class SaleApiTests(VariantFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.a = self.make()
        self.b = self.make(color=self.red)
        apply_movements([(self.a, 10), (self.b, 10)], StockMovement.INGRESO, StockMovement.COMPRA)
        self.seller = user_with('seller@test.com', 'view_sale', 'add_sale')
        self.admin = user_with('admin@test.com', 'view_sale', 'add_sale', 'void_sale', 'apply_discount')
        self.api = self.client_for(self.seller)
        self.client_obj = Client.objects.create(first_name='Ana', last_name='Paz', email='ana@test.com', origin='other')

    def client_for(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def payload(self, **kw):
        data = {'items': [{'variant': self.a.pk, 'quantity': 2}], 'payment_method': 'efectivo'}
        data.update(kw)
        return data

    def post(self, api=None, **kw):
        return (api or self.api).post(BASE, self.payload(**kw), format='json')

    def sale(self, **kw):
        return create_sale(self.seller, kw.pop('lines', [(self.a, 2)]), kw.pop('payment_method', 'efectivo'), **kw)[0]

    # --- alta ---
    def test_create_returns_detail_and_discounts_stock(self):
        r = self.post(client=self.client_obj.pk, note='regalo')
        self.assertEqual(r.status_code, 201)
        d = r.data
        self.assertEqual((d['client_name'], d['status'], d['total'], d['subtotal'], d['units'], d['items_count']),
                         ('Ana Paz', 'completada', '200.00', '200.00', 2, 1))
        self.assertEqual((d['created_by_email'], d['payment_method_display'], d['note']), ('seller@test.com', 'Efectivo', 'regalo'))
        item = d['items'][0]
        self.assertEqual((item['sku'], item['product_name'], item['unit_price'], item['exchangeable_quantity']),
                         (self.a.sku, 'Aurora', '100.00', 2))
        self.assertEqual(qty(self.a), 8)

    def test_price_in_payload_is_ignored(self):
        r = self.post(items=[{'variant': self.a.pk, 'quantity': 1, 'unit_price': '1'}])
        self.assertEqual(r.data['items'][0]['unit_price'], '100.00')

    def test_requires_permission_and_auth(self):
        self.assertEqual(APIClient().post(BASE, self.payload(), format='json').status_code, 401)
        nobody = self.client_for(user_with('n@test.com'))
        self.assertEqual(self.post(api=nobody).status_code, 403)
        self.assertEqual(nobody.get(BASE).status_code, 403)
        self.assertEqual(Sale.objects.count(), 0)

    def test_discount_only_with_permission(self):
        self.assertEqual(self.post(discount_percent=10).status_code, 403)
        self.assertEqual(Sale.objects.count(), 0)
        r = self.post(api=self.client_for(self.admin), discount_percent=10, discount_reason='frecuente')
        self.assertEqual(r.status_code, 201)
        self.assertEqual((r.data['total'], r.data['items'][0]['unit_price']), ('180.00', '90.00'))
        self.assertEqual(self.post(api=self.client_for(self.admin), discount_percent=7).status_code, 400)
        self.assertEqual(self.post(discount_percent=0).status_code, 201)

    def test_insufficient_stock_is_400_with_details(self):
        r = self.post(items=[{'variant': self.a.pk, 'quantity': 11}])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(  # los números de un 400 viajan como texto
            (str(r.data['available']), str(r.data['requested']), str(r.data['variant'])), ('10', '11', str(self.a.pk)),
        )
        self.assertEqual((Sale.objects.count(), qty(self.a)), (0, 10))

    def test_validation_errors(self):
        for data in (
            {'items': []},
            {'items': [{'variant': self.a.pk, 'quantity': 0}]},
            {'items': [{'variant': self.a.pk, 'quantity': 1}] * 2},
            {'items': [{'variant': 99999, 'quantity': 1}]},
            {'payment_method': 'cheque'},
            {'client': 99999},
        ):
            with self.subTest(data=data):
                self.assertEqual(self.post(**data).status_code, 400)
        r = self.api.post(BASE, {'items': [{'variant': self.a.pk, 'quantity': 1}]}, format='json')
        self.assertEqual(r.status_code, 400)  # falta el medio de pago
        self.assertEqual(Sale.objects.count(), 0)

    def test_idempotency_replay_is_200_and_does_not_duplicate(self):
        first = self.post(idempotency_key='abc')
        again = self.post(idempotency_key='abc')
        self.assertEqual((first.status_code, again.status_code), (201, 200))
        self.assertEqual(first.data['id'], again.data['id'])
        self.assertEqual((Sale.objects.count(), qty(self.a)), (1, 8))

    def test_payment_methods(self):
        for method in PaymentMethod.values:
            self.assertEqual(self.post(payment_method=method, items=[{'variant': self.a.pk, 'quantity': 1}]).status_code, 201)

    def test_no_update_or_delete(self):
        sale = self.sale()
        for method in ('put', 'patch', 'delete'):
            r = getattr(self.api, method)(f'{BASE}{sale.pk}/', {}, format='json')
            self.assertIn(r.status_code, (403, 405))  # nunca 2xx

    # --- consulta ---
    def test_retrieve_detail(self):
        sale = self.sale(client=self.client_obj)
        d = self.api.get(f'{BASE}{sale.pk}/').data
        self.assertEqual((len(d['items']), d['exchanges'], d['can_exchange']), (1, [], True))
        self.assertEqual(d['items'][0]['color_name'], 'Azul')

    def test_exchange_deadline_and_can_exchange(self):
        sale = self.sale()
        old = datetime.now(dt_timezone.utc) - timedelta(days=40)
        Sale.objects.filter(pk=sale.pk).update(created_at=old)
        d = self.api.get(f'{BASE}{sale.pk}/').data
        self.assertFalse(d['can_exchange'])
        self.assertLess(d['exchange_deadline'], datetime.now().date())  # el serializer devuelve la fecha
        fresh = self.api.get(f'{BASE}{self.sale().pk}/').data
        self.assertTrue(fresh['can_exchange'])

    def test_voided_sale_cannot_be_exchanged(self):
        sale = self.sale()
        self.client_for(self.admin).post(f'{BASE}{sale.pk}/void/', {'reason': 'x'}, format='json')
        self.assertFalse(self.api.get(f'{BASE}{sale.pk}/').data['can_exchange'])

    def test_detail_shows_exchange_summary(self):
        sale = self.sale()
        ex = Exchange.objects.create(sale=sale, returned_total=D('50'), new_total=D('80'), difference=D('30'), payment_method='qr')
        d = self.api.get(f'{BASE}{sale.pk}/').data
        self.assertEqual([(e['id'], e['status'], e['difference']) for e in d['exchanges']], [(ex.pk, 'completada', '30.00')])

    def test_list_rows_and_totals(self):
        self.sale(lines=[(self.a, 2), (self.b, 3)])
        row = self.api.get(BASE).data['results'][0]
        self.assertEqual((row['items_count'], row['units'], row['total']), (2, 5, '500.00'))
        self.assertNotIn('items', row)

    def test_list_is_newest_first_and_paginated(self):
        first, second = self.sale(), self.sale()
        res = self.api.get(BASE).data
        self.assertEqual([r['id'] for r in res['results']], [second.pk, first.pk])
        self.assertEqual(res['count'], 2)

    def test_filters(self):
        other = Client.objects.create(first_name='Beto', last_name='Gil', email='b@test.com', origin='other')
        s1 = self.sale(client=self.client_obj, payment_method='qr')
        s2 = create_sale(self.admin, [(self.b, 1)], 'efectivo', client=other, discount_percent=10)[0]
        s3 = self.sale()
        self.client_for(self.admin).post(f'{BASE}{s3.pk}/void/', {'reason': 'x'}, format='json')
        Exchange.objects.create(sale=s1, returned_total=D('0'), new_total=D('0'), difference=D('0'))

        def ids(query):
            return {r['id'] for r in self.api.get(f'{BASE}?{query}').data['results']}

        self.assertEqual(ids(f'client={other.pk}'), {s2.pk})
        self.assertEqual(ids('payment_method=qr'), {s1.pk})
        self.assertEqual(ids('status=anulada'), {s3.pk})
        self.assertEqual(ids(f'created_by={self.admin.pk}'), {s2.pk})
        self.assertEqual(ids(f'variant={self.b.pk}'), {s2.pk})
        self.assertEqual(ids(f'product={self.product.pk}'), {s1.pk, s2.pk, s3.pk})
        self.assertEqual(ids('has_discount=true'), {s2.pk})
        self.assertEqual(ids('has_discount=false'), {s1.pk, s3.pk})
        self.assertEqual(ids('has_exchanges=true'), {s1.pk})
        self.assertEqual(ids('has_exchanges=false'), {s2.pk, s3.pk})
        self.assertEqual(ids('min_total=150'), {s1.pk, s3.pk})
        self.assertEqual(ids('max_total=150'), {s2.pk})
        self.assertEqual(ids('date_from=2999-01-01'), set())
        self.assertEqual(ids(f'date_from={datetime.now().date()}&date_to={datetime.now().date()}'), {s1.pk, s2.pk, s3.pk})

    def test_voided_exchange_does_not_count_as_has_exchanges(self):
        sale = self.sale()
        Exchange.objects.create(sale=sale, returned_total=D('0'), new_total=D('0'), difference=D('0'), status='anulada')
        self.assertEqual(self.api.get(f'{BASE}?has_exchanges=true').data['count'], 0)

    def test_search_by_client_sku_and_note_without_duplicates(self):
        s1 = self.sale(client=self.client_obj, note='vidriera', lines=[(self.a, 1), (self.b, 1)])
        self.sale(lines=[(self.b, 1)])

        def search(term):
            res = self.api.get(f'{BASE}?search={term}').data
            return [r['id'] for r in res['results']], res['results']

        self.assertEqual(search('ana')[0], [s1.pk])
        self.assertEqual(search('vidriera')[0], [s1.pk])
        ids, rows = search(self.a.sku)
        self.assertEqual(ids, [s1.pk])
        self.assertEqual((rows[0]['items_count'], rows[0]['units']), (2, 2))  # el buscador no multiplica los totales
        self.assertEqual(len(search(self.b.sku)[0]), 2)

    def test_ordering_by_total(self):
        cheap, dear = self.sale(lines=[(self.a, 1)]), self.sale(lines=[(self.a, 5)])
        res = self.api.get(f'{BASE}?ordering=-total').data['results']
        self.assertEqual([r['id'] for r in res], [dear.pk, cheap.pk])

    def test_deleted_client_still_shows_name(self):
        sale = self.sale(client=self.client_obj)
        self.client_obj.delete()
        self.assertEqual(self.api.get(f'{BASE}{sale.pk}/').data['client_name'], 'Ana Paz')

    def test_list_query_count_is_constant(self):
        self.sale(client=self.client_obj)
        self.api.get(BASE)  # calienta el caché de permisos del usuario
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as few:
            self.api.get(BASE)
        for _ in range(4):
            self.sale(client=self.client_obj)
        with CaptureQueriesContext(connection) as many:
            self.api.get(BASE)
        self.assertEqual(len(few), len(many))

    # --- anulación ---
    def test_void_returns_stock_and_requires_reason_and_permission(self):
        sale = self.sale()
        url = f'{BASE}{sale.pk}/void/'
        self.assertEqual(self.api.post(url, {'reason': 'x'}, format='json').status_code, 403)  # el vendedor no anula
        admin = self.client_for(self.admin)
        self.assertEqual(admin.post(url, {}, format='json').status_code, 400)
        self.assertEqual(admin.post(url, {'reason': '  '}, format='json').status_code, 400)
        self.assertEqual(qty(self.a), 8)
        r = admin.post(url, {'reason': 'Se cargó mal'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['status'], r.data['void_reason'], r.data['voided_by_email']), ('anulada', 'Se cargó mal', 'admin@test.com'))
        self.assertEqual(qty(self.a), 10)
        self.assertEqual(admin.post(url, {'reason': 'otra vez'}, format='json').status_code, 400)

    def test_void_blocked_by_active_exchange(self):
        sale = self.sale()
        Exchange.objects.create(sale=sale, returned_total=D('0'), new_total=D('0'), difference=D('0'))
        r = self.client_for(self.admin).post(f'{BASE}{sale.pk}/void/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(qty(self.a), 8)

    def test_stock_history_links_to_the_sale(self):
        sale = self.sale()
        stock_viewer = self.client_for(user_with('s@test.com', 'view_stockmovement'))
        rows = stock_viewer.get(f'/api/stock-operations/?sale={sale.pk}').data['results']
        self.assertEqual([(r['reason'], r['sale']) for r in rows], [('venta', sale.pk)])
