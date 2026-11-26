from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from rest_framework.test import APIClient

from products.models import Brand, Category, Color, ProductModel, Size
from users.models import User


class CatalogApiTestCase(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.admin = User.objects.create_superuser(email='admin@example.com', password='pass12345')
        self.api.force_authenticate(self.admin)


class CategoryApiTests(CatalogApiTestCase):
    def test_create_root_and_child(self):
        root = self.api.post('/api/categories/', {'name': 'Vestidos'}, format='json')
        self.assertEqual(root.status_code, 201)
        child = self.api.post('/api/categories/', {'name': 'Largos', 'parent': root.data['id']}, format='json')
        self.assertEqual(child.status_code, 201)
        self.assertEqual(Category.objects.get(pk=child.data['id']).created_by, self.admin)

    def test_rejects_third_level(self):
        root = Category.objects.create(name='Vestidos')
        child = Category.objects.create(name='Largos', parent=root)
        response = self.api.post('/api/categories/', {'name': 'Fiesta', 'parent': child.pk}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('parent', response.data)

    def test_rejects_own_parent(self):
        root = Category.objects.create(name='Vestidos')
        response = self.api.patch(f'/api/categories/{root.pk}/', {'parent': root.pk}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_rejects_parent_for_category_with_children(self):
        root = Category.objects.create(name='Vestidos')
        Category.objects.create(name='Largos', parent=root)
        other = Category.objects.create(name='Indumentaria')
        response = self.api.patch(f'/api/categories/{root.pk}/', {'parent': other.pk}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_duplicate_sibling_name_is_400_case_insensitive(self):
        root = Category.objects.create(name='Vestidos')
        Category.objects.create(name='Largos', parent=root)
        response = self.api.post('/api/categories/', {'name': 'LARGOS', 'parent': root.pk}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_duplicate_root_name_is_400(self):
        Category.objects.create(name='Vestidos')
        response = self.api.post('/api/categories/', {'name': ' vestidos '}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_same_name_under_other_parent_is_ok(self):
        a = Category.objects.create(name='A')
        b = Category.objects.create(name='B')
        Category.objects.create(name='Otros', parent=a)
        response = self.api.post('/api/categories/', {'name': 'Otros', 'parent': b.pk}, format='json')
        self.assertEqual(response.status_code, 201)

    def test_update_keeping_same_name_is_ok(self):
        root = Category.objects.create(name='Vestidos')
        response = self.api.put(f'/api/categories/{root.pk}/', {'name': 'Vestidos'}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_filters_root_and_parent(self):
        root = Category.objects.create(name='Vestidos')
        child = Category.objects.create(name='Largos', parent=root)
        roots = self.api.get('/api/categories/', {'root': 'true'})
        self.assertEqual([r['id'] for r in roots.data['results']], [root.pk])
        children = self.api.get('/api/categories/', {'parent': root.pk})
        self.assertEqual([r['id'] for r in children.data['results']], [child.pk])

    def test_cannot_delete_category_with_children(self):
        root = Category.objects.create(name='Vestidos')
        child = Category.objects.create(name='Largos', parent=root)
        self.assertEqual(self.api.delete(f'/api/categories/{root.pk}/').status_code, 400)
        self.assertEqual(self.api.delete(f'/api/categories/{child.pk}/').status_code, 204)
        self.assertEqual(self.api.delete(f'/api/categories/{root.pk}/').status_code, 204)

    def test_delete_is_soft_and_restore_works(self):
        root = Category.objects.create(name='Vestidos')
        self.api.delete(f'/api/categories/{root.pk}/')
        deleted = Category.all_objects.get(pk=root.pk)
        self.assertTrue(deleted.is_deleted)
        self.assertEqual(deleted.deleted_by, self.admin)
        self.assertEqual(self.api.post(f'/api/categories/{root.pk}/restore/').status_code, 200)
        self.assertFalse(Category.objects.get(pk=root.pk).is_deleted)


class BrandAndModelApiTests(CatalogApiTestCase):
    def test_cannot_delete_brand_with_models(self):
        brand = Brand.objects.create(name='X')
        model = ProductModel.objects.create(brand=brand, name='Aurora')
        self.assertEqual(self.api.delete(f'/api/brands/{brand.pk}/').status_code, 400)
        model.delete()
        self.assertEqual(self.api.delete(f'/api/brands/{brand.pk}/').status_code, 204)

    def test_model_name_unique_within_brand_only(self):
        x = Brand.objects.create(name='X')
        y = Brand.objects.create(name='Y')
        ProductModel.objects.create(brand=x, name='Aurora')
        dup = self.api.post('/api/product-models/', {'name': 'aurora', 'brand': x.pk}, format='json')
        self.assertEqual(dup.status_code, 400)
        ok = self.api.post('/api/product-models/', {'name': 'Aurora', 'brand': y.pk}, format='json')
        self.assertEqual(ok.status_code, 201)

    def test_model_requires_brand_and_filters_by_it(self):
        x = Brand.objects.create(name='X')
        y = Brand.objects.create(name='Y')
        a = ProductModel.objects.create(brand=x, name='A')
        ProductModel.objects.create(brand=y, name='B')
        self.assertEqual(self.api.post('/api/product-models/', {'name': 'Z'}, format='json').status_code, 400)
        response = self.api.get('/api/product-models/', {'brand': x.pk})
        self.assertEqual([r['id'] for r in response.data['results']], [a.pk])

    def test_deleted_brand_name_can_be_reused(self):
        Brand.objects.create(name='X').delete()
        self.assertEqual(self.api.post('/api/brands/', {'name': 'X'}, format='json').status_code, 201)


class ColorAndSizeApiTests(CatalogApiTestCase):
    def test_color_invalid_hex_is_400(self):
        response = self.api.post('/api/colors/', {'name': 'Azul', 'hex': 'azul'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_color_hex_optional(self):
        self.assertEqual(self.api.post('/api/colors/', {'name': 'Azul'}, format='json').status_code, 201)

    def test_color_duplicate_case_insensitive(self):
        Color.objects.create(name='Azul')
        self.assertEqual(self.api.post('/api/colors/', {'name': 'azul'}, format='json').status_code, 400)

    def test_sizes_listed_in_order(self):
        Size.objects.create(name='M', order=3)
        Size.objects.create(name='XS', order=1)
        Size.objects.create(name='S', order=2)
        response = self.api.get('/api/sizes/')
        self.assertEqual([r['name'] for r in response.data['results']], ['XS', 'S', 'M'])


class CatalogPermissionsTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.user = User.objects.create_user(email='member@example.com', password='pass12345')
        self.api.force_authenticate(self.user)

    def _grant(self, *codenames):
        group = Group.objects.create(name='g_' + '_'.join(codenames))
        group.permissions.set(Permission.objects.filter(content_type__app_label='products', codename__in=codenames))
        self.user.groups.add(group)
        # ModelBackend cachea permisos en la instancia: se re-autentica con una nueva.
        self.user = User.objects.get(pk=self.user.pk)
        self.api.force_authenticate(self.user)

    def test_requires_view_permission_to_list(self):
        self.assertEqual(self.api.get('/api/brands/').status_code, 403)
        self._grant('view_brand')
        self.assertEqual(self.api.get('/api/brands/').status_code, 200)

    def test_view_only_cannot_write(self):
        self._grant('view_brand')
        self.assertEqual(self.api.post('/api/brands/', {'name': 'X'}, format='json').status_code, 403)

    def test_add_permission_allows_create(self):
        self._grant('view_brand', 'add_brand')
        self.assertEqual(self.api.post('/api/brands/', {'name': 'X'}, format='json').status_code, 201)

    def test_restore_requires_change_permission(self):
        brand = Brand.objects.create(name='X')
        brand.delete()
        self._grant('view_brand', 'delete_brand')
        self.assertEqual(self.api.post(f'/api/brands/{brand.pk}/restore/').status_code, 403)
        self._grant('change_brand')
        self.assertEqual(self.api.post(f'/api/brands/{brand.pk}/restore/').status_code, 200)
