from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from products.models import Brand, Category, Color, Product, ProductImage, ProductVariant, Size
from products.slugs import generate_unique_slug
from users.models import User


class SlugGenerationTests(TestCase):
    def test_slugifies_and_strips_accents(self):
        self.assertEqual(generate_unique_slug(Brand, 'Ñandú Ñ & Co'), 'nandu-n-co')

    def test_empty_slug_falls_back_to_item(self):
        self.assertEqual(generate_unique_slug(Brand, '!!!'), 'item')

    def test_numbers_collisions(self):
        Brand.objects.create(name='X', slug='x')
        Brand.objects.create(name='X2', slug='x-2')
        self.assertEqual(generate_unique_slug(Brand, 'X'), 'x-3')

    def test_prefix_tried_before_number(self):
        Category.objects.create(name='Largos', slug='largos')
        self.assertEqual(generate_unique_slug(Category, 'Largos', prefix='vestidos'), 'vestidos-largos')

    def test_deleted_slug_is_reusable(self):
        Brand.objects.create(name='X', slug='x').delete()
        self.assertEqual(generate_unique_slug(Brand, 'X'), 'x')

    def test_exclude_pk_ignores_own_slug(self):
        b = Brand.objects.create(name='X')
        self.assertEqual(generate_unique_slug(Brand, 'X', exclude_pk=b.pk), 'x')

    def test_respects_max_length(self):
        slug = generate_unique_slug(Brand, 'a' * 500)
        self.assertLessEqual(len(slug), Brand._meta.get_field('slug').max_length)

    def test_model_save_generates_slug_when_missing(self):
        root = Category.objects.create(name='Vestidos')
        child = Category.objects.create(name='Largos', parent=root)
        other = Category.objects.create(name='Otros')
        Category.objects.create(name='Largos', parent=other)  # mismo nombre bajo otro padre
        self.assertEqual(root.slug, 'vestidos')
        self.assertEqual(child.slug, 'largos')
        self.assertEqual(Category.objects.get(parent=other).slug, 'otros-largos')


class SlugApiTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(User.objects.create_superuser(email='admin@example.com', password='pass12345'))
        self.category = Category.objects.create(name='Vestidos')

    def add_variant(self, product_id):
        color, _ = Color.objects.get_or_create(name='Azul')
        size, _ = Size.objects.get_or_create(name='M')
        # Con foto de su color: es lo que exige publicar.
        ProductImage.objects.get_or_create(product_id=product_id, color=color, storage_key='test/foto')
        return ProductVariant.objects.create(product_id=product_id, color=color, size=size)

    def published_product(self, **kw):
        created = self.product(**kw).data
        self.add_variant(created['id'])
        response = self.api.patch(f"/api/products/{created['id']}/", {'is_published': True}, format='json')
        assert response.status_code == 200, response.data
        return response.data

    def product(self, **kw):
        data = {'name': 'Vestido Aurora', 'category': self.category.pk, 'sale_price': '100.00'}
        data.update(kw)
        return self.api.post('/api/products/', data, format='json')

    def test_product_slug_generated_when_omitted(self):
        response = self.product()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['slug'], 'vestido-aurora')
        self.assertFalse(response.data['is_published'])

    def test_same_name_gets_numbered_slug(self):
        self.product()
        self.assertEqual(self.product().data['slug'], 'vestido-aurora-2')

    def test_explicit_slug_respected_and_lowercased(self):
        self.assertEqual(self.product(slug='  Mi-Vestido ').data['slug'], 'mi-vestido')

    def test_explicit_duplicate_slug_is_400(self):
        self.product(slug='mi-vestido')
        response = self.product(slug='mi-vestido')
        self.assertEqual(response.status_code, 400)
        self.assertIn('slug', response.data)

    def test_invalid_slug_is_400(self):
        self.assertEqual(self.product(slug='con espacios').status_code, 400)

    def test_rename_does_not_change_slug(self):
        created = self.product().data
        response = self.api.patch(f"/api/products/{created['id']}/", {'name': 'Otro nombre'}, format='json')
        self.assertEqual(response.data['slug'], 'vestido-aurora')

    def test_blank_slug_regenerates_when_unpublished(self):
        created = self.product().data
        self.api.patch(f"/api/products/{created['id']}/", {'name': 'Otro nombre'}, format='json')
        response = self.api.patch(f"/api/products/{created['id']}/", {'slug': ''}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['slug'], 'otro-nombre')

    def test_blank_slug_regeneration_keeps_own_slug_free(self):
        created = self.product().data
        response = self.api.patch(f"/api/products/{created['id']}/", {'slug': ''}, format='json')
        self.assertEqual(response.data['slug'], 'vestido-aurora')

    def test_blank_slug_rejected_when_published(self):
        created = self.published_product()
        response = self.api.patch(f"/api/products/{created['id']}/", {'slug': ''}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('slug', response.data)

    def test_blank_slug_with_publishing_in_same_request_rejected(self):
        created = self.product().data
        self.add_variant(created['id'])
        response = self.api.patch(
            f"/api/products/{created['id']}/", {'slug': '', 'is_published': True}, format='json'
        )
        self.assertEqual(response.status_code, 400)

    def test_blank_slug_on_create_is_generated(self):
        self.assertEqual(self.product(slug='').data['slug'], 'vestido-aurora')

    def test_published_flag_roundtrip_and_filter(self):
        a = self.published_product(name='A')
        self.product(name='B')
        ids = lambda q: {r['id'] for r in self.api.get('/api/products/', q).data['results']}  # noqa: E731
        self.assertEqual(ids({'is_published': 'true'}), {a['id']})
        self.assertEqual(len(ids({'is_published': 'false'})), 1)
        patched = self.api.patch(f"/api/products/{a['id']}/", {'is_published': False}, format='json')
        self.assertFalse(patched.data['is_published'])

    def test_search_by_slug(self):
        a = self.product(name='Alfa', slug='codigo-raro').data
        self.product(name='Beta')
        response = self.api.get('/api/products/', {'search': 'codigo-raro'})
        self.assertEqual([r['id'] for r in response.data['results']], [a['id']])

    def test_with_variants_includes_slug_and_published(self):
        a = self.published_product()
        data = self.api.get(f"/api/products/{a['id']}/with-variants/").data
        self.assertEqual(data['slug'], 'vestido-aurora')
        self.assertTrue(data['is_published'])

    def test_deleted_product_slug_reusable(self):
        a = self.product().data
        self.api.delete(f"/api/products/{a['id']}/")
        self.assertEqual(self.product().data['slug'], 'vestido-aurora')

    def test_restore_with_taken_slug_is_400(self):
        a = self.product().data
        self.api.delete(f"/api/products/{a['id']}/")
        self.product()
        self.assertEqual(self.api.post(f"/api/products/{a['id']}/restore/").status_code, 400)

    def test_category_slug_uses_parent_prefix_on_collision(self):
        self.api.post('/api/categories/', {'name': 'Largos'}, format='json')
        response = self.api.post('/api/categories/', {'name': 'Largos', 'parent': self.category.pk}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['slug'], 'vestidos-largos')

    def test_brand_slug_generated(self):
        self.assertEqual(self.api.post('/api/brands/', {'name': 'Marca X'}, format='json').data['slug'], 'marca-x')

    def test_category_and_brand_slug_explicit_duplicate_is_400(self):
        self.assertEqual(self.api.post('/api/brands/', {'name': 'A', 'slug': 'm'}, format='json').status_code, 201)
        self.assertEqual(self.api.post('/api/brands/', {'name': 'B', 'slug': 'm'}, format='json').status_code, 400)
