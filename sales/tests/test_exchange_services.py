import threading
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from products.models import Product, ProductVariant
from sales.exceptions import SaleError
from sales.models import Exchange, ExchangeItem, PaymentMethod, Sale, SaleItem
from sales.services import create_exchange, create_sale, preview_exchange, void_exchange, void_sale
from sales.tests.test_services import SaleFixtureMixin, qty
from stock.exceptions import InsufficientStock
from stock.models import StockMovement, StockOperation
from stock.services import apply_movements

D = Decimal
CASH, QR = PaymentMethod.EFECTIVO, PaymentMethod.QR


class ExchangeFixtureMixin(SaleFixtureMixin):
    def setUp(self):
        super().setUp()
        # self.a / self.b: $100 (producto Aurora). Dos productos más para cambiar por algo más caro o más barato.
        self.dear = self.variant_of('Abrigo', D('150'))
        self.cheap = self.variant_of('Remera', D('40'))
        self.sale, _ = create_sale(self.seller, [(self.a, 2), (self.b, 1)], CASH)

    def variant_of(self, name, price, stock=10):
        product = Product.objects.create(name=name, category=self.category, sale_price=price)
        variant = ProductVariant.objects.create(product=product, color=self.blue, size=self.m)
        if stock:
            apply_movements([(variant, stock)], StockMovement.INGRESO, StockMovement.COMPRA)
        return variant

    def item(self, variant, sale=None):
        return (sale or self.sale).items.get(variant=variant)

    def exchange(self, returned=None, new=None, **kw):
        returned = [(self.item(self.a), 1)] if returned is None else returned
        new = [(self.dear, 1)] if new is None else new
        kw.setdefault('payment_method', CASH)
        return create_exchange(self.seller, self.sale, returned, new, **kw)

    def exchanged(self, variant):
        return SaleItem.objects.get(pk=self.item(variant).pk).exchanged_quantity


class CreateExchangeTests(ExchangeFixtureMixin, TestCase):
    def test_exchange_for_something_dearer_moves_stock_and_records_difference(self):
        ex = self.exchange(note='talle')
        self.assertEqual((ex.status, ex.sale, ex.created_by, ex.note), ('completada', self.sale, self.seller, 'talle'))
        self.assertEqual((ex.returned_total, ex.new_total, ex.difference, ex.unreturned_amount, ex.payment_method),
                         (D('100'), D('150'), D('50'), 0, CASH))
        self.assertEqual((qty(self.a), qty(self.dear)), (9, 9))  # a: 10 − 2 vendidas + 1 devuelta
        self.assertEqual(self.exchanged(self.a), 1)
        self.assertEqual(self.sale.status, 'completada')  # la venta original no cambia
        self.assertEqual(Sale.objects.get(pk=self.sale.pk).total, D('300'))

    def test_two_linked_operations(self):
        ex = self.exchange()
        ops = {op.reason: op for op in ex.stock_operations.all()}
        self.assertEqual(set(ops), {'cambio_entrada', 'cambio_salida'})
        self.assertEqual((ops['cambio_entrada'].kind, ops['cambio_salida'].kind), ('ingreso', 'egreso'))
        self.assertEqual(ops['cambio_entrada'].note, f'Cambio #{ex.pk} (venta #{self.sale.pk})')
        self.assertEqual((ops['cambio_entrada'].movements.get().quantity, ops['cambio_salida'].movements.get().quantity), (1, -1))
        self.assertTrue(all(op.sale_id is None for op in ops.values()))  # enlazadas al cambio, no a la venta

    def test_items_are_recorded_with_prices(self):
        ex = self.exchange()
        back, out = ex.items.order_by('direction', 'id')[0], ex.items.order_by('direction', 'id')[1]
        self.assertEqual((back.direction, back.variant, back.unit_price, back.sale_item), ('in', self.a, D('100'), self.item(self.a)))
        self.assertEqual((out.direction, out.variant, out.unit_price, out.sale_item), ('out', self.dear, D('150'), None))

    def test_payment_method_required_when_there_is_a_difference_to_pay(self):
        for method in ('', 'cheque'):
            with self.subTest(method=method), self.assertRaises(SaleError):
                self.exchange(payment_method=method)
        self.assertEqual((Exchange.objects.count(), qty(self.dear), self.exchanged(self.a)), (0, 10, 0))

    def test_same_value_has_no_payment(self):
        ex = self.exchange(new=[(self.b, 1)], payment_method=QR)  # a (100) por b (100); QR se ignora
        self.assertEqual((ex.difference, ex.payment_method, ex.unreturned_amount), (0, '', 0))

    def test_cheaper_exchange_closes_without_refund(self):
        ex = self.exchange(new=[(self.cheap, 1)], payment_method='')
        self.assertEqual((ex.difference, ex.payment_method, ex.unreturned_amount), (D('-60'), '', D('60')))
        self.assertEqual((qty(self.cheap), self.exchanged(self.a)), (9, 1))

    def test_exchange_without_new_items(self):
        ex = self.exchange(new=[])
        self.assertEqual((ex.new_total, ex.difference, ex.unreturned_amount, ex.payment_method), (0, D('-100'), D('100'), ''))
        self.assertEqual(ex.stock_operations.count(), 1)  # sólo el ingreso
        self.assertEqual(qty(self.a), 9)

    def test_returned_items_are_valued_at_what_was_paid(self):
        sale, _ = create_sale(self.admin, [(self.a, 1)], CASH, discount_percent=10)  # pagó 90
        self.product.sale_price = D('500')
        self.product.save()  # el precio de lista cambia después
        ex = create_exchange(self.seller, sale, [(sale.items.get(), 1)], [(self.dear, 1)], CASH)
        self.assertEqual((ex.returned_total, ex.new_total, ex.difference), (D('90.00'), D('150'), D('60.00')))

    def test_new_items_use_current_price_with_promo_and_no_discount(self):
        today = timezone.localdate()
        promo = self.dear.product
        promo.promo_price, promo.promo_start, promo.promo_end = D('120'), today, today + timedelta(days=3)
        promo.save()
        self.assertEqual(self.exchange().new_total, D('120'))

    def test_partial_exchange_leaves_other_items_alone(self):
        self.exchange()  # devuelve 1 de las 2 unidades de `a`
        self.assertEqual((self.exchanged(self.a), self.exchanged(self.b)), (1, 0))
        self.assertEqual(Sale.objects.get(pk=self.sale.pk).status, 'completada')

    def test_successive_exchanges_consume_the_remaining_units(self):
        self.exchange()
        self.exchange(new=[(self.cheap, 1)])  # la segunda y última unidad de `a`
        self.assertEqual(self.exchanged(self.a), 2)
        with self.assertRaises(SaleError):
            self.exchange(new=[(self.cheap, 1)])
        self.assertEqual((qty(self.cheap), Exchange.objects.count()), (9, 2))

    def test_cannot_return_more_than_available(self):
        with self.assertRaises(SaleError) as ctx:
            self.exchange(returned=[(self.item(self.a), 3)])
        self.assertIn('returned_items', ctx.exception.detail)
        self.assertEqual(Exchange.objects.count(), 0)

    def test_item_from_another_sale_rejected(self):
        other, _ = create_sale(self.seller, [(self.a, 1)], CASH)
        with self.assertRaises(SaleError):
            self.exchange(returned=[(self.item(self.a, other), 1)])

    def test_input_validation(self):
        a = self.item(self.a)
        for kwargs in (
            {'returned': []},
            {'returned': [(a, 1), (a, 1)]},
            {'returned': [(a, 0)]},
            {'new': [(self.dear, 1), (self.dear, 1)]},
            {'new': [(self.dear, 0)]},
            {'new': [(self.a, 1)]},  # cambiar una variante por sí misma
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(SaleError):
                self.exchange(**kwargs)
        self.assertEqual((Exchange.objects.count(), qty(self.a), qty(self.dear)), (0, 8, 10))

    def test_no_stock_for_the_new_item_rolls_everything_back(self):
        scarce = self.variant_of('Chaleco', D('300'), stock=0)
        with self.assertRaises(InsufficientStock):
            self.exchange(new=[(scarce, 1)])
        self.assertEqual((Exchange.objects.count(), qty(self.a), self.exchanged(self.a)), (0, 8, 0))  # el ingreso se revirtió
        self.assertEqual(StockOperation.objects.filter(reason='cambio_entrada').count(), 0)

    def test_deadline(self):
        def age(days):
            Sale.objects.filter(pk=self.sale.pk).update(created_at=timezone.now() - timedelta(days=days))
            self.sale.refresh_from_db()

        age(31)
        with self.assertRaises(SaleError) as ctx:
            self.exchange()
        self.assertIn('plazo', str(ctx.exception.detail['detail']))
        age(30)  # el último día todavía vale
        self.exchange()

    def test_voided_sale_cannot_be_exchanged(self):
        sale, _ = create_sale(self.seller, [(self.a, 1)], CASH)
        void_sale(sale, self.admin, 'x')
        with self.assertRaises(SaleError):
            create_exchange(self.seller, sale, [(sale.items.get(), 1)], [(self.dear, 1)], CASH)


class PreviewExchangeTests(ExchangeFixtureMixin, TestCase):
    def preview(self, returned=None, new=None):
        returned = [(self.item(self.a), 1)] if returned is None else returned
        new = [(self.dear, 1)] if new is None else new
        return preview_exchange(self.sale, returned, new)

    def test_numbers(self):
        self.assertEqual(self.preview(), {
            'returned_total': D('100'), 'new_total': D('150'), 'difference': D('50'), 'unreturned_amount': D('0'),
        })
        self.assertEqual(self.preview(new=[(self.cheap, 1)])['unreturned_amount'], D('60'))
        self.assertEqual(self.preview(new=[])['unreturned_amount'], D('100'))

    def test_matches_what_create_records(self):
        preview = self.preview(new=[(self.cheap, 2)])
        ex = self.exchange(new=[(self.cheap, 2)])
        self.assertEqual(preview, {
            'returned_total': ex.returned_total, 'new_total': ex.new_total,
            'difference': ex.difference, 'unreturned_amount': ex.unreturned_amount,
        })

    def test_writes_nothing(self):
        before = (Exchange.objects.count(), StockOperation.objects.count(), qty(self.a), qty(self.dear))
        self.preview()
        self.assertEqual((Exchange.objects.count(), StockOperation.objects.count(), qty(self.a), qty(self.dear)), before)
        self.assertEqual(self.exchanged(self.a), 0)

    def test_same_rules_as_create(self):
        with self.assertRaises(SaleError):
            self.preview(returned=[(self.item(self.a), 5)])
        with self.assertRaises(SaleError):
            self.preview(returned=[])
        scarce = self.variant_of('Chaleco', D('300'), stock=0)
        with self.assertRaises(InsufficientStock):
            self.preview(new=[(scarce, 1)])
        Sale.objects.filter(pk=self.sale.pk).update(created_at=timezone.now() - timedelta(days=45))
        self.sale.refresh_from_db()
        with self.assertRaises(SaleError):
            self.preview()


class VoidExchangeTests(ExchangeFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.ex = self.exchange()

    def test_restores_stock_and_releases_units(self):
        voided = void_exchange(self.ex, self.admin, 'se arrepintió')
        self.assertEqual((qty(self.a), qty(self.dear)), (8, 10))
        self.assertEqual(self.exchanged(self.a), 0)
        self.assertEqual((voided.status, voided.voided_by, voided.void_reason), ('anulada', self.admin, 'se arrepintió'))
        self.assertIsNotNone(voided.voided_at)

    def test_reversals_are_linked_to_the_exchange(self):
        void_exchange(self.ex, self.admin, 'x')
        reversals = self.ex.stock_operations.filter(reason='anulacion')
        self.assertEqual(sorted(op.kind for op in reversals), ['egreso', 'ingreso'])
        self.assertEqual(self.ex.stock_operations.count(), 4)

    def test_units_can_be_exchanged_again_after_voiding(self):
        self.exchange()  # la segunda unidad de `a`
        with self.assertRaises(SaleError):
            self.exchange()
        void_exchange(self.ex, self.admin, 'x')
        self.exchange()

    def test_reason_required_and_no_double_void(self):
        for reason in ('', '  ', None):
            with self.subTest(reason=reason), self.assertRaises(SaleError):
                void_exchange(self.ex, self.admin, reason)
        void_exchange(self.ex, self.admin, 'x')
        with self.assertRaises(SaleError):
            void_exchange(self.ex, self.admin, 'x')
        self.assertEqual((qty(self.a), qty(self.dear)), (8, 10))

    def test_fails_atomically_if_returned_units_were_already_sold(self):
        create_sale(self.seller, [(self.a, qty(self.a))], CASH)  # se vende todo `a`, incluida la unidad devuelta
        with self.assertRaises(InsufficientStock):
            void_exchange(self.ex, self.admin, 'x')
        self.assertEqual((Exchange.objects.get(pk=self.ex.pk).status, self.exchanged(self.a), qty(self.dear)), ('completada', 1, 9))
        self.assertEqual(self.ex.stock_operations.count(), 2)  # ni siquiera quedó la anulación de lo que salió

    def test_sale_can_be_voided_only_after_its_exchange_is_voided(self):
        with self.assertRaises(SaleError):
            void_sale(self.sale, self.admin, 'x')
        void_exchange(self.ex, self.admin, 'x')
        void_sale(self.sale, self.admin, 'x')
        self.assertEqual(qty(self.a), 10)


class ConcurrentExchangeTests(ExchangeFixtureMixin, TransactionTestCase):
    def run_in_threads(self, *works):
        results, barrier = [], threading.Barrier(len(works))

        def worker(work):
            try:
                barrier.wait()
                work()
                results.append('ok')
            except Exception as exc:  # noqa: BLE001 - se informa el tipo
                results.append(type(exc).__name__)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(w,)) for w in works]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return sorted(results)

    def test_the_same_unit_cannot_be_exchanged_twice(self):
        item = self.item(self.b)  # una sola unidad
        work = lambda: create_exchange(self.seller, self.sale, [(item, 1)], [(self.cheap, 1)])
        self.assertEqual(self.run_in_threads(work, work), ['SaleError', 'ok'])
        self.assertEqual((self.exchanged(self.b), Exchange.objects.count(), qty(self.cheap)), (1, 1, 9))

    def test_exchange_and_void_sale_race_has_one_winner(self):
        item = self.item(self.b)
        results = self.run_in_threads(
            lambda: create_exchange(self.seller, self.sale, [(item, 1)], [(self.cheap, 1)]),
            lambda: void_sale(self.sale, self.admin, 'x'),
        )
        self.assertEqual(results, ['SaleError', 'ok'])
        sale = Sale.objects.get(pk=self.sale.pk)
        active = sale.exchanges.filter(status='completada').count()
        self.assertEqual((sale.status == 'anulada') + active, 1)  # o se anuló la venta o hay un cambio, nunca ambos

    def test_double_void_exchange_restores_once(self):
        ex = self.exchange()
        work = lambda: void_exchange(ex, self.admin, 'x')
        self.assertEqual(self.run_in_threads(work, work), ['SaleError', 'ok'])
        self.assertEqual((qty(self.a), qty(self.dear), self.exchanged(self.a)), (8, 10, 0))
