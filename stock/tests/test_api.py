from io import StringIO

from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from products.tests.test_variants import VariantFixtureMixin
from stock.models import StockLevel, StockMovement
from stock.services import apply_movement
from users.models import User

I, E = StockMovement.INGRESO, StockMovement.EGRESO


class StockApiBase(VariantFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        call_command('seed_roles', stdout=StringIO(), stderr=StringIO())
        self.api = APIClient()
        self.admin = User.objects.create_user(email='admin@t.com', password='x')
        self.admin.groups.add(Group.objects.get(name='Administrador'))
        self.seller = User.objects.create_user(email='seller@t.com', password='x')
        self.seller.groups.add(Group.objects.get(name='Vendedor'))
        self.api.force_authenticate(self.admin)
        self.a = self.make()
        self.b = self.make(color=self.red)

    def post_movement(self, kind, reason, items, **extra):
        return self.api.post(
            '/api/stock-operations/',
            {'kind': kind, 'reason': reason, 'items': [{'variant': v.pk, 'quantity': q} for v, q in items], **extra},
            format='json',
        )


class StockGridTests(StockApiBase):
    def test_lists_all_variants_with_zero_when_no_movements(self):
        apply_movement(self.a, I, 4, StockMovement.COMPRA)
        rows = {r['id']: r for r in self.api.get('/api/stock/').data['results']}
        self.assertEqual(rows[self.a.pk]['quantity'], 4)
        self.assertEqual(rows[self.b.pk]['quantity'], 0)
        self.assertEqual(rows[self.a.pk]['sku'], self.a.sku)

    def test_low_stock_flag_and_filters(self):
        self.a.min_stock = 3
        self.a.save()
        apply_movement(self.a, I, 3, StockMovement.COMPRA)      # 3 <= 3 -> bajo
        apply_movement(self.b, I, 10, StockMovement.COMPRA)     # mínimo 0 -> sin alerta
        rows = {r['id']: r for r in self.api.get('/api/stock/').data['results']}
        self.assertTrue(rows[self.a.pk]['is_low_stock'])
        self.assertFalse(rows[self.b.pk]['is_low_stock'])
        low = self.api.get('/api/stock/?low_stock=true').data['results']
        self.assertEqual([r['id'] for r in low], [self.a.pk])
        out = self.api.get('/api/stock/?out_of_stock=true').data['results']
        self.assertEqual(out, [])
        self.assertEqual(len(self.api.get('/api/stock/?in_stock=true').data['results']), 2)

    def test_out_of_stock_with_minimum_counts_as_low(self):
        self.a.min_stock = 2
        self.a.save()
        self.assertEqual([r['id'] for r in self.api.get('/api/stock/?low_stock=true').data['results']], [self.a.pk])
        self.assertEqual(len(self.api.get('/api/stock/?out_of_stock=true').data['results']), 2)

    def test_ordering_by_quantity_and_retrieve(self):
        apply_movement(self.b, I, 9, StockMovement.COMPRA)
        ids = [r['id'] for r in self.api.get('/api/stock/?ordering=-quantity').data['results']]
        self.assertEqual(ids[0], self.b.pk)
        self.assertEqual(self.api.get(f'/api/stock/{self.b.pk}/').data['quantity'], 9)

    def test_summary(self):
        self.a.min_stock = 5
        self.a.save()
        apply_movement(self.a, I, 2, StockMovement.COMPRA)
        data = self.api.get('/api/stock/summary/').data
        self.assertEqual(data, {'variants': 2, 'out_of_stock': 1, 'low_stock': 1, 'units': 2})

    def test_deleted_variant_not_listed(self):
        self.b.delete()
        self.assertEqual(len(self.api.get('/api/stock/').data['results']), 1)

    def test_no_query_per_row(self):
        for color in (self.blue, self.red):
            self.make(color=color, size=self.s)
        # 2 de permisos + conteo + página, sin importar cuántas filas haya.
        with self.assertNumQueries(4):
            self.api.get('/api/stock/')


class MovementApiTests(StockApiBase):
    def test_batch_ingreso(self):
        r = self.post_movement(I, 'stock_inicial', [(self.a, 5), (self.b, 3)], note='carga')
        self.assertEqual(r.status_code, 201)
        self.assertEqual((r.data['lines_count'], r.data['units']), (2, 8))
        self.assertEqual(len(r.data['movements']), 2)
        self.assertEqual(StockLevel.objects.get(variant=self.a).quantity, 5)
        self.assertEqual(StockMovement.objects.first().created_by, self.admin)

    def test_egreso_insufficient_returns_400_and_rolls_back(self):
        apply_movement(self.a, I, 2, StockMovement.COMPRA)
        r = self.post_movement(E, 'perdida', [(self.b, 1), (self.a, 3)])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['available'], '2')  # DRF serializa los valores de un 400 como texto
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_validation_errors(self):
        for payload in [
            {'kind': 'ajuste', 'reason': 'recuento', 'items': [{'variant': self.a.pk, 'quantity': 1}]},
            {'kind': 'ingreso', 'reason': 'perdida', 'items': [{'variant': self.a.pk, 'quantity': 1}]},
            {'kind': 'ingreso', 'reason': 'anulacion', 'items': [{'variant': self.a.pk, 'quantity': 1}]},
            {'kind': 'egreso', 'reason': 'venta', 'items': [{'variant': self.a.pk, 'quantity': 1}]},  # lo genera ventas
            {'kind': 'ingreso', 'reason': 'compra', 'items': []},
            {'kind': 'ingreso', 'reason': 'compra', 'items': [{'variant': self.a.pk, 'quantity': 0}]},
            {'kind': 'ingreso', 'reason': 'compra', 'items': [{'variant': self.a.pk, 'quantity': 1}] * 2},
            {'kind': 'ingreso', 'reason': 'compra', 'items': [{'variant': 99999, 'quantity': 1}]},
        ]:
            with self.subTest(payload=payload):
                self.assertEqual(self.api.post('/api/stock-operations/', payload, format='json').status_code, 400)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_deleted_variant_rejected(self):
        self.b.delete()
        self.assertEqual(self.post_movement(I, 'compra', [(self.b, 1)]).status_code, 400)

    def test_history_filters(self):
        apply_movement(self.a, I, 5, StockMovement.COMPRA)
        apply_movement(self.b, I, 2, StockMovement.COMPRA)
        apply_movement(self.a, E, -1, StockMovement.PERDIDA)
        res = self.api.get(f'/api/stock-movements/?variant={self.a.pk}&kind=egreso').data['results']
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['quantity'], -1)
        self.assertEqual(len(self.api.get('/api/stock-movements/?reason=compra').data['results']), 2)
        self.assertEqual(len(self.api.get(f'/api/stock-movements/?product={self.product.pk}').data['results']), 3)
        self.assertEqual(len(self.api.get('/api/stock-movements/?date_from=2999-01-01').data['results']), 0)

    def test_date_filters_use_local_time(self):
        """Un movimiento de las 22:30 en Buenos Aires (01:30 UTC del día siguiente) cuenta en el día local."""
        from datetime import datetime, timezone as dt_timezone

        m = apply_movement(self.a, I, 5, StockMovement.COMPRA)
        StockMovement.objects.filter(pk=m.pk).update(created_at=datetime(2026, 3, 10, 1, 30, tzinfo=dt_timezone.utc))

        def count(query):
            return len(self.api.get(f'/api/stock-movements/?{query}').data['results'])

        self.assertEqual(count('date_from=2026-03-09&date_to=2026-03-09'), 1)
        self.assertEqual(count('date_from=2026-03-10'), 0)

    def test_history_is_immutable(self):
        m = apply_movement(self.a, I, 5, StockMovement.COMPRA)
        for method in ('put', 'patch', 'delete'):
            for url in (f'/api/stock-movements/{m.pk}/', f'/api/stock-operations/{m.operation_id}/'):
                r = getattr(self.api, method)(url, {}, format='json')
                self.assertIn(r.status_code, (403, 405))  # nunca 2xx
        self.assertIn(self.api.post('/api/stock-movements/', {}, format='json').status_code, (403, 405))


class ReverseApiTests(StockApiBase):
    def test_reverse_ingreso(self):
        m = apply_movement(self.a, I, 5, StockMovement.COMPRA)
        r = self.api.post(f'/api/stock-movements/{m.pk}/reverse/', {'note': 'error de carga'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['kind'], 'egreso')
        self.assertEqual(r.data['reason'], 'anulacion')
        self.assertEqual(r.data['reverses'], m.pk)
        self.assertEqual(r.data['reverses_operation'], m.operation_id)
        self.assertIsNone(r.data['reversed_by_operation'])
        self.assertEqual(StockLevel.objects.get(variant=self.a).quantity, 0)
        original = self.api.get(f'/api/stock-movements/{m.pk}/').data
        self.assertEqual(original['reversed_by'], r.data['id'])
        self.assertEqual(original['reversed_by_operation'], r.data['operation'])  # sin consulta extra para enlazar

    def test_reverse_egreso_restores_stock(self):
        apply_movement(self.a, I, 5, StockMovement.COMPRA)
        m = apply_movement(self.a, E, -2, StockMovement.PERDIDA)
        r = self.api.post(f'/api/stock-movements/{m.pk}/reverse/')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(StockLevel.objects.get(variant=self.a).quantity, 5)

    def test_cannot_reverse_twice_or_reverse_a_reversal(self):
        m = apply_movement(self.a, I, 5, StockMovement.COMPRA)
        reversal = self.api.post(f'/api/stock-movements/{m.pk}/reverse/').data
        self.assertEqual(self.api.post(f'/api/stock-movements/{m.pk}/reverse/').status_code, 400)
        self.assertEqual(self.api.post(f'/api/stock-movements/{reversal["id"]}/reverse/').status_code, 400)

    def test_cannot_reverse_ajuste(self):
        m = apply_movement(self.a, 'ajuste', 3, StockMovement.CORRECCION)
        self.assertEqual(self.api.post(f'/api/stock-movements/{m.pk}/reverse/').status_code, 400)

    def test_reverse_fails_when_units_already_left(self):
        m = apply_movement(self.a, I, 5, StockMovement.COMPRA)
        apply_movement(self.a, E, -4, StockMovement.PERDIDA)
        r = self.api.post(f'/api/stock-movements/{m.pk}/reverse/')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(StockLevel.objects.get(variant=self.a).quantity, 1)
        self.assertEqual(StockMovement.objects.count(), 2)


class PermissionTests(StockApiBase):
    def test_seller_can_only_view(self):
        apply_movement(self.a, I, 5, StockMovement.COMPRA)
        m = StockMovement.objects.get()
        self.api.force_authenticate(self.seller)
        self.assertEqual(self.api.get('/api/stock/').status_code, 200)
        self.assertEqual(self.api.get('/api/stock/summary/').status_code, 200)
        self.assertEqual(self.api.get('/api/stock-movements/').status_code, 200)
        self.assertEqual(self.post_movement(I, 'compra', [(self.a, 1)]).status_code, 403)
        self.assertEqual(self.api.post(f'/api/stock-movements/{m.pk}/reverse/').status_code, 403)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_seller_sees_min_stock_fields(self):
        self.api.force_authenticate(self.seller)
        row = self.api.get('/api/stock/').data['results'][0]
        self.assertIn('min_stock', row)
        self.assertIn('is_low_stock', row)

    def test_user_without_permissions_denied(self):
        self.api.force_authenticate(User.objects.create_user(email='n@t.com', password='x'))
        self.assertEqual(self.api.get('/api/stock/').status_code, 403)
        self.assertEqual(self.api.get('/api/stock-movements/').status_code, 403)

    def test_anonymous_denied(self):
        self.api.force_authenticate(None)
        self.assertEqual(self.api.get('/api/stock/').status_code, 401)


class MinStockOnVariantTests(StockApiBase):
    def test_default_zero_and_patch(self):
        r = self.api.post('/api/product-variants/', {'product': self.product.pk, 'color': self.blue.pk, 'size': self.s.pk}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['min_stock'], 0)
        r = self.api.patch(f'/api/product-variants/{r.data["id"]}/', {'min_stock': 4}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['min_stock'], 4)

    def test_rejects_negative(self):
        r = self.api.patch(f'/api/product-variants/{self.a.pk}/', {'min_stock': -1}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_seller_cannot_edit(self):
        self.api.force_authenticate(self.seller)
        r = self.api.patch(f'/api/product-variants/{self.a.pk}/', {'min_stock': 4}, format='json')
        self.assertEqual(r.status_code, 403)


class StockCountApiTests(StockApiBase):
    def create_count(self, items=None, **extra):
        payload = {'note': 'vidriera', **extra}
        if items is not None:
            payload['items'] = [{'variant': v.pk, 'counted_quantity': q} for v, q in items]
        return self.api.post('/api/stock-counts/', payload, format='json')

    def add_item(self, count_id, variant, qty):
        return self.api.post(
            f'/api/stock-counts/{count_id}/items/', {'variant': variant.pk, 'counted_quantity': qty}, format='json'
        )

    def test_create_draft_with_items(self):
        r = self.create_count([(self.a, 4)])
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['status'], 'borrador')
        self.assertEqual(r.data['created_by'], self.admin.pk)
        self.assertEqual(len(r.data['items']), 1)
        self.assertIsNone(r.data['items'][0]['system_quantity'])

    def test_create_rejects_duplicate_and_deleted_variants(self):
        self.assertEqual(self.create_count([(self.a, 1), (self.a, 2)]).status_code, 400)
        self.b.delete()
        self.assertEqual(self.create_count([(self.b, 1)]).status_code, 400)

    def test_add_item_upserts_and_remove(self):
        cid = self.create_count().data['id']
        self.add_item(cid, self.a, 3)
        r = self.add_item(cid, self.a, 5)
        self.assertEqual(r.status_code, 201)
        self.assertEqual([i['counted_quantity'] for i in r.data['items']], [5])
        self.add_item(cid, self.b, 0)
        r = self.api.delete(f'/api/stock-counts/{cid}/items/{self.a.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([i['variant'] for i in r.data['items']], [self.b.pk])
        self.assertEqual(self.api.delete(f'/api/stock-counts/{cid}/items/{self.a.pk}/').status_code, 404)

    def test_confirm_adjusts_and_records_differences(self):
        apply_movement(self.a, I, 5, StockMovement.COMPRA)
        apply_movement(self.b, I, 2, StockMovement.COMPRA)
        cid = self.create_count([(self.a, 3), (self.b, 2)]).data['id']
        r = self.api.post(f'/api/stock-counts/{cid}/confirm/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['status'], 'confirmado')
        self.assertEqual(r.data['confirmed_by'], self.admin.pk)
        rows = {i['variant']: i for i in r.data['items']}
        self.assertEqual((rows[self.a.pk]['system_quantity'], rows[self.a.pk]['difference']), (5, -2))
        self.assertEqual((rows[self.b.pk]['system_quantity'], rows[self.b.pk]['difference']), (2, 0))
        self.assertEqual(StockLevel.objects.get(variant=self.a).quantity, 3)
        adjustments = StockMovement.objects.filter(operation__stock_count_id=cid)
        self.assertEqual(adjustments.count(), 1)  # sin diferencia no hay movimiento
        self.assertEqual((adjustments[0].kind, adjustments[0].reason, adjustments[0].quantity), ('ajuste', 'recuento', -2))
        self.assertEqual(len(self.api.get(f'/api/stock-movements/?stock_count={cid}').data['results']), 1)

    def test_count_can_raise_stock_from_nothing(self):
        cid = self.create_count([(self.a, 7)]).data['id']
        self.api.post(f'/api/stock-counts/{cid}/confirm/')
        self.assertEqual(StockLevel.objects.get(variant=self.a).quantity, 7)

    def test_partial_count_leaves_other_variants_alone(self):
        apply_movement(self.b, I, 9, StockMovement.COMPRA)
        cid = self.create_count([(self.a, 1)]).data['id']
        self.api.post(f'/api/stock-counts/{cid}/confirm/')
        self.assertEqual(StockLevel.objects.get(variant=self.b).quantity, 9)

    def test_difference_uses_stock_at_confirmation(self):
        apply_movement(self.a, I, 5, StockMovement.COMPRA)
        cid = self.create_count([(self.a, 5)]).data['id']
        apply_movement(self.a, E, -2, StockMovement.PERDIDA)  # entre el conteo y la confirmación
        r = self.api.post(f'/api/stock-counts/{cid}/confirm/')
        self.assertEqual((r.data['items'][0]['system_quantity'], r.data['items'][0]['difference']), (3, 2))
        self.assertEqual(StockLevel.objects.get(variant=self.a).quantity, 5)

    def test_confirm_empty_rejected(self):
        cid = self.create_count().data['id']
        self.assertEqual(self.api.post(f'/api/stock-counts/{cid}/confirm/').status_code, 400)

    def test_confirm_rolls_back_if_a_variant_was_deleted(self):
        apply_movement(self.a, I, 5, StockMovement.COMPRA)
        cid = self.create_count([(self.a, 1), (self.b, 4)]).data['id']
        self.b.delete()
        self.assertEqual(self.api.post(f'/api/stock-counts/{cid}/confirm/').status_code, 400)
        self.assertEqual(StockLevel.objects.get(variant=self.a).quantity, 5)
        self.assertEqual(self.api.get(f'/api/stock-counts/{cid}/').data['status'], 'borrador')

    def test_confirmed_and_cancelled_are_frozen(self):
        cid = self.create_count([(self.a, 1)]).data['id']
        self.api.post(f'/api/stock-counts/{cid}/confirm/')
        self.assertEqual(self.api.post(f'/api/stock-counts/{cid}/confirm/').status_code, 400)
        self.assertEqual(self.api.post(f'/api/stock-counts/{cid}/cancel/').status_code, 400)
        self.assertEqual(self.add_item(cid, self.b, 1).status_code, 400)
        self.assertEqual(self.api.patch(f'/api/stock-counts/{cid}/', {'note': 'x'}, format='json').status_code, 400)
        self.assertEqual(self.api.delete(f'/api/stock-counts/{cid}/items/{self.a.pk}/').status_code, 400)

    def test_cancel_does_not_touch_stock(self):
        cid = self.create_count([(self.a, 9)]).data['id']
        r = self.api.post(f'/api/stock-counts/{cid}/cancel/')
        self.assertEqual(r.data['status'], 'cancelado')
        self.assertFalse(StockLevel.objects.filter(variant=self.a, quantity=9).exists())
        self.assertEqual(self.api.post(f'/api/stock-counts/{cid}/confirm/').status_code, 400)

    def test_patch_note_and_no_put_or_delete(self):
        cid = self.create_count().data['id']
        r = self.api.patch(f'/api/stock-counts/{cid}/', {'note': 'otra', 'status': 'confirmado'}, format='json')
        self.assertEqual((r.status_code, r.data['note'], r.data['status']), (200, 'otra', 'borrador'))
        self.assertIn(self.api.put(f'/api/stock-counts/{cid}/', {}, format='json').status_code, (403, 405))
        self.assertIn(self.api.delete(f'/api/stock-counts/{cid}/').status_code, (403, 405))

    def test_list_filters_and_items_count(self):
        c1 = self.create_count([(self.a, 1), (self.b, 1)]).data['id']
        c2 = self.create_count().data['id']
        self.api.post(f'/api/stock-counts/{c2}/cancel/')
        rows = {r['id']: r for r in self.api.get('/api/stock-counts/').data['results']}
        self.assertEqual(rows[c1]['items_count'], 2)
        self.assertNotIn('items', rows[c1])
        self.assertEqual([r['id'] for r in self.api.get('/api/stock-counts/?status=cancelado').data['results']], [c2])

    def test_permissions(self):
        cid = self.create_count([(self.a, 1)]).data['id']
        self.api.force_authenticate(self.seller)
        self.assertEqual(self.api.get('/api/stock-counts/').status_code, 200)
        self.assertEqual(self.api.get(f'/api/stock-counts/{cid}/').status_code, 200)
        self.assertEqual(self.create_count().status_code, 403)
        self.assertEqual(self.api.post(f'/api/stock-counts/{cid}/confirm/').status_code, 403)
        self.assertEqual(self.add_item(cid, self.b, 1).status_code, 403)
        self.assertEqual(self.api.post(f'/api/stock-counts/{cid}/cancel/').status_code, 403)
        self.api.force_authenticate(User.objects.create_user(email='n@t.com', password='x'))
        self.assertEqual(self.api.get('/api/stock-counts/').status_code, 403)

    def test_count_adjustments_cannot_be_reversed(self):
        cid = self.create_count([(self.a, 3)]).data['id']
        self.api.post(f'/api/stock-counts/{cid}/confirm/')
        m = StockMovement.objects.get(operation__stock_count_id=cid)
        self.assertEqual(self.api.post(f'/api/stock-movements/{m.pk}/reverse/').status_code, 400)


class VariantWithStockDeleteTests(StockApiBase):
    def test_cannot_delete_variant_with_stock(self):
        apply_movement(self.a, I, 2, StockMovement.COMPRA)
        r = self.api.delete(f'/api/product-variants/{self.a.pk}/')
        self.assertEqual(r.status_code, 400)
        apply_movement(self.a, E, -2, StockMovement.PERDIDA)
        self.assertEqual(self.api.delete(f'/api/product-variants/{self.a.pk}/').status_code, 204)

    def test_can_delete_variant_that_never_had_stock(self):
        self.assertEqual(self.api.delete(f'/api/product-variants/{self.b.pk}/').status_code, 204)


class StockCountBulkItemsTests(StockApiBase):
    def setUp(self):
        super().setUp()
        self.c = self.make(color=self.blue, size=self.s)
        self.cid = self.api.post('/api/stock-counts/', {'items': [{'variant': self.a.pk, 'counted_quantity': 1}]}, format='json').data['id']

    def bulk(self, items):
        return self.api.post(
            f'/api/stock-counts/{self.cid}/items/bulk/',
            {'items': [{'variant': v.pk, 'counted_quantity': q} for v, q in items]}, format='json',
        )

    def test_adds_and_updates_in_one_request(self):
        r = self.bulk([(self.a, 9), (self.b, 0), (self.c, 4)])
        self.assertEqual(r.status_code, 200)
        self.assertEqual({i['variant']: i['counted_quantity'] for i in r.data['items']},
                         {self.a.pk: 9, self.b.pk: 0, self.c.pk: 4})

    def test_unmentioned_lines_are_kept(self):
        r = self.bulk([(self.b, 2)])
        self.assertEqual({i['variant'] for i in r.data['items']}, {self.a.pk, self.b.pk})

    def test_rejects_duplicates_empty_and_deleted_atomically(self):
        self.assertEqual(self.bulk([(self.b, 1), (self.b, 2)]).status_code, 400)
        self.assertEqual(self.bulk([]).status_code, 400)
        self.c.delete()
        self.assertEqual(self.bulk([(self.b, 5), (self.c, 1)]).status_code, 400)
        items = self.api.get(f'/api/stock-counts/{self.cid}/').data['items']
        self.assertEqual([i['variant'] for i in items], [self.a.pk])  # no se aplicó nada

    def test_frozen_after_confirm_and_needs_permission(self):
        self.api.force_authenticate(self.seller)
        self.assertEqual(self.bulk([(self.b, 1)]).status_code, 403)
        self.api.force_authenticate(self.admin)
        self.api.post(f'/api/stock-counts/{self.cid}/confirm/')
        self.assertEqual(self.bulk([(self.b, 1)]).status_code, 400)


class OperationHistoryTests(StockApiBase):
    def test_batch_is_one_row_with_detail(self):
        r = self.post_movement(I, 'compra', [(self.a, 5), (self.b, 3)], note='Pedido Norte')
        history = self.api.get('/api/stock-operations/').data['results']
        self.assertEqual(len(history), 1)
        row = history[0]
        self.assertEqual((row['kind'], row['reason'], row['note'], row['lines_count'], row['units']), ('ingreso', 'compra', 'Pedido Norte', 2, 8))
        self.assertEqual(row['created_by'], self.admin.pk)
        self.assertNotIn('movements', row)
        detail = self.api.get(f'/api/stock-operations/{r.data["id"]}/').data
        self.assertEqual({m['sku'] for m in detail['movements']}, {self.a.sku, self.b.sku})
        self.assertEqual({m['quantity'] for m in detail['movements']}, {5, 3})
        self.assertEqual({m['operation'] for m in detail['movements']}, {r.data['id']})
        # las líneas siguen consultables una por una
        self.assertEqual(self.api.get(f'/api/stock-movements/?operation={r.data["id"]}').data['count'], 2)

    def test_ten_lines_are_one_operation(self):
        variants = [self.make(color=self.red, size=self.s)] + [
            self.make(color=self.blue, size=self.s)
        ]
        variants += [self.a, self.b]
        r = self.post_movement(I, 'compra', [(v, 2) for v in variants])
        self.assertEqual(self.api.get('/api/stock-operations/').data['count'], 1)
        self.assertEqual(r.data['lines_count'], 4)
        self.assertEqual(self.api.get('/api/stock-movements/').data['count'], 4)

    def test_failed_batch_leaves_no_operation(self):
        self.post_movement(E, 'perdida', [(self.a, 1)])
        self.assertEqual(self.api.get('/api/stock-operations/').data['count'], 0)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_reversal_and_count_are_operations_too(self):
        apply_movement(self.a, I, 5, StockMovement.COMPRA)
        m = StockMovement.objects.get()
        self.api.post(f'/api/stock-movements/{m.pk}/reverse/')
        cid = self.api.post('/api/stock-counts/', {'items': [{'variant': self.b.pk, 'counted_quantity': 3}]}, format='json').data['id']
        self.api.post(f'/api/stock-counts/{cid}/confirm/')
        kinds = [(o['kind'], o['reason']) for o in self.api.get('/api/stock-operations/').data['results']]  # más nuevas primero
        self.assertEqual(kinds, [('ajuste', 'recuento'), ('egreso', 'anulacion'), ('ingreso', 'compra')])
        op = self.api.get(f'/api/stock-operations/?stock_count={cid}').data['results'][0]
        self.assertEqual((op['stock_count'], op['lines_count'], op['units']), (cid, 1, 3))

    def test_count_without_differences_is_an_operation_with_no_lines(self):
        apply_movement(self.a, I, 5, StockMovement.COMPRA)
        cid = self.api.post('/api/stock-counts/', {'items': [{'variant': self.a.pk, 'counted_quantity': 5}]}, format='json').data['id']
        self.api.post(f'/api/stock-counts/{cid}/confirm/')
        op = self.api.get(f'/api/stock-operations/?stock_count={cid}').data['results'][0]
        self.assertEqual((op['lines_count'], op['units']), (0, 0))
        self.assertEqual(self.api.get(f'/api/stock-operations/{op["id"]}/').data['movements'], [])

    def test_filters(self):
        o1 = self.post_movement(I, 'compra', [(self.a, 5), (self.b, 2)], note='Pedido Norte').data['id']
        o2 = self.post_movement(E, 'perdida', [(self.a, 1)]).data['id']
        ids = lambda q: [o['id'] for o in self.api.get(f'/api/stock-operations/{q}').data['results']]
        self.assertEqual(ids(f'?variant={self.b.pk}'), [o1])
        self.assertEqual(sorted(ids(f'?variant={self.a.pk}')), sorted([o1, o2]))
        self.assertEqual(ids(f'?product={self.product.pk}&kind=egreso'), [o2])
        self.assertEqual(ids('?reason=compra'), [o1])
        self.assertEqual(ids('?search=norte'), [o1])
        self.assertEqual(sorted(ids(f'?search={self.b.sku}')), [o1])
        self.assertEqual(ids('?date_from=2999-01-01'), [])
        self.assertEqual(ids('?ordering=-units'), [o1, o2])  # 7 unidades contra 1
        # el filtro por variante no duplica filas ni altera los totales
        row = self.api.get(f'/api/stock-operations/?variant={self.a.pk}&reason=compra').data['results'][0]
        self.assertEqual((row['lines_count'], row['units']), (2, 7))

    def test_permissions(self):
        op = self.post_movement(I, 'compra', [(self.a, 1)]).data['id']
        self.api.force_authenticate(self.seller)
        self.assertEqual(self.api.get('/api/stock-operations/').status_code, 200)
        self.assertEqual(self.api.get(f'/api/stock-operations/{op}/').status_code, 200)
        self.assertEqual(self.post_movement(I, 'compra', [(self.a, 1)]).status_code, 403)
        self.api.force_authenticate(User.objects.create_user(email='n@t.com', password='x'))
        self.assertEqual(self.api.get('/api/stock-operations/').status_code, 403)

    def test_no_query_per_row_in_list_and_detail(self):
        r = self.post_movement(I, 'compra', [(self.a, 1), (self.b, 1)])
        for _ in range(3):
            self.post_movement(I, 'compra', [(self.a, 1), (self.b, 1)])
        with self.assertNumQueries(2):  # conteo + página (los permisos ya están en caché del usuario)
            self.api.get('/api/stock-operations/')
        with self.assertNumQueries(2):  # operación + todas sus líneas
            self.api.get(f'/api/stock-operations/{r.data["id"]}/')


@override_settings(IMAGE_STORAGE='core.tests.fakes.FakeImageStorage', IMAGE_FOLDER='test')
class StockImagesTests(StockApiBase):
    def rows(self, url='/api/stock/'):
        return {r['id']: r for r in self.api.get(url).data['results']}

    def test_primary_photo_of_the_variant_color(self):
        self.add_image(color=self.blue, storage_key='test/azul-2', sort_order=2)
        self.add_image(color=self.blue, storage_key='test/azul-principal', is_primary=True, sort_order=5)
        self.add_image(color=self.red, storage_key='test/rojo-1')
        rows = self.rows()
        self.assertEqual(rows[self.a.pk]['image_url'], 'https://fake.test/test/azul-principal')
        self.assertEqual(rows[self.a.pk]['thumbnail_url'], 'https://fake.test/400x400/test/azul-principal')
        self.assertEqual(rows[self.b.pk]['image_url'], 'https://fake.test/test/rojo-1')

    def test_without_primary_uses_lowest_order(self):
        self.add_image(color=self.blue, storage_key='test/b', sort_order=3)
        self.add_image(color=self.blue, storage_key='test/a', sort_order=1)
        self.assertEqual(self.rows()[self.a.pk]['image_url'], 'https://fake.test/test/a')

    def test_color_without_photos_is_null(self):
        self.add_image(color=self.blue, storage_key='test/azul')
        row = self.rows()[self.b.pk]  # rojo: sin fotos (la del azul no se usa)
        self.assertIsNone(row['image_url'])
        self.assertIsNone(row['thumbnail_url'])

    def test_deleted_photo_is_ignored(self):
        self.add_image(color=self.blue, storage_key='test/borrada', is_primary=True).delete()
        self.add_image(color=self.blue, storage_key='test/vigente')
        self.assertEqual(self.rows()[self.a.pk]['image_url'], 'https://fake.test/test/vigente')

    def test_retrieve_includes_photo(self):
        self.add_image(color=self.blue, storage_key='test/azul')
        data = self.api.get(f'/api/stock/{self.a.pk}/').data
        self.assertEqual(data['image_url'], 'https://fake.test/test/azul')
        self.assertEqual(data['thumbnail_url'], 'https://fake.test/400x400/test/azul')

    def test_same_photo_as_product_variants(self):
        self.add_image(color=self.blue, storage_key='test/azul-2', sort_order=2)
        self.add_image(color=self.blue, storage_key='test/azul-1', sort_order=1)
        self.add_image(color=self.red, storage_key='test/rojo', is_primary=True)
        stock = self.rows()
        variants = {r['id']: r for r in self.api.get('/api/product-variants/').data['results']}
        for pk in (self.a.pk, self.b.pk):
            self.assertEqual((stock[pk]['image_url'], stock[pk]['thumbnail_url']), (variants[pk]['image_url'], variants[pk]['thumbnail_url']))

    def test_hidden_without_view_productimage(self):
        self.add_image(color=self.blue, storage_key='test/azul')
        user = User.objects.create_user(email='solo-stock@t.com', password='x')
        user.user_permissions.add(Permission.objects.get(content_type__app_label='stock', codename='view_stocklevel'))
        self.api.force_authenticate(user)
        for data in (self.rows()[self.a.pk], self.api.get(f'/api/stock/{self.a.pk}/').data):
            self.assertIsNone(data['image_url'])
            self.assertIsNone(data['thumbnail_url'])
            self.assertEqual(data['quantity'], 0)  # el resto del contrato no cambia
        user.user_permissions.add(Permission.objects.get(content_type__app_label='products', codename='view_productimage'))
        user = User.objects.get(pk=user.pk)  # descarta el caché de permisos
        self.api.force_authenticate(user)
        self.assertEqual(self.rows()[self.a.pk]['image_url'], 'https://fake.test/test/azul')

    def test_seller_sees_photos(self):
        self.add_image(color=self.blue, storage_key='test/azul')
        self.api.force_authenticate(self.seller)
        self.assertEqual(self.rows()[self.a.pk]['image_url'], 'https://fake.test/test/azul')

    def test_no_query_per_row_with_photos(self):
        extra = [self.make(color=self.red, size=self.s), self.make(color=self.blue, size=self.s)]
        for color in (self.blue, self.red):
            self.add_image(color=color, storage_key=f'test/{color.name}')
        self.assertEqual(len(extra), 2)
        with self.assertNumQueries(4):  # 2 de permisos + conteo + página (fotos en la misma consulta)
            self.assertEqual(len(self.api.get('/api/stock/').data['results']), 4)

    def test_existing_contract_unchanged_and_filters_still_work(self):
        self.add_image(color=self.blue, storage_key='test/azul')
        self.a.min_stock = 3
        self.a.save()
        apply_movement(self.a, I, 2, StockMovement.COMPRA)
        row = self.rows('/api/stock/?low_stock=true')[self.a.pk]
        self.assertEqual((row['quantity'], row['min_stock'], row['is_low_stock']), (2, 3, True))
        self.assertEqual(len(self.api.get('/api/stock/?low_stock=true').data['results']), 1)
