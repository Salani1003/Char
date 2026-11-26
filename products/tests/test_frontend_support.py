from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from products.models import Brand, Category, Color, Product, ProductModel, ProductVariant, Size
from users.models import User


class ApiCase(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(User.objects.create_superuser(email='admin@example.com', password='pass12345'))

    def ids(self, url, **params):
        return [r['id'] for r in self.api.get(url, {'page_size': 100, **params}).data['results']]

    def queries(self, url, **params):
        with CaptureQueriesContext(connection) as ctx:
            response = self.api.get(url, {'page_size': 100, **params})
        self.assertEqual(response.status_code, 200)
        return len(ctx)


class CategoryFlagsTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.dresses = Category.objects.create(name='Vestidos')
        self.long = Category.objects.create(name='Largos', parent=self.dresses)
        self.short = Category.objects.create(name='Cortos', parent=self.dresses)
        self.accessories = Category.objects.create(name='Accesorios')

    def by_id(self):
        return {r['id']: r for r in self.api.get('/api/categories/', {'page_size': 100}).data['results']}

    def test_has_children_and_products_count_in_list(self):
        Product.objects.create(name='A', category=self.accessories, sale_price=Decimal('1'))
        Product.objects.create(name='B', category=self.accessories, sale_price=Decimal('1'))
        Product.objects.create(name='C', category=self.long, sale_price=Decimal('1'))
        rows = self.by_id()
        self.assertTrue(rows[self.dresses.pk]['has_children'])
        self.assertEqual(rows[self.dresses.pk]['products_count'], 0)
        self.assertFalse(rows[self.long.pk]['has_children'])
        self.assertEqual(rows[self.long.pk]['products_count'], 1)
        self.assertFalse(rows[self.short.pk]['has_children'])
        self.assertEqual(rows[self.short.pk]['products_count'], 0)
        self.assertFalse(rows[self.accessories.pk]['has_children'])
        self.assertEqual(rows[self.accessories.pk]['products_count'], 2)

    def test_label_and_parent_name(self):
        rows = self.by_id()
        self.assertEqual(rows[self.long.pk]['label'], 'Vestidos › Largos')
        self.assertEqual(rows[self.long.pk]['parent_name'], 'Vestidos')
        self.assertEqual(rows[self.dresses.pk]['label'], 'Vestidos')
        self.assertIsNone(rows[self.dresses.pk]['parent_name'])
        created = self.api.post('/api/categories/', {'name': 'Enterizos', 'parent': self.accessories.pk}, format='json')
        self.assertEqual(created.data['label'], 'Accesorios › Enterizos')

    def test_deleted_children_and_products_are_not_counted(self):
        self.short.delete()
        self.long.delete()
        Product.objects.create(name='A', category=self.accessories, sale_price=Decimal('1')).delete()
        rows = self.by_id()
        self.assertFalse(rows[self.dresses.pk]['has_children'])
        self.assertEqual(rows[self.accessories.pk]['products_count'], 0)

    def test_fields_in_retrieve_create_and_update_responses(self):
        retrieved = self.api.get(f'/api/categories/{self.dresses.pk}/').data
        self.assertTrue(retrieved['has_children'])
        created = self.api.post('/api/categories/', {'name': 'Enterizos', 'parent': self.accessories.pk}, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        self.assertFalse(created.data['has_children'])
        self.assertEqual(created.data['products_count'], 0)
        updated = self.api.patch(f'/api/categories/{self.dresses.pk}/', {'name': 'Vestidos de fiesta'}, format='json')
        self.assertTrue(updated.data['has_children'])

    def test_fields_are_read_only(self):
        response = self.api.patch(
            f'/api/categories/{self.long.pk}/', {'has_children': True, 'products_count': 9}, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['has_children'])
        self.assertEqual(response.data['products_count'], 0)

    def test_creating_a_subcategory_flips_parent_flag(self):
        self.assertFalse(self.api.get(f'/api/categories/{self.accessories.pk}/').data['has_children'])
        self.api.post('/api/categories/', {'name': 'Bolsos', 'parent': self.accessories.pk}, format='json')
        self.assertTrue(self.api.get(f'/api/categories/{self.accessories.pk}/').data['has_children'])

    def test_leaf_filter(self):
        self.assertEqual(
            set(self.ids('/api/categories/', leaf='true')), {self.long.pk, self.short.pk, self.accessories.pk}
        )
        self.assertEqual(self.ids('/api/categories/', leaf='false'), [self.dresses.pk])

    def test_leaf_filter_ignores_deleted_children_and_combines_with_search(self):
        self.short.delete()
        self.long.delete()
        self.assertIn(self.dresses.pk, self.ids('/api/categories/', leaf='true'))
        Category.objects.create(name='Largos fiesta', parent=self.accessories)
        self.assertEqual(len(self.ids('/api/categories/', leaf='true', search='largos')), 1)

    def test_list_query_count_does_not_grow_with_rows(self):
        baseline = self.queries('/api/categories/')
        for i in range(5):
            parent = Category.objects.create(name=f'Padre {i}')
            Category.objects.create(name=f'Hija {i}', parent=parent)
        self.assertEqual(self.queries('/api/categories/'), baseline)

    def test_restore_still_works_with_annotations(self):
        self.short.delete()
        self.assertEqual(self.api.post(f'/api/categories/{self.short.pk}/restore/').status_code, 200)


class ProductNamesTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.dresses = Category.objects.create(name='Vestidos')
        self.long = Category.objects.create(name='Largos', parent=self.dresses)
        self.root_leaf = Category.objects.create(name='Accesorios')
        self.brand = Brand.objects.create(name='Marca X')
        self.model = ProductModel.objects.create(brand=self.brand, name='Aurora')

    def make(self, **kw):
        data = {'name': 'Vestido', 'category': self.long, 'sale_price': Decimal('100')}
        data.update(kw)
        return Product.objects.create(**data)

    def test_labels_in_detail_and_list(self):
        p = self.make(brand=self.brand, product_model=self.model)
        for data in (
            self.api.get(f'/api/products/{p.pk}/').data,
            self.api.get('/api/products/').data['results'][0],
        ):
            self.assertEqual(data['category_label'], 'Vestidos › Largos')
            self.assertEqual(data['brand_name'], 'Marca X')
            self.assertEqual(data['product_model_name'], 'Aurora')

    def test_root_category_label_is_just_its_name_and_nulls_without_brand(self):
        p = self.make(category=self.root_leaf)
        data = self.api.get(f'/api/products/{p.pk}/').data
        self.assertEqual(data['category_label'], 'Accesorios')
        self.assertIsNone(data['brand_name'])
        self.assertIsNone(data['product_model_name'])

    def test_labels_in_create_update_and_with_variants(self):
        created = self.api.post(
            '/api/products/',
            {'name': 'Nuevo', 'category': self.long.pk, 'sale_price': '10.00', 'product_model': self.model.pk},
            format='json',
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data['category_label'], 'Vestidos › Largos')
        self.assertEqual(created.data['brand_name'], 'Marca X')
        patched = self.api.patch(f"/api/products/{created.data['id']}/", {'category': self.root_leaf.pk}, format='json')
        self.assertEqual(patched.data['category_label'], 'Accesorios')
        ProductVariant.objects.create(
            product_id=created.data['id'], color=Color.objects.create(name='Azul'), size=Size.objects.create(name='M')
        )
        nested = self.api.get(f"/api/products/{created.data['id']}/with-variants/").data
        self.assertEqual(nested['category_label'], 'Accesorios')

    def test_labels_follow_catalog_renames(self):
        p = self.make()
        self.long.name = 'Cortos'
        self.long.save()
        self.assertEqual(self.api.get(f'/api/products/{p.pk}/').data['category_label'], 'Vestidos › Cortos')

    def test_list_query_count_does_not_grow_with_rows(self):
        self.make(name='Uno', brand=self.brand, product_model=self.model)
        baseline = self.queries('/api/products/')
        for i in range(6):
            self.make(name=f'P{i}', brand=self.brand, product_model=self.model)
        self.assertEqual(self.queries('/api/products/'), baseline)


class ColorHexTests(ApiCase):
    def test_hex_saved_uppercase_via_api(self):
        response = self.api.post('/api/colors/', {'name': 'Azul marino', 'hex': '#14284b'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['hex'], '#14284B')
        self.assertEqual(Color.objects.get(pk=response.data['id']).hex, '#14284B')

    def test_hex_uppercased_on_patch(self):
        color = Color.objects.create(name='Azul')
        response = self.api.patch(f'/api/colors/{color.pk}/', {'hex': ' #1f4e9e '}, format='json')
        self.assertEqual(response.data['hex'], '#1F4E9E')

    def test_hex_optional_and_validated(self):
        self.assertEqual(self.api.post('/api/colors/', {'name': 'Rojo'}, format='json').data['hex'], '')
        self.assertEqual(self.api.post('/api/colors/', {'name': 'Verde', 'hex': 'verde'}, format='json').status_code, 400)
        self.assertEqual(self.api.post('/api/colors/', {'name': 'Gris', 'hex': '#12345'}, format='json').status_code, 400)

    def test_hex_uppercased_on_orm_save_and_update_fields(self):
        color = Color.objects.create(name='Azul', hex='#abcdef')
        self.assertEqual(color.hex, '#ABCDEF')
        color.hex = '#fedcba'
        color.save(update_fields=['name'])
        self.assertEqual(Color.objects.get(pk=color.pk).hex, '#FEDCBA')
