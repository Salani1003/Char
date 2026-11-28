import threading
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from clients.models import Client
from products.tests.test_variants import VariantFixtureMixin
from sales.exceptions import SaleError
from sales.models import Exchange, PaymentMethod, Sale
from sales.services import create_sale, discounted_price, void_sale
from stock.exceptions import InsufficientStock
from stock.models import StockLevel, StockMovement, StockOperation
from stock.services import apply_movements
from users.models import User

D = Decimal
CASH = PaymentMethod.EFECTIVO


def qty(variant):
    level = StockLevel.objects.filter(variant=variant).first()
    return level.quantity if level else 0


def user_with(email, *codenames):
    user = User.objects.create_user(email=email, password='x')
    user.user_permissions.set(Permission.objects.filter(codename__in=codenames))
    return User.objects.get(pk=user.pk)  # sin el caché de permisos


class SaleFixtureMixin(VariantFixtureMixin):
    def setUp(self):
        super().setUp()
        self.a = self.make()  # producto de $100
        self.b = self.make(color=self.red)
        apply_movements([(self.a, 10), (self.b, 10)], StockMovement.INGRESO, StockMovement.COMPRA)
        self.seller = User.objects.create_user(email='seller@test.com', password='x')
        self.admin = user_with('admin@test.com', 'apply_discount')


class DiscountedPriceTests(TestCase):
    def test_rounding(self):
        self.assertEqual(discounted_price(D('100'), 0), D('100.00'))
        self.assertEqual(discounted_price(D('100'), 10), D('90.00'))
        self.assertEqual(discounted_price(D('99.99'), 5), D('94.99'))  # 94.9905
        self.assertEqual(discounted_price(D('0.50'), 5), D('0.48'))  # 0.475 → mitad hacia arriba


class CreateSaleTests(SaleFixtureMixin, TestCase):
    def sell(self, lines=None, **kw):
        kw.setdefault('user', self.seller)
        kw.setdefault('payment_method', CASH)
        return create_sale(lines=[(self.a, 2)] if lines is None else lines, **kw)

    def test_creates_sale_items_and_discounts_stock(self):
        client = Client.objects.create(first_name='Ana', last_name='Paz', email='ana@test.com', origin='other')
        sale, created = self.sell([(self.a, 2), (self.b, 1)], client=client, note='regalo')
        self.assertTrue(created)
        self.assertEqual((sale.status, sale.client, sale.note, sale.created_by), ('completada', client, 'regalo', self.seller))
        self.assertEqual((sale.subtotal, sale.total), (D('300'), D('300')))
        self.assertEqual({(i.variant_id, i.quantity, i.unit_price, i.subtotal) for i in sale.items.all()},
                         {(self.a.pk, 2, D('100'), D('200')), (self.b.pk, 1, D('100'), D('100'))})
        self.assertEqual((qty(self.a), qty(self.b)), (8, 9))

    def test_stock_operation_is_linked_and_labeled(self):
        sale, _ = self.sell()
        op = sale.stock_operations.get()
        self.assertEqual((op.kind, op.reason, op.note, op.created_by), ('egreso', 'venta', f'Venta #{sale.pk}', self.seller))
        self.assertEqual(op.movements.get().quantity, -2)

    def test_uses_promo_price_when_in_range(self):
        today = timezone.localdate()
        self.product.promo_price = D('80')
        self.product.promo_start, self.product.promo_end = today - timedelta(days=1), today + timedelta(days=1)
        self.product.save()
        sale, _ = self.sell()
        item = sale.items.get()
        self.assertEqual((item.list_price, item.unit_price, sale.total), (D('80'), D('80'), D('160')))

    def test_expired_promo_uses_sale_price(self):
        today = timezone.localdate()
        self.product.promo_price = D('80')
        self.product.promo_start, self.product.promo_end = today - timedelta(days=9), today - timedelta(days=1)
        self.product.save()
        self.assertEqual(self.sell()[0].items.get().unit_price, D('100'))

    def test_price_is_frozen(self):
        sale, _ = self.sell()
        self.product.sale_price = D('500')
        self.product.save()
        item = sale.items.get()
        self.assertEqual((item.unit_price, Sale.objects.get(pk=sale.pk).total), (D('100'), D('200')))

    def test_discount_needs_permission(self):
        with self.assertRaises(PermissionDenied):
            self.sell(discount_percent=10)
        self.assertEqual((Sale.objects.count(), qty(self.a)), (0, 10))

    def test_discount_applied_per_item(self):
        sale, _ = self.sell([(self.a, 2)], user=self.admin, discount_percent=10, discount_reason='cliente frecuente')
        item = sale.items.get()
        self.assertEqual((item.list_price, item.discount_percent, item.unit_price, item.subtotal), (D('100'), 10, D('90.00'), D('180.00')))
        self.assertEqual((sale.subtotal, sale.total, sale.discount_percent, sale.discount_reason), (D('200'), D('180.00'), 10, 'cliente frecuente'))

    def test_discount_zero_needs_no_permission(self):
        self.sell(discount_percent=0)

    def test_discount_must_be_an_allowed_value(self):
        for percent in (1, 7, 15, 100, -5):
            with self.subTest(percent=percent), self.assertRaises(SaleError):
                self.sell(user=self.admin, discount_percent=percent)

    def test_insufficient_stock_saves_nothing(self):
        before = StockOperation.objects.count()
        with self.assertRaises(InsufficientStock) as ctx:
            self.sell([(self.a, 11)])
        self.assertEqual((ctx.exception.available, ctx.exception.requested), (10, 11))
        self.assertEqual((Sale.objects.count(), StockOperation.objects.count(), qty(self.a)), (0, before, 10))

    def test_one_line_without_stock_rolls_back_the_others(self):
        with self.assertRaises(InsufficientStock):
            self.sell([(self.a, 1), (self.b, 99)])
        self.assertEqual((Sale.objects.count(), qty(self.a), qty(self.b)), (0, 10, 10))

    def test_can_sell_the_last_unit(self):
        self.sell([(self.a, 10)])
        self.assertEqual(qty(self.a), 0)
        with self.assertRaises(InsufficientStock):
            self.sell([(self.a, 1)])

    def test_input_validation(self):
        for kwargs in (
            {'lines': []},
            {'lines': [(self.a, 1), (self.a, 2)]},
            {'lines': [(self.a, 0)]},
            {'payment_method': 'cheque'},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(SaleError):
                self.sell(**kwargs)
        self.assertEqual((Sale.objects.count(), qty(self.a)), (0, 10))

    def test_every_payment_method_is_accepted(self):
        for method in PaymentMethod.values:
            self.sell([(self.a, 1)], payment_method=method)
        self.assertEqual(Sale.objects.count(), 5)

    def test_deleted_variant_and_client_rejected(self):
        client = Client.objects.create(first_name='Ana', last_name='Paz', email='ana@test.com', origin='other')
        client.delete()
        with self.assertRaises(SaleError):
            self.sell(client=client)
        gone = self.make(color=self.blue, size=self.s)
        gone.delete()
        with self.assertRaises(SaleError):
            self.sell([(gone, 1)])
        self.assertEqual(Sale.objects.count(), 0)

    def test_uses_current_price_even_with_a_stale_variant_object(self):
        stale = self.a
        self.product.sale_price = D('150')
        self.product.save()
        self.assertEqual(self.sell([(stale, 1)])[0].items.get().unit_price, D('150'))

    def test_idempotency_key_prevents_duplicates(self):
        first, created1 = self.sell(idempotency_key='k-1')
        second, created2 = self.sell(idempotency_key='k-1')
        self.assertEqual((created1, created2, first.pk), (True, False, second.pk))
        self.assertEqual((Sale.objects.count(), qty(self.a)), (1, 8))
        third, created3 = self.sell(idempotency_key='k-2')
        self.assertTrue(created3 and third.pk != first.pk)


class VoidSaleTests(SaleFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.sale, _ = create_sale(self.seller, [(self.a, 3), (self.b, 2)], CASH)

    def test_returns_stock_and_marks_voided(self):
        voided = void_sale(self.sale, self.admin, 'se equivocó')
        self.assertEqual((qty(self.a), qty(self.b)), (10, 10))
        self.assertEqual((voided.status, voided.voided_by, voided.void_reason), ('anulada', self.admin, 'se equivocó'))
        self.assertIsNotNone(voided.voided_at)
        self.assertEqual(Sale.objects.get(pk=self.sale.pk).status, 'anulada')

    def test_reversal_is_one_linked_operation(self):
        void_sale(self.sale, self.admin, 'x')
        reversal = self.sale.stock_operations.get(reason='anulacion')
        self.assertEqual((reversal.kind, reversal.movements.count(), reversal.note), ('ingreso', 2, f'Anulación de venta #{self.sale.pk}'))
        self.assertEqual(self.sale.stock_operations.count(), 2)

    def test_cannot_void_twice(self):
        void_sale(self.sale, self.admin, 'x')
        with self.assertRaises(SaleError):
            void_sale(self.sale, self.admin, 'x')
        self.assertEqual(qty(self.a), 10)  # no devolvió dos veces

    def test_reason_is_required(self):
        for reason in ('', '   ', None):
            with self.subTest(reason=reason), self.assertRaises(SaleError):
                void_sale(self.sale, self.admin, reason)
        self.assertEqual(Sale.objects.get(pk=self.sale.pk).status, 'completada')

    def test_blocked_by_active_exchange_but_not_by_a_voided_one(self):
        exchange = Exchange.objects.create(sale=self.sale, returned_total=D('0'), new_total=D('0'), difference=D('0'))
        with self.assertRaises(SaleError):
            void_sale(self.sale, self.admin, 'x')
        self.assertEqual(qty(self.a), 7)
        exchange.status = Exchange.Status.ANULADA
        exchange.save()
        void_sale(self.sale, self.admin, 'x')
        self.assertEqual(qty(self.a), 10)


class ConcurrentSaleTests(SaleFixtureMixin, TransactionTestCase):
    def run_in_threads(self, work):
        results, barrier = [], threading.Barrier(2)

        def worker():
            try:
                barrier.wait()
                results.append(work())
            except Exception as exc:  # noqa: BLE001 - se informa el tipo
                results.append(type(exc).__name__)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def test_two_sales_of_the_last_unit_only_one_wins(self):
        v = self.make(color=self.blue, size=self.s)
        apply_movements([(v, 1)], StockMovement.INGRESO, StockMovement.COMPRA)
        results = self.run_in_threads(lambda: create_sale(self.seller, [(v, 1)], CASH)[1])
        self.assertEqual(sorted(map(str, results)), ['InsufficientStock', 'True'])
        self.assertEqual((qty(v), Sale.objects.filter(items__variant=v).count()), (0, 1))

    def test_double_void_returns_stock_once(self):
        sale, _ = create_sale(self.seller, [(self.a, 3)], CASH)
        results = self.run_in_threads(lambda: void_sale(sale, self.admin, 'x').status)
        self.assertEqual(sorted(results), ['SaleError', 'anulada'])
        self.assertEqual(qty(self.a), 10)

    def test_same_idempotency_key_in_parallel_creates_one_sale(self):
        results = self.run_in_threads(lambda: create_sale(self.seller, [(self.a, 1)], CASH, idempotency_key='dup')[1])
        self.assertEqual(sorted(map(str, results)), ['False', 'True'])
        self.assertEqual((Sale.objects.count(), qty(self.a)), (1, 9))
