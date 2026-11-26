from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from products.models import Brand, Category, Product, ProductModel
from users.models import User

TODAY = date(2026, 12, 15)


def _today():
    return mock.patch('django.utils.timezone.localdate', return_value=TODAY)


class ProductFixtureMixin:
    def setUp(self):
        super().setUp()
        self.dresses = Category.objects.create(name='Vestidos')
        self.long = Category.objects.create(name='Largos', parent=self.dresses)
        self.short = Category.objects.create(name='Cortos', parent=self.dresses)
        self.clothes = Category.objects.create(name='Indumentaria')
        self.blouses = Category.objects.create(name='Blusas', parent=self.clothes)
        self.brand = Brand.objects.create(name='X')
        self.model = ProductModel.objects.create(brand=self.brand, name='Aurora')

    def make(self, **kw):
        data = {'name': 'Vestido', 'category': self.long, 'sale_price': Decimal('100')}
        data.update(kw)
        return Product.objects.create(**data)


class ProductModelTests(ProductFixtureMixin, TestCase):
    def test_current_price_without_promo(self):
        self.assertEqual(self.make().get_current_price(TODAY), Decimal('100'))

    def test_current_price_inside_promo_range_inclusive(self):
        p = self.make(promo_price=Decimal('80'), promo_start=date(2026, 12, 15), promo_end=date(2026, 12, 15))
        self.assertTrue(p.is_on_promo(TODAY))
        self.assertEqual(p.get_current_price(TODAY), Decimal('80'))

    def test_current_price_outside_promo_range(self):
        p = self.make(promo_price=Decimal('80'), promo_start=date(2026, 12, 16), promo_end=date(2026, 12, 31))
        self.assertEqual(p.get_current_price(TODAY), Decimal('100'))
        p.promo_start, p.promo_end = date(2026, 12, 1), date(2026, 12, 14)
        self.assertEqual(p.get_current_price(TODAY), Decimal('100'))

    def test_db_rejects_partial_promo(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make(promo_price=Decimal('80'))

    def test_db_rejects_inverted_range(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make(promo_price=Decimal('80'), promo_start=date(2026, 12, 20), promo_end=date(2026, 12, 1))

    def test_clean_rejects_promo_not_lower_than_sale(self):
        p = Product(name='V', category=self.long, sale_price=Decimal('100'),
                    promo_price=Decimal('100'), promo_start=TODAY, promo_end=TODAY)
        with self.assertRaises(ValidationError) as ctx:
            p.clean()
        self.assertIn('promo_price', ctx.exception.message_dict)

    def test_clean_rejects_non_leaf_category(self):
        with self.assertRaises(ValidationError):
            Product(name='V', category=self.dresses, sale_price=Decimal('1')).clean()

    def test_clean_rejects_model_of_other_brand(self):
        other = Brand.objects.create(name='Y')
        with self.assertRaises(ValidationError):
            Product(name='V', category=self.long, sale_price=Decimal('1'), brand=other,
                    product_model=self.model).clean()


class ProductApiTests(ProductFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.admin = User.objects.create_superuser(email='admin@example.com', password='pass12345')
        self.api.force_authenticate(self.admin)

    def payload(self, **kw):
        data = {'name': 'Aurora', 'category': self.long.pk, 'sale_price': '90000.00', 'cost_price': '40000.00'}
        data.update(kw)
        return data

    def post(self, **kw):
        return self.api.post('/api/products/', self.payload(**kw), format='json')

    def test_create_minimal_without_brand_model_or_cost(self):
        data = {'name': 'Blusa', 'category': self.blouses.pk, 'sale_price': '100.00'}
        response = self.api.post('/api/products/', data, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(response.data['brand'])
        self.assertEqual(Product.objects.get(pk=response.data['id']).created_by, self.admin)

    def test_rejects_non_leaf_category(self):
        response = self.post(category=self.dresses.pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn('category', response.data)

    def test_brand_derived_from_model(self):
        response = self.post(product_model=self.model.pk)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['brand'], self.brand.pk)

    def test_rejects_model_from_other_brand(self):
        other = Brand.objects.create(name='Y')
        response = self.post(brand=other.pk, product_model=self.model.pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn('product_model', response.data)

    def test_rejects_negative_price(self):
        self.assertEqual(self.post(sale_price='-1').status_code, 400)

    def test_promo_requires_all_three_fields(self):
        self.assertEqual(self.post(promo_price='1000.00').status_code, 400)
        self.assertEqual(self.post(promo_start='2026-12-01').status_code, 400)

    def test_promo_range_and_price_validated(self):
        bad_range = self.post(promo_price='1.00', promo_start='2026-12-20', promo_end='2026-12-01')
        self.assertEqual(bad_range.status_code, 400)
        not_lower = self.post(promo_price='90000.00', promo_start='2026-12-01', promo_end='2026-12-31')
        self.assertEqual(not_lower.status_code, 400)

    def test_patch_validates_against_existing_values(self):
        p = self.make(sale_price=Decimal('100'))
        response = self.api.patch(
            f'/api/products/{p.pk}/',
            {'promo_price': '150.00', 'promo_start': '2026-12-01', 'promo_end': '2026-12-31'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_patch_can_clear_promo(self):
        p = self.make(promo_price=Decimal('80'), promo_start=TODAY, promo_end=TODAY)
        response = self.api.patch(
            f'/api/products/{p.pk}/',
            {'promo_price': None, 'promo_start': None, 'promo_end': None},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_current_price_in_response(self):
        self.make(name='Con promo', promo_price=Decimal('80'), promo_start=date(2026, 12, 1), promo_end=date(2026, 12, 31))
        with _today():
            response = self.api.get('/api/products/')
        item = response.data['results'][0]
        self.assertEqual(item['current_price'], '80.00')
        self.assertTrue(item['is_on_promo'])

    def test_filter_by_root_category_includes_children(self):
        a = self.make(name='A', category=self.long)
        b = self.make(name='B', category=self.short)
        self.make(name='C', category=self.blouses)
        ids = lambda q: {r['id'] for r in self.api.get('/api/products/', q).data['results']}  # noqa: E731
        self.assertEqual(ids({'category': self.dresses.pk}), {a.pk, b.pk})
        self.assertEqual(ids({'category': self.long.pk}), {a.pk})

    def test_filter_by_brand_and_model(self):
        a = self.make(name='A', brand=self.brand, product_model=self.model)
        self.make(name='B')
        ids = lambda q: {r['id'] for r in self.api.get('/api/products/', q).data['results']}  # noqa: E731
        self.assertEqual(ids({'brand': self.brand.pk}), {a.pk})
        self.assertEqual(ids({'product_model': self.model.pk}), {a.pk})

    def test_filter_on_promo_and_price_range(self):
        promo = self.make(name='P', sale_price=Decimal('100'), promo_price=Decimal('50'),
                          promo_start=date(2026, 12, 1), promo_end=date(2026, 12, 31))
        expired = self.make(name='E', sale_price=Decimal('100'), promo_price=Decimal('50'),
                            promo_start=date(2026, 1, 1), promo_end=date(2026, 1, 31))
        plain = self.make(name='N', sale_price=Decimal('70'))
        ids = lambda q: {r['id'] for r in self.api.get('/api/products/', q).data['results']}  # noqa: E731
        with _today():
            self.assertEqual(ids({'on_promo': 'true'}), {promo.pk})
            self.assertEqual(ids({'on_promo': 'false'}), {expired.pk, plain.pk})
            self.assertEqual(ids({'max_price': '60'}), {promo.pk})
            self.assertEqual(ids({'min_price': '60', 'max_price': '80'}), {plain.pk})

    def test_cannot_delete_catalog_entries_in_use(self):
        self.make(brand=self.brand, product_model=self.model)
        self.assertEqual(self.api.delete(f'/api/categories/{self.long.pk}/').status_code, 400)
        self.assertEqual(self.api.delete(f'/api/product-models/{self.model.pk}/').status_code, 400)
        self.assertEqual(self.api.delete(f'/api/brands/{self.brand.pk}/').status_code, 400)

    def test_cannot_add_subcategory_under_category_with_products(self):
        self.make()
        response = self.api.post('/api/categories/', {'name': 'Fiesta', 'parent': self.long.pk}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_delete_and_restore(self):
        p = self.make()
        self.assertEqual(self.api.delete(f'/api/products/{p.pk}/').status_code, 204)
        self.assertTrue(Product.all_objects.get(pk=p.pk).is_deleted)
        self.assertEqual(self.api.post(f'/api/products/{p.pk}/restore/').status_code, 200)


class ProductCostPermissionTests(ProductFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.user = User.objects.create_user(email='member@example.com', password='pass12345')
        self.product = self.make(cost_price=Decimal('40'))

    def grant(self, *codenames):
        group = Group.objects.create(name='g_' + '_'.join(codenames))
        group.permissions.set(Permission.objects.filter(content_type__app_label='products', codename__in=codenames))
        self.user.groups.add(group)
        self.user = User.objects.get(pk=self.user.pk)
        self.api.force_authenticate(self.user)

    def test_cost_hidden_without_permission(self):
        self.grant('view_product')
        response = self.api.get(f'/api/products/{self.product.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('cost_price', response.data)
        self.assertIn('sale_price', response.data)

    def test_cost_visible_with_permission(self):
        self.grant('view_product', 'view_cost_price')
        response = self.api.get(f'/api/products/{self.product.pk}/')
        self.assertEqual(response.data['cost_price'], '40.00')

    def test_cost_ignored_on_write_without_permission(self):
        self.grant('view_product', 'change_product')
        response = self.api.patch(f'/api/products/{self.product.pk}/', {'cost_price': '1.00'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.cost_price, Decimal('40'))

    def test_cost_writable_with_permission(self):
        self.grant('view_product', 'change_product', 'view_cost_price')
        self.api.patch(f'/api/products/{self.product.pk}/', {'cost_price': '55.00'}, format='json')
        self.product.refresh_from_db()
        self.assertEqual(self.product.cost_price, Decimal('55'))

    def test_vendedor_role_cannot_see_cost_but_administrador_can(self):
        from io import StringIO
        from django.core.management import call_command
        call_command('seed_roles', stdout=StringIO(), stderr=StringIO())
        names = lambda role: set(Group.objects.get(name=role).permissions.values_list('codename', flat=True))  # noqa: E731
        self.assertIn('view_product', names('Vendedor'))
        self.assertNotIn('view_cost_price', names('Vendedor'))
        self.assertIn('view_cost_price', names('Administrador'))
