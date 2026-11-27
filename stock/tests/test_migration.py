from datetime import timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class GroupExistingMovementsMigrationTests(TransactionTestCase):
    """0002 agrupa en operaciones los movimientos que ya existían."""

    migrate_from = [('stock', '0001_initial')]
    migrate_to = [('stock', '0002_operations')]

    def setUp(self):
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.migrate_from)

    def tearDown(self):
        MigrationExecutor(connection).loader.build_graph()
        MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def test_groups_batches_counts_and_reversals(self):
        apps = self.executor.loader.project_state(self.migrate_from).apps
        Category, Product, Color, Size, Variant = (apps.get_model('products', n) for n in ('Category', 'Product', 'Color', 'Size', 'ProductVariant'))
        Movement, Count = apps.get_model('stock', 'StockMovement'), apps.get_model('stock', 'StockCount')
        cat = Category.objects.create(name='Vestidos', slug='vestidos')
        prod = Product.objects.create(name='Aurora', slug='aurora', category=cat, sale_price=100)
        color, size = Color.objects.create(name='Azul', hex='#14284B'), Size.objects.create(name='S', order=1)
        variants = [
            Variant.objects.create(product=prod, color=Color.objects.create(name=f'C{i}', hex='#000000'), size=size, sku=f'CHAR-{i:04d}')
            for i in range(3)
        ]
        now = timezone.now()
        count = Count.objects.create(status='confirmado')

        def mv(variant, kind, reason, qty, note='', **kw):
            before = max(0, -qty)  # cumple stock_after = stock_before + quantity
            return Movement.objects.create(
                variant=variant, kind=kind, reason=reason, quantity=qty, stock_before=before, stock_after=before + qty,
                note=note, **kw,
            )

        lote = [mv(v, 'ingreso', 'compra', 5, 'Pedido') for v in variants]            # un lote de 3 líneas
        otro = mv(variants[0], 'ingreso', 'compra', 2, 'Pedido')                      # misma variante: otro lote
        ajustes = [mv(variants[0], 'ajuste', 'recuento', 1, stock_count=count), mv(variants[1], 'ajuste', 'recuento', 1, stock_count=count)]
        anulacion = mv(variants[2], 'egreso', 'anulacion', -5, reverses=lote[2])
        Movement.objects.filter(pk=otro.pk).update(created_at=now + timedelta(minutes=10))

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        apps = executor.loader.project_state(self.migrate_to).apps
        Movement, Operation = apps.get_model('stock', 'StockMovement'), apps.get_model('stock', 'StockOperation')
        op = lambda m: Movement.objects.get(pk=m.pk).operation_id

        self.assertEqual(len({op(m) for m in lote}), 1)                      # el lote queda agrupado
        self.assertNotEqual(op(otro), op(lote[0]))                           # lejos en el tiempo: otra operación
        self.assertEqual(len({op(m) for m in ajustes}), 1)                   # el recuento comparte operación
        self.assertEqual(Operation.objects.get(pk=op(ajustes[0])).stock_count_id, count.pk)
        self.assertNotIn(op(anulacion), {op(m) for m in lote})               # la anulación va sola
        self.assertEqual(Movement.objects.filter(operation__isnull=True).count(), 0)
        self.assertEqual(Operation.objects.count(), 4)
