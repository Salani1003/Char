import threading

from django.db import connection
from django.test import TestCase, TransactionTestCase

from products.tests.test_variants import VariantFixtureMixin
from stock.exceptions import InsufficientStock, StockError
from stock.models import StockLevel, StockMovement, StockOperation
from stock.services import apply_movement, apply_movements
from users.models import User

I, E, A = StockMovement.INGRESO, StockMovement.EGRESO, StockMovement.AJUSTE


def qty(variant):
    level = StockLevel.objects.filter(variant=variant).first()
    return level.quantity if level else 0


class ApplyMovementTests(VariantFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.v = self.make()
        self.user = User.objects.create_user(email='a@test.com', password='x')

    def test_ingreso_creates_level_and_movement(self):
        m = apply_movement(self.v, I, 5, StockMovement.COMPRA, user=self.user, note='lote 1')
        self.assertEqual(qty(self.v), 5)
        self.assertEqual((m.stock_before, m.stock_after, m.quantity), (0, 5, 5))
        self.assertEqual(m.created_by, self.user)
        self.assertEqual(m.note, 'lote 1')

    def test_egreso_subtracts(self):
        apply_movement(self.v, I, 5, StockMovement.COMPRA)
        m = apply_movement(self.v, E, -2, StockMovement.ROTURA_MERMA)
        self.assertEqual(qty(self.v), 3)
        self.assertEqual((m.stock_before, m.stock_after), (5, 3))

    def test_ajuste_accepts_either_sign(self):
        apply_movement(self.v, I, 5, StockMovement.COMPRA)
        apply_movement(self.v, A, -3, StockMovement.RECUENTO)
        apply_movement(self.v, A, 4, StockMovement.CORRECCION)
        self.assertEqual(qty(self.v), 6)

    def test_cannot_go_negative(self):
        apply_movement(self.v, I, 2, StockMovement.COMPRA)
        with self.assertRaises(InsufficientStock) as ctx:
            apply_movement(self.v, E, -3, StockMovement.PERDIDA)
        self.assertEqual(ctx.exception.available, 2)
        self.assertEqual(qty(self.v), 2)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_egreso_without_level_is_insufficient(self):
        with self.assertRaises(InsufficientStock):
            apply_movement(self.v, E, -1, StockMovement.PERDIDA)

    def test_ajuste_cannot_go_negative(self):
        apply_movement(self.v, I, 2, StockMovement.COMPRA)
        with self.assertRaises(InsufficientStock):
            apply_movement(self.v, A, -3, StockMovement.CORRECCION)

    def test_invalid_inputs(self):
        for kind, delta, reason in [
            ('otro', 1, StockMovement.COMPRA),
            (I, 0, StockMovement.COMPRA),
            (I, -1, StockMovement.COMPRA),
            (E, 1, StockMovement.PERDIDA),
            (I, 1, StockMovement.PERDIDA),      # motivo de egreso en un ingreso
            (E, -1, StockMovement.COMPRA),      # motivo de ingreso en un egreso
            (A, 1, StockMovement.COMPRA),
        ]:
            with self.subTest(kind=kind, delta=delta, reason=reason), self.assertRaises(StockError):
                apply_movement(self.v, kind, delta, reason)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_deleted_variant_rejected(self):
        self.v.delete()
        with self.assertRaises(StockError):
            apply_movement(self.v, I, 1, StockMovement.COMPRA)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_exchange_reasons_allowed(self):
        apply_movement(self.v, I, 1, StockMovement.CAMBIO_ENTRADA)
        apply_movement(self.v, E, -1, StockMovement.CAMBIO_SALIDA)
        self.assertEqual(qty(self.v), 0)


class ApplyMovementsBatchTests(VariantFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.a = self.make()
        self.b = self.make(color=self.red)

    def test_batch_ingreso(self):
        op = apply_movements([(self.a, 3), (self.b, 4)], I, StockMovement.STOCK_INICIAL, note='n')
        self.assertEqual(op.movements.count(), 2)
        self.assertEqual({(m.kind, m.reason, m.note) for m in op.movements.all()}, {('ingreso', 'stock_inicial', 'n')})
        self.assertEqual((qty(self.a), qty(self.b)), (3, 4))

    def test_batch_is_atomic(self):
        apply_movement(self.a, I, 5, StockMovement.COMPRA)
        with self.assertRaises(InsufficientStock):
            apply_movements([(self.a, 2), (self.b, 1)], E, StockMovement.PERDIDA)
        self.assertEqual(qty(self.a), 5)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(StockOperation.objects.count(), 1)  # la del lote fallido se revirtió

    def test_single_movement_gets_its_own_operation(self):
        m = apply_movement(self.a, I, 2, StockMovement.COMPRA)
        self.assertEqual((m.operation.kind, m.operation.reason, m.operation.movements.count()), ('ingreso', 'compra', 1))

    def test_batch_rejects_reason_of_the_other_kind(self):
        with self.assertRaises(StockError):
            apply_movements([(self.a, 1)], I, StockMovement.PERDIDA)

    def test_duplicate_variant_rejected(self):
        with self.assertRaises(StockError):
            apply_movements([(self.a, 1), (self.a, 2)], I, StockMovement.COMPRA)

    def test_empty_and_nonpositive_rejected(self):
        with self.assertRaises(StockError):
            apply_movements([], I, StockMovement.COMPRA)
        with self.assertRaises(StockError):
            apply_movements([(self.a, 0)], I, StockMovement.COMPRA)

    def test_batch_rejects_ajuste(self):
        with self.assertRaises(StockError):
            apply_movements([(self.a, 1)], A, StockMovement.RECUENTO)


class ConcurrencyTests(VariantFixtureMixin, TransactionTestCase):
    def test_two_simultaneous_egresos_on_last_unit(self):
        v = self.make()
        apply_movement(v, I, 1, StockMovement.COMPRA)
        results = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                barrier.wait()
                apply_movement(v, E, -1, StockMovement.PERDIDA)
                results.append('ok')
            except InsufficientStock:
                results.append('insufficient')
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), ['insufficient', 'ok'])
        self.assertEqual(qty(v), 0)


class ConcurrentConfirmTests(VariantFixtureMixin, TransactionTestCase):
    def test_double_confirm_applies_adjustment_once(self):
        from stock.models import StockCount, StockCountItem
        from stock.services import confirm_count

        v = self.make()
        apply_movement(v, I, 5, StockMovement.COMPRA)
        count = StockCount.objects.create()
        StockCountItem.objects.create(count=count, variant=v, counted_quantity=3)
        results = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                barrier.wait()
                confirm_count(count)
                results.append('ok')
            except StockError:
                results.append('error')
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), ['error', 'ok'])
        self.assertEqual(qty(v), 3)
        self.assertEqual(StockMovement.objects.filter(operation__stock_count=count).count(), 1)
