from datetime import datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from sales.models import Exchange, Sale
from sales.services import create_exchange, create_sale
from sales.tests.test_exchange_services import ExchangeFixtureMixin
from sales.tests.test_services import qty, user_with

D = Decimal
BASE = '/api/exchanges/'
SALES = '/api/sales/'


class ExchangeApiTests(ExchangeFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.clerk = user_with('clerk@test.com', 'view_exchange', 'add_exchange', 'view_sale')
        self.boss = user_with('boss@test.com', 'view_exchange', 'add_exchange', 'void_exchange', 'view_sale', 'void_sale')
        self.api = self.api_for(self.clerk)

    def api_for(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def payload(self, **kw):
        data = {
            'sale': self.sale.pk,
            'returned_items': [{'sale_item': self.item(self.a).pk, 'quantity': 1}],
            'new_items': [{'variant': self.dear.pk, 'quantity': 1}],
            'payment_method': 'qr',
        }
        data.update(kw)
        return data

    def post(self, api=None, **kw):
        return (api or self.api).post(BASE, self.payload(**kw), format='json')

    def do_exchange(self, **kw):
        kw.setdefault('payment_method', 'efectivo')
        return self.exchange(**kw)

    # --- alta ---
    def test_create_returns_detail_with_both_sides(self):
        r = self.post(note='talle')
        self.assertEqual(r.status_code, 201)
        d = r.data
        self.assertEqual((d['status'], d['returned_total'], d['new_total'], d['difference'], d['unreturned_amount']),
                         ('completada', '100.00', '150.00', '50.00', '0.00'))
        self.assertEqual((d['payment_method'], d['payment_method_display'], d['created_by_email'], d['sale']),
                         ('qr', 'QR', 'clerk@test.com', self.sale.pk))
        back, out = d['items']
        self.assertEqual((back['direction'], back['sku'], back['unit_price'], back['subtotal'], back['sale_item']),
                         ('in', self.a.sku, '100.00', '100.00', self.item(self.a).pk))
        self.assertEqual((out['direction'], out['product_name'], out['unit_price'], out['sale_item']), ('out', 'Abrigo', '150.00', None))
        self.assertEqual((qty(self.a), qty(self.dear)), (9, 9))

    def test_cheaper_exchange_is_accepted_without_payment(self):
        r = self.post(new_items=[{'variant': self.cheap.pk, 'quantity': 1}], payment_method='')
        self.assertEqual(r.status_code, 201)
        self.assertEqual((r.data['difference'], r.data['unreturned_amount'], r.data['payment_method_display']), ('-60.00', '60.00', ''))

    def test_exchange_without_new_items_and_without_the_field(self):
        r = self.api.post(BASE, {
            'sale': self.sale.pk, 'returned_items': [{'sale_item': self.item(self.a).pk, 'quantity': 1}],
        }, format='json')
        self.assertEqual((r.status_code, r.data['new_total'], r.data['unreturned_amount']), (201, '0.00', '100.00'))

    def test_payment_required_with_difference(self):
        for method in ('', 'cheque'):
            self.assertEqual(self.post(payment_method=method).status_code, 400)
        self.assertEqual(Exchange.objects.count(), 0)

    def test_errors_are_400(self):
        a = self.item(self.a).pk
        for data in (
            {'returned_items': []},
            {'returned_items': [{'sale_item': a, 'quantity': 3}]},  # sólo compró 2
            {'returned_items': [{'sale_item': a, 'quantity': 0}]},
            {'returned_items': [{'sale_item': 99999, 'quantity': 1}]},
            {'new_items': [{'variant': self.a.pk, 'quantity': 1}]},  # por sí misma
            {'new_items': [{'variant': 99999, 'quantity': 1}]},
            {'sale': 99999},
        ):
            with self.subTest(data=data):
                self.assertEqual(self.post(**data).status_code, 400)
        self.assertEqual((Exchange.objects.count(), qty(self.a), qty(self.dear)), (0, 8, 10))

    def test_item_of_another_sale_is_400(self):
        other, _ = create_sale(self.seller, [(self.a, 1)], 'efectivo')
        r = self.post(returned_items=[{'sale_item': self.item(self.a, other).pk, 'quantity': 1}])
        self.assertEqual(r.status_code, 400)

    def test_out_of_deadline_is_400(self):
        Sale.objects.filter(pk=self.sale.pk).update(created_at=timezone.now() - timedelta(days=31))
        r = self.post()
        self.assertEqual(r.status_code, 400)
        self.assertIn('plazo', str(r.data['detail']))

    def test_no_stock_is_400_with_details(self):
        scarce = self.variant_of('Chaleco', D('300'), stock=0)
        r = self.post(new_items=[{'variant': scarce.pk, 'quantity': 1}])
        self.assertEqual((r.status_code, str(r.data['available']), str(r.data['requested'])), (400, '0', '1'))
        self.assertEqual((Exchange.objects.count(), qty(self.a)), (0, 8))

    def test_permissions(self):
        self.assertEqual(APIClient().post(BASE, self.payload(), format='json').status_code, 401)
        nobody = self.api_for(user_with('n@test.com'))
        self.assertEqual(self.post(api=nobody).status_code, 403)
        self.assertEqual(nobody.get(BASE).status_code, 403)
        self.assertEqual(nobody.post(BASE + 'preview/', self.payload(), format='json').status_code, 403)
        viewer = self.api_for(user_with('v@test.com', 'view_exchange'))
        self.assertEqual(viewer.get(BASE).status_code, 200)
        self.assertEqual(self.post(api=viewer).status_code, 403)
        self.assertEqual(Exchange.objects.count(), 0)

    def test_no_update_or_delete(self):
        ex = self.do_exchange()
        for method in ('put', 'patch', 'delete'):
            r = getattr(self.api, method)(f'{BASE}{ex.pk}/', {}, format='json')
            self.assertIn(r.status_code, (403, 405))

    # --- vista previa ---
    def test_preview_returns_totals_and_writes_nothing(self):
        data = self.payload()
        data.pop('payment_method')
        r = self.api.post(BASE + 'preview/', data, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(dict(r.data), {
            'returned_total': '100.00', 'new_total': '150.00', 'difference': '50.00', 'unreturned_amount': '0.00',
        })
        self.assertEqual((Exchange.objects.count(), qty(self.a), qty(self.dear), self.exchanged(self.a)), (0, 8, 10, 0))

    def test_preview_shows_unreturned_amount(self):
        r = self.api.post(BASE + 'preview/', self.payload(new_items=[{'variant': self.cheap.pk, 'quantity': 1}]), format='json')
        self.assertEqual((r.data['difference'], r.data['unreturned_amount']), ('-60.00', '60.00'))

    def test_preview_matches_create(self):
        preview = self.api.post(BASE + 'preview/', self.payload(), format='json').data
        created = self.post().data
        self.assertEqual({k: created[k] for k in preview}, dict(preview))

    def test_preview_validates_like_create(self):
        scarce = self.variant_of('Chaleco', D('300'), stock=0)
        for data in ({'returned_items': []}, {'new_items': [{'variant': scarce.pk, 'quantity': 1}]}):
            self.assertEqual(self.api.post(BASE + 'preview/', self.payload(**data), format='json').status_code, 400)

    # --- consulta ---
    def test_list_and_detail(self):
        ex = self.do_exchange()
        row = self.api.get(BASE).data['results'][0]
        self.assertEqual((row['id'], row['sale'], row['status'], row['difference']), (ex.pk, self.sale.pk, 'completada', '50.00'))
        self.assertNotIn('items', row)
        self.assertEqual(len(self.api.get(f'{BASE}{ex.pk}/').data['items']), 2)

    def test_sale_detail_lists_its_exchanges_and_available_units(self):
        ex = self.do_exchange()
        sale = self.api.get(f'{SALES}{self.sale.pk}/').data
        self.assertEqual([(e['id'], e['difference']) for e in sale['exchanges']], [(ex.pk, '50.00')])
        by_sku = {i['sku']: i for i in sale['items']}
        self.assertEqual((by_sku[self.a.sku]['exchanged_quantity'], by_sku[self.a.sku]['exchangeable_quantity']), (1, 1))

    def test_filters_and_search(self):
        from clients.models import Client
        ana = Client.objects.create(first_name='Ana', last_name='Paz', email='ana@test.com', origin='other')
        sale2, _ = create_sale(self.seller, [(self.a, 1)], 'efectivo', client=ana)
        e1 = self.do_exchange()
        e2 = create_exchange(self.clerk, sale2, [(sale2.items.get(), 1)], [(self.cheap, 1)])
        e3 = self.do_exchange()
        self.api_for(self.boss).post(f'{BASE}{e3.pk}/void/', {'reason': 'x'}, format='json')

        def ids(query):
            return {r['id'] for r in self.api.get(f'{BASE}?{query}').data['results']}

        self.assertEqual(ids(f'sale={sale2.pk}'), {e2.pk})
        self.assertEqual(ids(f'client={ana.pk}'), {e2.pk})
        self.assertEqual(ids('status=anulada'), {e3.pk})
        self.assertEqual(ids('payment_method=efectivo'), {e1.pk, e3.pk})
        self.assertEqual(ids(f'created_by={self.clerk.pk}'), {e2.pk})
        self.assertEqual(ids('date_from=2999-01-01'), set())
        today = datetime.now().date()
        self.assertEqual(ids(f'date_from={today}&date_to={today}'), {e1.pk, e2.pk, e3.pk})
        self.assertEqual(ids('search=ana'), {e2.pk})
        self.assertEqual(ids(f'search={self.dear.sku}'), {e1.pk, e3.pk})
        res = self.api.get(f'{BASE}?search={self.dear.sku}').data
        self.assertEqual(res['count'], 2)  # el buscador por SKU no duplica filas
        self.assertEqual([r['id'] for r in self.api.get(f'{BASE}?ordering=difference').data['results']][0], e2.pk)

    # --- anulación ---
    def test_void(self):
        ex = self.do_exchange()
        url = f'{BASE}{ex.pk}/void/'
        self.assertEqual(self.api.post(url, {'reason': 'x'}, format='json').status_code, 403)  # el vendedor no anula
        boss = self.api_for(self.boss)
        self.assertEqual(boss.post(url, {}, format='json').status_code, 400)
        self.assertEqual(boss.post(url, {'reason': ' '}, format='json').status_code, 400)
        r = boss.post(url, {'reason': 'Se arrepintió'}, format='json')
        self.assertEqual((r.status_code, r.data['status'], r.data['void_reason'], r.data['voided_by_email']),
                         (200, 'anulada', 'Se arrepintió', 'boss@test.com'))
        self.assertEqual((qty(self.a), qty(self.dear), self.exchanged(self.a)), (8, 10, 0))
        self.assertEqual(boss.post(url, {'reason': 'otra vez'}, format='json').status_code, 400)

    def test_void_fails_if_received_units_were_sold(self):
        ex = self.do_exchange()
        create_sale(self.seller, [(self.a, qty(self.a))], 'efectivo')
        r = self.api_for(self.boss).post(f'{BASE}{ex.pk}/void/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Exchange.objects.get(pk=ex.pk).status, 'completada')

    def test_stock_history_links_to_the_exchange(self):
        ex = self.do_exchange()
        viewer = self.api_for(user_with('s@test.com', 'view_stockmovement'))
        rows = viewer.get(f'/api/stock-operations/?exchange={ex.pk}').data['results']
        self.assertEqual(sorted((r['reason'], r['exchange']) for r in rows), [('cambio_entrada', ex.pk), ('cambio_salida', ex.pk)])

    def test_single_movement_of_an_exchange_cannot_be_reversed_alone(self):
        self.do_exchange()
        from stock.models import StockMovement
        mover = self.api_for(user_with('m@test.com', 'view_stockmovement', 'add_stockmovement'))
        movement = StockMovement.objects.filter(reason='cambio_salida').get()
        r = mover.post(f'/api/stock-movements/{movement.pk}/reverse/', {}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(qty(self.dear), 9)

    def test_query_count_of_the_list_is_constant(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.do_exchange()
        self.api.get(BASE)  # calienta el caché de permisos
        with CaptureQueriesContext(connection) as few:
            self.api.get(BASE)
        self.do_exchange(new=[(self.cheap, 1)], returned=[(self.item(self.a), 1)])
        self.do_exchange(new=[(self.cheap, 1)], returned=[(self.item(self.b), 1)])
        with CaptureQueriesContext(connection) as many:
            self.api.get(BASE)
        self.assertEqual(len(few), len(many))
