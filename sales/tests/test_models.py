from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from products.tests.test_variants import VariantFixtureMixin
from sales.models import Exchange, ExchangeItem, PaymentMethod, Sale, SaleItem
from stock.exceptions import StockError
from stock.models import StockMovement
from stock.services import apply_movements, reverse_movement, reverse_operation

D = Decimal
I, E = StockMovement.INGRESO, StockMovement.EGRESO


def make_sale(**kw):
    data = {'payment_method': PaymentMethod.EFECTIVO, 'subtotal': D('100'), 'total': D('100')}
    data.update(kw)
    return Sale.objects.create(**data)


class SalesModelTests(VariantFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.v = self.make()
        self.sale = make_sale()

    def assertViolates(self, create):
        with self.assertRaises(IntegrityError), transaction.atomic():
            create()

    def test_defaults(self):
        self.assertEqual((self.sale.status, self.sale.discount_percent, self.sale.client), ('completada', 0, None))
        self.assertEqual(str(self.sale), f'Venta #{self.sale.pk}')

    def test_sale_constraints(self):
        self.assertViolates(lambda: make_sale(total=D('-1')))
        self.assertViolates(lambda: make_sale(discount_percent=101))

    def test_idempotency_key_is_unique_but_optional(self):
        make_sale(idempotency_key='abc')
        make_sale()
        make_sale()  # varias sin clave
        self.assertViolates(lambda: make_sale(idempotency_key='abc'))

    def item(self, **kw):
        data = {'sale': self.sale, 'variant': self.v, 'quantity': 2, 'list_price': D('50'), 'unit_price': D('50'), 'subtotal': D('100')}
        data.update(kw)
        return SaleItem.objects.create(**data)

    def test_item_constraints(self):
        self.item()
        self.assertViolates(self.item)  # misma variante dos veces en la venta
        other = self.make(color=self.red)
        self.assertViolates(lambda: self.item(variant=other, quantity=0))
        self.assertViolates(lambda: self.item(variant=other, exchanged_quantity=3))

    def test_exchange_constraints(self):
        make = lambda **kw: Exchange.objects.create(**{
            'sale': self.sale, 'returned_total': D('50'), 'new_total': D('80'), 'difference': D('30'), **kw,
        })
        ok = make(payment_method=PaymentMethod.QR)
        self.assertEqual(ok.unreturned_amount, 0)
        # Con diferencia <= 0 no puede haber medio de pago (que falte con diferencia > 0 lo valida el servicio).
        self.assertViolates(lambda: make(difference=D('0'), payment_method=PaymentMethod.QR))
        short = make(difference=D('-20'), new_total=D('30'), payment_method='')
        self.assertEqual(short.unreturned_amount, D('20'))

    def test_exchange_item_sale_item_only_when_returning(self):
        item = self.item()
        ex = Exchange.objects.create(
            sale=self.sale, returned_total=D('50'), new_total=D('50'), difference=D('0'),
        )
        make = lambda **kw: ExchangeItem.objects.create(
            **{'exchange': ex, 'variant': self.v, 'quantity': 1, 'unit_price': D('50'), **kw}
        )
        make(direction='in', sale_item=item)
        make(direction='out')
        self.assertViolates(lambda: make(direction='in'))
        self.assertViolates(lambda: make(direction='out', sale_item=item))
        self.assertViolates(lambda: make(direction='out', quantity=0))


class StockLinkTests(VariantFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.a = self.make()
        apply_movements([(self.a, 10)], I, StockMovement.COMPRA)
        self.sale = make_sale()

    def test_operation_is_linked_to_its_sale(self):
        op = apply_movements([(self.a, 2)], E, StockMovement.VENTA, sale=self.sale)
        self.assertEqual(list(self.sale.stock_operations.all()), [op])

    def test_reversal_inherits_the_link(self):
        op = apply_movements([(self.a, 2)], E, StockMovement.VENTA, sale=self.sale)
        reversal = reverse_operation(op)
        self.assertEqual(reversal.sale_id, self.sale.pk)
        self.assertEqual(self.sale.stock_operations.count(), 2)

    def test_single_line_of_a_sale_cannot_be_reversed_alone(self):
        op = apply_movements([(self.a, 2)], E, StockMovement.VENTA, sale=self.sale)
        with self.assertRaises(StockError):
            reverse_movement(op.movements.get())
        self.assertEqual(StockMovement.objects.filter(reason='anulacion').count(), 0)

    def test_linked_operations_appear_in_the_history_api(self):
        from rest_framework.test import APIClient
        from users.models import User

        op = apply_movements([(self.a, 2)], E, StockMovement.VENTA, sale=self.sale)
        api = APIClient()
        api.force_authenticate(User.objects.create_superuser(email='root@test.com', password='x'))
        res = api.get(f'/api/stock-operations/?sale={self.sale.pk}').data['results']
        self.assertEqual([(r['id'], r['sale'], r['exchange']) for r in res], [(op.pk, self.sale.pk, None)])
