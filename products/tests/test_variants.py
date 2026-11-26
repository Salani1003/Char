from decimal import Decimal

from django.contrib.auth.models import Group, Permission
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from products.models import Category, Color, Product, ProductVariant, Size, SkuCounter
from users.models import User


class VariantFixtureMixin:
    def setUp(self):
        super().setUp()
        self.category = Category.objects.create(name='Vestidos')
        self.product = Product.objects.create(name='Aurora', category=self.category, sale_price=Decimal('100'))
        self.blue = Color.objects.create(name='Azul')
        self.red = Color.objects.create(name='Rojo')
        self.s = Size.objects.create(name='S', order=1)
        self.m = Size.objects.create(name='M', order=2)

    def make(self, **kw):
        data = {'product': self.product, 'color': self.blue, 'size': self.m}
        data.update(kw)
        return ProductVariant.objects.create(**data)


class VariantModelTests(VariantFixtureMixin, TestCase):
    def test_sku_assigned_sequentially(self):
        first = self.make()
        second = self.make(color=self.red)
        self.assertEqual(first.sku, 'CHAR-0001')
        self.assertEqual(second.sku, 'CHAR-0002')

    def test_sku_not_reused_after_delete(self):
        first = self.make()
        first.delete()
        self.assertEqual(self.make().sku, 'CHAR-0002')

    def test_sku_not_consumed_when_insert_fails(self):
        self.make()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make()  # combinación repetida
        self.assertEqual(SkuCounter.objects.get(pk=1).last_value, 1)
        self.assertEqual(self.make(color=self.red).sku, 'CHAR-0002')

    def test_sku_keeps_value_on_update(self):
        v = self.make()
        v.color = self.red
        v.save()
        self.assertEqual(ProductVariant.objects.get(pk=v.pk).sku, 'CHAR-0001')

    def test_sku_grows_past_four_digits(self):
        SkuCounter.objects.create(pk=1, last_value=9999)
        self.assertEqual(self.make().sku, 'CHAR-10000')

    def test_combination_unique_among_active(self):
        self.make()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make()

    def test_same_product_other_color_or_size_allowed(self):
        self.make()
        self.make(color=self.red)
        self.make(size=self.s)


class VariantApiTests(VariantFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.admin = User.objects.create_superuser(email='admin@example.com', password='pass12345')
        self.api.force_authenticate(self.admin)

    def payload(self, **kw):
        data = {'product': self.product.pk, 'color': self.blue.pk, 'size': self.m.pk}
        data.update(kw)
        return data

    def post(self, **kw):
        return self.api.post('/api/product-variants/', self.payload(**kw), format='json')

    def test_create(self):
        response = self.post()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['sku'], 'CHAR-0001')
        self.assertEqual(ProductVariant.objects.get(pk=response.data['id']).created_by, self.admin)

    def test_duplicate_combination_is_400(self):
        self.make()
        response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertIn('color y talle', str(response.data))

    def test_sku_is_read_only(self):
        response = self.post(sku='MIO-1')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['sku'], 'CHAR-0001')
        patched = self.api.patch(f"/api/product-variants/{response.data['id']}/", {'sku': 'MIO-2'}, format='json')
        self.assertEqual(patched.data['sku'], 'CHAR-0001')

    def test_failed_create_does_not_consume_sku(self):
        self.make()
        self.assertEqual(self.post().status_code, 400)
        self.assertEqual(self.post(color=self.red.pk).data['sku'], 'CHAR-0002')

    def test_update_same_values_is_ok(self):
        v = self.make()
        response = self.api.put(f'/api/product-variants/{v.pk}/', self.payload(), format='json')
        self.assertEqual(response.status_code, 200, response.data)

    def test_update_to_taken_combination_is_400(self):
        self.make()
        other = self.make(color=self.red)
        response = self.api.patch(f'/api/product-variants/{other.pk}/', {'color': self.blue.pk}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_product_cannot_change(self):
        v = self.make()
        other = Product.objects.create(name='Otro', category=self.category, sale_price=Decimal('1'))
        response = self.api.patch(f'/api/product-variants/{v.pk}/', {'product': other.pk}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_cannot_use_deleted_product(self):
        self.product.delete()
        self.assertEqual(self.post().status_code, 400)

    def test_filters(self):
        a = self.make()
        b = self.make(color=self.red, size=self.s)
        ids = lambda q: {r['id'] for r in self.api.get('/api/product-variants/', q).data['results']}  # noqa: E731
        self.assertEqual(ids({'product': self.product.pk}), {a.pk, b.pk})
        self.assertEqual(ids({'color': self.red.pk}), {b.pk})
        self.assertEqual(ids({'size': self.m.pk}), {a.pk})

    def test_cannot_delete_parents_with_variants(self):
        v = self.make()
        for url in (
            f'/api/products/{self.product.pk}/',
            f'/api/colors/{self.blue.pk}/',
            f'/api/sizes/{self.m.pk}/',
        ):
            self.assertEqual(self.api.delete(url).status_code, 400, url)
        self.assertEqual(self.api.delete(f'/api/product-variants/{v.pk}/').status_code, 204)
        self.assertEqual(self.api.delete(f'/api/products/{self.product.pk}/').status_code, 204)

    def test_restore_conflicting_variant_is_400(self):
        v = self.make()
        v.delete()
        self.make()
        self.assertEqual(self.api.post(f'/api/product-variants/{v.pk}/restore/').status_code, 400)

    def test_requires_permissions(self):
        user = User.objects.create_user(email='member@example.com', password='pass12345')
        api = APIClient()
        api.force_authenticate(user)
        self.assertEqual(api.get('/api/product-variants/').status_code, 403)
        group = Group.objects.create(name='viewers')
        group.permissions.set(Permission.objects.filter(codename='view_productvariant'))
        user.groups.add(group)
        api.force_authenticate(User.objects.get(pk=user.pk))
        self.assertEqual(api.get('/api/product-variants/').status_code, 200)
        self.assertEqual(api.post('/api/product-variants/', self.payload(), format='json').status_code, 403)


class ProductWithVariantsTests(VariantFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.admin = User.objects.create_superuser(email='admin@example.com', password='pass12345')
        self.api.force_authenticate(self.admin)
        self.url = f'/api/products/{self.product.pk}/with-variants/'

    def test_returns_product_with_variants_ordered(self):
        self.make(color=self.red, size=self.m)
        self.make(color=self.blue, size=self.m)
        self.make(color=self.blue, size=self.s)
        response = self.api.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Aurora')
        self.assertEqual(
            [(v['color']['name'], v['size']['name']) for v in response.data['variants']],
            [('Azul', 'S'), ('Azul', 'M'), ('Rojo', 'M')],
        )
        self.assertIn('sku', response.data['variants'][0])
        self.assertIn('hex', response.data['variants'][0]['color'])

    def test_excludes_deleted_variants(self):
        keep = self.make()
        self.make(color=self.red).delete()
        response = self.api.get(self.url)
        self.assertEqual([v['id'] for v in response.data['variants']], [keep.pk])

    def test_product_without_variants_returns_empty_list(self):
        self.assertEqual(self.api.get(self.url).data['variants'], [])

    def test_plain_detail_has_no_variants(self):
        self.make()
        self.assertNotIn('variants', self.api.get(f'/api/products/{self.product.pk}/').data)

    def test_deleted_product_is_404(self):
        self.product.delete()
        self.assertEqual(self.api.get(self.url).status_code, 404)

    def test_query_count_does_not_grow_with_variants(self):
        self.make()
        baseline = self._count()
        for i in range(3):
            self.make(color=Color.objects.create(name=f'C{i}'))
        with self.assertNumQueries(baseline):
            self.api.get(self.url)

    def _count(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            self.api.get(self.url)
        return len(ctx)

    def test_requires_both_view_permissions(self):
        user = User.objects.create_user(email='member@example.com', password='pass12345')
        api = APIClient()

        def login():
            api.force_authenticate(User.objects.get(pk=user.pk))

        group = Group.objects.create(name='g')
        user.groups.add(group)
        group.permissions.set(Permission.objects.filter(codename='view_product'))
        login()
        self.assertEqual(api.get(self.url).status_code, 403)
        group.permissions.add(Permission.objects.get(codename='view_productvariant'))
        login()
        self.assertEqual(api.get(self.url).status_code, 200)

    def test_cost_hidden_without_permission(self):
        self.product.cost_price = Decimal('40')
        self.product.save()
        user = User.objects.create_user(email='member@example.com', password='pass12345')
        group = Group.objects.create(name='g')
        group.permissions.set(Permission.objects.filter(codename__in=['view_product', 'view_productvariant']))
        user.groups.add(group)
        api = APIClient()
        api.force_authenticate(user)
        self.assertNotIn('cost_price', api.get(self.url).data)
        self.assertIn('cost_price', self.api.get(self.url).data)


class PublishRequiresVariantsTests(VariantFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.api.force_authenticate(User.objects.create_superuser(email='admin@example.com', password='pass12345'))
        self.url = f'/api/products/{self.product.pk}/'

    def publish(self, value=True):
        return self.api.patch(self.url, {'is_published': value}, format='json')

    def test_cannot_publish_without_variants(self):
        response = self.publish()
        self.assertEqual(response.status_code, 400)
        self.assertIn('is_published', response.data)
        self.assertFalse(Product.objects.get(pk=self.product.pk).is_published)

    def test_cannot_create_already_published(self):
        data = {'name': 'Nuevo', 'category': self.category.pk, 'sale_price': '10.00', 'is_published': True}
        response = self.api.post('/api/products/', data, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('is_published', response.data)

    def test_can_publish_with_active_variant(self):
        self.make()
        self.assertEqual(self.publish().status_code, 200)
        self.assertTrue(Product.objects.get(pk=self.product.pk).is_published)

    def test_deleted_variants_do_not_count(self):
        self.make().delete()
        self.assertEqual(self.publish().status_code, 400)

    def test_unpublishing_always_allowed(self):
        v = self.make()
        self.publish()
        v.is_deleted = True  # estado inconsistente heredado: igual se puede despublicar
        v.save(update_fields=['is_deleted'])
        self.assertEqual(self.publish(False).status_code, 200)

    def test_editing_published_product_still_works(self):
        self.make()
        self.publish()
        response = self.api.patch(self.url, {'description': 'Nueva'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

    def test_cannot_delete_last_variant_of_published_product(self):
        a = self.make()
        b = self.make(color=self.red)
        self.publish()
        self.assertEqual(self.api.delete(f'/api/product-variants/{a.pk}/').status_code, 204)
        response = self.api.delete(f'/api/product-variants/{b.pk}/')
        self.assertEqual(response.status_code, 400)
        self.assertTrue(ProductVariant.objects.filter(pk=b.pk).exists())

    def test_can_delete_last_variant_after_unpublishing(self):
        v = self.make()
        self.publish()
        self.publish(False)
        self.assertEqual(self.api.delete(f'/api/product-variants/{v.pk}/').status_code, 204)

    def test_can_delete_last_variant_of_unpublished_product(self):
        v = self.make()
        self.assertEqual(self.api.delete(f'/api/product-variants/{v.pk}/').status_code, 204)


class VariantGridTests(VariantFixtureMixin, TestCase):
    """Listado de variantes como grilla: campos derivados, filtros y orden."""

    def setUp(self):
        super().setUp()
        from datetime import timedelta

        from django.utils import timezone

        from products.models import Brand

        self.api = APIClient()
        self.api.force_authenticate(User.objects.create_superuser(email='admin@example.com', password='pass12345'))
        today = timezone.localdate()
        self.nike = Brand.objects.create(name='Nike')
        self.sub = Category.objects.create(name='Largos', parent=self.category)
        self.promo = Product.objects.create(
            name='Zeta', category=self.sub, brand=self.nike, sale_price=Decimal('200'),
            promo_price=Decimal('50'), promo_start=today - timedelta(days=1), promo_end=today + timedelta(days=1),
            is_published=False,
        )
        self.v_plain = self.make(color=self.blue, size=self.s)  # Aurora, 100
        self.v_promo = ProductVariant.objects.create(product=self.promo, color=self.red, size=self.m)

    def ids(self, query=''):
        response = self.api.get(f'/api/product-variants/{query}')
        self.assertEqual(response.status_code, 200, response.data)
        return [r['id'] for r in response.data['results']]

    def test_row_has_resolved_names_and_prices(self):
        row = self.api.get(f'/api/product-variants/{self.v_promo.pk}/').data
        self.assertEqual(row['product_name'], 'Zeta')
        self.assertEqual(row['category_label'], 'Vestidos › Largos')
        self.assertEqual(row['brand_name'], 'Nike')
        self.assertEqual((row['color_name'], row['size_name']), ('Rojo', 'M'))
        self.assertEqual(row['current_price'], '50.00')
        self.assertTrue(row['is_on_promo'])
        self.assertNotIn('cost_price', row)

    def test_filters(self):
        plain, promo = self.v_plain.pk, self.v_promo.pk
        self.assertEqual(self.ids(f'?category={self.category.pk}'), [plain, promo])  # raíz incluye hijas
        self.assertEqual(self.ids(f'?category={self.sub.pk}'), [promo])
        self.assertEqual(self.ids(f'?brand={self.nike.pk}'), [promo])
        self.assertEqual(self.ids('?on_promo=true'), [promo])
        self.assertEqual(self.ids('?on_promo=false'), [plain])
        self.assertEqual(self.ids('?min_price=60'), [plain])  # precio vigente, no el de venta
        self.assertEqual(self.ids('?max_price=60'), [promo])
        self.assertEqual(self.ids('?is_published=false'), [plain, promo])
        self.assertEqual(self.ids(f'?color={self.red.pk}&size={self.m.pk}'), [promo])
        self.assertEqual(self.ids('?search=nike'), [promo])

    def test_ordering(self):
        plain, promo = self.v_plain.pk, self.v_promo.pk
        self.assertEqual(self.ids('?ordering=effective_price'), [promo, plain])
        self.assertEqual(self.ids('?ordering=-product__name'), [promo, plain])
        self.assertEqual(self.ids('?ordering=size__order'), [plain, promo])


class ProductListVariantsTests(VariantFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.admin = User.objects.create_superuser(email='admin@example.com', password='pass12345')
        self.api.force_authenticate(self.admin)
        self.empty = Product.objects.create(name='Zeta', category=self.category, sale_price=Decimal('50'))

    def rows(self, query=''):
        response = self.api.get(f'/api/products/?page_size=100{query}')
        self.assertEqual(response.status_code, 200)
        return {r['name']: r for r in response.data['results']}

    def test_count_and_ordered_variants_exclude_deleted(self):
        self.make(color=self.red, size=self.m)
        self.make(color=self.blue, size=self.m)
        self.make(color=self.blue, size=self.s)
        self.make(color=self.red, size=self.s).delete()
        rows = self.rows()
        self.assertEqual(rows['Aurora']['variants_count'], 3)
        self.assertEqual(rows['Zeta']['variants_count'], 0)
        self.assertEqual(rows['Zeta']['variants'], [])
        first = rows['Aurora']['variants'][0]
        self.assertEqual(set(first), {'id', 'sku', 'color', 'size'})
        self.assertEqual(set(first['color']), {'id', 'name', 'hex'})
        self.assertEqual(set(first['size']), {'id', 'name', 'order'})
        self.assertEqual(
            [(v['color']['name'], v['size']['name']) for v in rows['Aurora']['variants']],
            [('Azul', 'S'), ('Azul', 'M'), ('Rojo', 'M')],
        )

    def test_has_variants_filter(self):
        self.make()
        self.assertEqual(set(self.rows('&has_variants=true')), {'Aurora'})
        self.assertEqual(set(self.rows('&has_variants=false')), {'Zeta'})

    def test_ordering_by_variants_count(self):
        self.make()
        response = self.api.get('/api/products/?ordering=-variants_count')
        self.assertEqual([r['name'] for r in response.data['results']], ['Aurora', 'Zeta'])

    def test_variants_need_view_productvariant_but_count_does_not(self):
        self.make()
        user = User.objects.create_user(email='member@example.com', password='pass12345')
        group = Group.objects.create(name='g')
        user.groups.add(group)
        group.permissions.set(Permission.objects.filter(codename='view_product'))
        api = APIClient()
        api.force_authenticate(User.objects.get(pk=user.pk))
        row = api.get('/api/products/').data['results'][0]
        self.assertIn('variants_count', row)
        self.assertNotIn('variants', row)
        group.permissions.add(Permission.objects.get(codename='view_productvariant'))
        api.force_authenticate(User.objects.get(pk=user.pk))
        self.assertIn('variants', api.get('/api/products/').data['results'][0])

    def test_detail_has_count_but_no_variants(self):
        self.make()
        data = self.api.get(f'/api/products/{self.product.pk}/').data
        self.assertEqual(data['variants_count'], 1)
        self.assertNotIn('variants', data)

    def test_list_query_count_does_not_grow(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.make()
        with CaptureQueriesContext(connection) as a:
            self.api.get('/api/products/')
        for i in range(3):
            self.make(color=Color.objects.create(name=f'C{i}'))
            Product.objects.create(name=f'P{i}', category=self.category, sale_price=Decimal('1'))
        with CaptureQueriesContext(connection) as b:
            self.api.get('/api/products/')
        self.assertEqual(len(a), len(b))
