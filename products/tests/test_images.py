from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.tests.fakes import FakeImageStorage
from products.models import ProductImage
from products.tests.test_variants import VariantFixtureMixin
from users.models import User

URL = '/api/product-images/'
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 32
WEBP = b'RIFF\x24\x00\x00\x00WEBPVP8 ' + b'\x00' * 16


def upload(content=PNG, name='foto.png', content_type='image/png'):
    return SimpleUploadedFile(name, content, content_type=content_type)


@override_settings(IMAGE_STORAGE='core.tests.fakes.FakeImageStorage', IMAGE_FOLDER='test')
class ImageTestCase(VariantFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        FakeImageStorage.reset()
        self.api = APIClient()
        self.admin = User.objects.create_superuser(email='admin@example.com', password='pass12345')
        self.api.force_authenticate(self.admin)

    def post(self, file=None, **extra):
        data = {'product': self.product.pk, 'color': self.blue.pk, 'file': file or upload(), **extra}
        return self.api.post(URL, data, format='multipart')


class UploadTests(ImageTestCase):
    def test_upload_registers_the_image_with_the_key_from_the_provider(self):
        response = self.post(alt_text='Frente')
        self.assertEqual(response.status_code, 201, response.data)
        key = f'test/products/{self.product.pk}/img1'
        self.assertEqual(response.data['storage_key'], key)
        self.assertEqual(response.data['url'], f'https://fake.test/{key}')
        self.assertEqual(response.data['thumbnail_url'], f'https://fake.test/400x400/{key}')
        self.assertEqual(response.data['color_name'], 'Azul')
        self.assertNotIn('file', response.data)
        self.assertEqual(response.data['created_by'], self.admin.pk)
        self.assertEqual(ProductImage.objects.get().alt_text, 'Frente')
        self.assertEqual(FakeImageStorage.uploaded[0][0], key)

    def test_accepts_jpeg_png_and_webp(self):
        for content, name in ((JPEG, 'a.jpg'), (PNG, 'a.png'), (WEBP, 'a.webp')):
            self.assertEqual(self.post(upload(content, name)).status_code, 201, name)

    def test_color_is_required(self):
        response = self.api.post(URL, {'product': self.product.pk, 'file': upload()}, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertIn('color', response.data)
        self.assertEqual(FakeImageStorage.uploaded, [])

    def test_client_cannot_choose_the_storage_key(self):
        response = self.post(storage_key='char/otra/ajena')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotEqual(response.data['storage_key'], 'char/otra/ajena')

    def test_json_without_file_is_rejected(self):
        response = self.api.post(URL, {'product': self.product.pk, 'color': self.blue.pk}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('file', response.data)

    def test_file_content_is_checked_not_the_declared_type(self):
        response = self.post(upload(b'<?xml version="1.0"?><svg onload="alert(1)"/>', 'logo.png', 'image/png'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('no es una imagen válida', str(response.data['file']))
        self.assertEqual(FakeImageStorage.uploaded, [])

    @override_settings(IMAGE_MAX_BYTES=10)
    def test_too_big_is_rejected(self):
        self.assertEqual(self.post().status_code, 400)
        self.assertEqual(FakeImageStorage.uploaded, [])

    def test_storage_not_configured_is_503(self):
        FakeImageStorage.configured = False
        self.assertEqual(self.post().status_code, 503)
        self.assertEqual(ProductImage.objects.count(), 0)

    def test_provider_failure_is_502(self):
        FakeImageStorage.fail_upload = True
        self.assertEqual(self.post().status_code, 502)
        self.assertEqual(ProductImage.objects.count(), 0)

    def test_orphan_file_is_cleaned_when_the_record_cannot_be_saved(self):
        with self.assertRaises(Exception):
            # color inexistente: falla el INSERT (FK) después de subir el archivo
            from products.serializers import ProductImageSerializer

            ProductImageSerializer().create({'product': self.product, 'color_id': 999999, 'file': upload()})
        self.assertEqual(len(FakeImageStorage.deleted), len(FakeImageStorage.uploaded))
        self.assertEqual(ProductImage.objects.count(), 0)


class GalleryTests(ImageTestCase):
    def test_several_images_per_product_and_color_get_consecutive_order(self):
        orders = [self.post().data['sort_order'] for _ in range(3)]
        self.assertEqual(orders, [0, 1, 2])

    def test_order_is_independent_per_color(self):
        self.post()
        self.post()
        self.assertEqual(self.post(color=self.red.pk).data['sort_order'], 0)

    def test_explicit_sort_order_is_respected(self):
        self.assertEqual(self.post(sort_order=5).data['sort_order'], 5)
        self.assertEqual(self.post().data['sort_order'], 6)

    def test_image_does_not_need_a_variant_of_that_color(self):
        self.assertEqual(self.post(color=self.red.pk).status_code, 201)

    def test_filter_by_product_and_color(self):
        self.post()
        self.post(color=self.red.pk)
        response = self.api.get(URL, {'product': self.product.pk, 'color': self.red.pk})
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['color'], self.red.pk)

    def test_with_variants_includes_images_ordered_by_color_and_order(self):
        self.make()
        self.post(color=self.red.pk)
        self.post(sort_order=1)
        self.post(sort_order=0)
        response = self.api.get(f'/api/products/{self.product.pk}/with-variants/')
        self.assertEqual(response.status_code, 200)
        images = response.data['images']
        self.assertEqual([(i['color'], i['sort_order']) for i in images], [(self.blue.pk, 0), (self.blue.pk, 1), (self.red.pk, 0)])
        self.assertIn('thumbnail_url', images[0])

    def test_plain_product_detail_has_no_images(self):
        self.post()
        self.assertNotIn('images', self.api.get(f'/api/products/{self.product.pk}/').data)


class UpdateAndDeleteTests(ImageTestCase):
    def setUp(self):
        super().setUp()
        self.image_id = self.post().data['id']
        self.detail = f'{URL}{self.image_id}/'

    def test_can_edit_alt_order_and_color(self):
        response = self.api.patch(self.detail, {'alt_text': 'Dorso', 'sort_order': 3, 'color': self.red.pk}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        image = ProductImage.objects.get()
        self.assertEqual((image.alt_text, image.sort_order, image.color_id), ('Dorso', 3, self.red.pk))

    def test_cannot_replace_the_file(self):
        response = self.api.patch(self.detail, {'file': upload()}, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertIn('file', response.data)

    def test_cannot_change_the_product(self):
        other = type(self.product).objects.create(name='Otro', category=self.category, sale_price=1)
        response = self.api.patch(self.detail, {'product': other.pk}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('product', response.data)

    def test_delete_removes_the_file_and_soft_deletes(self):
        key = ProductImage.objects.get().storage_key
        self.assertEqual(self.api.delete(self.detail).status_code, 204)
        self.assertEqual(FakeImageStorage.deleted, [key])
        self.assertEqual(ProductImage.objects.count(), 0)
        self.assertTrue(ProductImage.all_objects.get().is_deleted)

    def test_provider_failure_on_delete_keeps_the_image(self):
        FakeImageStorage.fail_delete = True
        self.assertEqual(self.api.delete(self.detail).status_code, 502)
        self.assertEqual(ProductImage.objects.count(), 1)

    def test_storage_not_configured_on_delete_is_503(self):
        FakeImageStorage.configured = False
        self.assertEqual(self.api.delete(self.detail).status_code, 503)
        self.assertEqual(ProductImage.objects.count(), 1)

    def test_cannot_restore(self):
        self.api.delete(self.detail)
        self.assertEqual(self.api.post(f'{self.detail}restore/').status_code, 404)

    def test_color_with_images_cannot_be_deleted(self):
        response = self.api.delete(f'/api/colors/{self.blue.pk}/')
        self.assertEqual(response.status_code, 400)
        self.assertIn('imágenes', str(response.data))

    def test_product_with_images_cannot_be_deleted(self):
        response = self.api.delete(f'/api/products/{self.product.pk}/')
        self.assertEqual(response.status_code, 400)
        self.assertIn('imágenes', str(response.data))

    def test_color_and_product_can_be_deleted_after_removing_images(self):
        self.api.delete(self.detail)
        self.assertEqual(self.api.delete(f'/api/colors/{self.blue.pk}/').status_code, 204)
        self.assertEqual(self.api.delete(f'/api/products/{self.product.pk}/').status_code, 204)


class PermissionTests(ImageTestCase):
    def setUp(self):
        super().setUp()
        call_command('seed_roles', verbosity=0)
        self.image_id = self.post().data['id']

    def client_for(self, role):
        user = User.objects.create_user(email=f'{role.lower()}@example.com', password='pass12345')
        user.groups.add(Group.objects.get(name=role))
        api = APIClient()
        api.force_authenticate(user)
        return api

    def test_vendedor_can_only_view(self):
        api = self.client_for('Vendedor')
        self.assertEqual(api.get(URL).status_code, 200)
        self.assertEqual(api.post(URL, {'product': self.product.pk, 'color': self.blue.pk, 'file': upload()}, format='multipart').status_code, 403)
        self.assertEqual(api.delete(f'{URL}{self.image_id}/').status_code, 403)

    def test_administrador_can_manage(self):
        api = self.client_for('Administrador')
        self.assertEqual(api.post(URL, {'product': self.product.pk, 'color': self.blue.pk, 'file': upload()}, format='multipart').status_code, 201)
        self.assertEqual(api.delete(f'{URL}{self.image_id}/').status_code, 204)

    def test_anonymous_is_rejected(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)


class VariantGridThumbnailTests(ImageTestCase):
    def grid(self):
        return {r['color']: r for r in self.api.get('/api/product-variants/').data['results']}

    def test_row_shows_first_image_of_its_color(self):
        self.make()
        self.make(color=self.red)
        self.post(sort_order=1)
        first = self.post(sort_order=0).data['storage_key']
        rows = self.grid()
        self.assertEqual(rows[self.blue.pk]['thumbnail_url'], f'https://fake.test/400x400/{first}')
        self.assertEqual(rows[self.blue.pk]['image_url'], f'https://fake.test/{first}')
        self.assertIsNone(rows[self.red.pk]['thumbnail_url'])
        self.assertIsNone(rows[self.red.pk]['image_url'])

    def test_sizes_of_the_same_color_share_the_image(self):
        self.make(size=self.s)
        self.make(size=self.m)
        self.post()
        urls = {r['thumbnail_url'] for r in self.api.get('/api/product-variants/').data['results']}
        self.assertEqual(len(urls), 1)
        self.assertIsNotNone(urls.pop())

    def test_deleted_images_are_ignored(self):
        self.make()
        image_id = self.post().data['id']
        self.api.delete(f'{URL}{image_id}/')
        self.assertIsNone(self.grid()[self.blue.pk]['thumbnail_url'])

    def test_no_query_per_row(self):
        for size in (self.s, self.m):
            for color in (self.blue, self.red):
                self.make(color=color, size=size)
        self.post()
        with self.assertNumQueries(2):  # conteo + listado (la imagen va en una subconsulta)
            self.api.get('/api/product-variants/')

    def test_create_response_includes_thumbnail(self):
        self.post()
        response = self.api.post('/api/product-variants/', {'product': self.product.pk, 'color': self.blue.pk, 'size': self.s.pk}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data['thumbnail_url'].startswith('https://fake.test/400x400/'))


class PrimaryImageTests(ImageTestCase):
    def primaries(self, color=None):
        return list(ProductImage.objects.filter(product=self.product, color=color or self.blue, is_primary=True))

    def test_first_upload_is_not_primary_by_default(self):
        self.assertFalse(self.post().data['is_primary'])
        self.assertEqual(self.primaries(), [])

    def test_can_upload_as_primary(self):
        self.assertTrue(self.post(is_primary='true').data['is_primary'])

    def test_marking_a_new_one_unmarks_the_previous(self):
        first = self.post(is_primary='true').data['id']
        second = self.post(is_primary='true').data['id']
        self.assertEqual([i.pk for i in self.primaries()], [second])
        self.assertFalse(ProductImage.objects.get(pk=first).is_primary)

    def test_patch_moves_the_primary(self):
        first = self.post(is_primary='true').data['id']
        second = self.post().data['id']
        response = self.api.patch(f'{URL}{second}/', {'is_primary': True}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([i.pk for i in self.primaries()], [second])
        self.assertFalse(ProductImage.objects.get(pk=first).is_primary)

    def test_patch_unmark_leaves_no_primary(self):
        first = self.post(is_primary='true').data['id']
        self.api.patch(f'{URL}{first}/', {'is_primary': False}, format='json')
        self.assertEqual(self.primaries(), [])

    def test_primary_is_independent_per_color(self):
        self.post(is_primary='true')
        self.post(color=self.red.pk, is_primary='true')
        self.assertEqual(len(self.primaries(self.blue)), 1)
        self.assertEqual(len(self.primaries(self.red)), 1)

    def test_changing_color_of_a_primary_replaces_the_primary_of_the_target_color(self):
        red_primary = self.post(color=self.red.pk, is_primary='true').data['id']
        blue_primary = self.post(is_primary='true').data['id']
        response = self.api.patch(f'{URL}{blue_primary}/', {'color': self.red.pk}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([i.pk for i in self.primaries(self.red)], [blue_primary])
        self.assertFalse(ProductImage.objects.get(pk=red_primary).is_primary)

    def test_database_allows_only_one_primary_per_product_color(self):
        from django.db import IntegrityError, transaction

        self.post(is_primary='true')
        other = ProductImage.objects.create(product=self.product, color=self.blue, storage_key='x')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductImage.objects.filter(pk=other.pk).update(is_primary=True)

    def test_primary_comes_first_in_list_and_with_variants(self):
        self.make()
        self.post(sort_order=0)
        primary = self.post(sort_order=5, is_primary='true').data['id']
        listing = self.api.get(URL, {'product': self.product.pk}).data['results']
        self.assertEqual(listing[0]['id'], primary)
        images = self.api.get(f'/api/products/{self.product.pk}/with-variants/').data['images']
        self.assertEqual(images[0]['id'], primary)
        self.assertTrue(images[0]['is_primary'])

    def test_filter_by_is_primary(self):
        self.post()
        primary = self.post(is_primary='true').data['id']
        results = self.api.get(URL, {'is_primary': 'true'}).data['results']
        self.assertEqual([r['id'] for r in results], [primary])

    def test_deleting_the_primary_does_not_promote_another(self):
        other = self.post().data['id']
        primary = self.post(is_primary='true').data['id']
        self.api.delete(f'{URL}{primary}/')
        self.assertEqual(self.primaries(), [])
        self.assertFalse(ProductImage.objects.get(pk=other).is_primary)

    def test_a_new_primary_can_be_marked_after_deleting_the_old_one(self):
        primary = self.post(is_primary='true').data['id']
        self.api.delete(f'{URL}{primary}/')
        self.assertEqual(self.post(is_primary='true').status_code, 201)

    def test_grid_thumbnail_prefers_the_primary_then_the_lowest_order(self):
        self.make()
        self.make(color=self.red)
        self.post(sort_order=0)
        primary_key = self.post(sort_order=9, is_primary='true').data['storage_key']
        red_first = self.post(color=self.red.pk, sort_order=0).data['storage_key']
        self.post(color=self.red.pk, sort_order=1)
        rows = {r['color']: r for r in self.api.get('/api/product-variants/').data['results']}
        self.assertEqual(rows[self.blue.pk]['image_url'], f'https://fake.test/{primary_key}')
        self.assertEqual(rows[self.red.pk]['image_url'], f'https://fake.test/{red_first}')


class PublishedProductKeepsAPhotoTests(ImageTestCase):
    """Con el producto publicado tiene que quedar al menos una variante con foto."""

    def setUp(self):
        super().setUp()
        self.make()  # Azul / M
        self.make(color=self.red)
        self.blue_photo = self.post().data['id']
        self.api.patch(f'/api/products/{self.product.pk}/', {'is_published': True}, format='json')
        self.assertTrue(self.product.__class__.objects.get(pk=self.product.pk).is_published)

    def delete_image(self, pk):
        return self.api.delete(f'{URL}{pk}/')

    def test_cannot_delete_the_last_photo_of_a_published_product(self):
        response = self.delete_image(self.blue_photo)
        self.assertEqual(response.status_code, 400)
        self.assertIn('última foto', str(response.data))
        self.assertEqual(ProductImage.objects.count(), 1)
        self.assertEqual(FakeImageStorage.deleted, [])  # tampoco se toca el archivo

    def test_can_delete_a_photo_when_another_variant_keeps_one(self):
        red_photo = self.post(color=self.red.pk).data['id']
        self.assertEqual(self.delete_image(self.blue_photo).status_code, 204)
        self.assertEqual(self.delete_image(red_photo).status_code, 400)

    def test_can_delete_one_of_several_photos_of_the_same_color(self):
        second = self.post().data['id']
        self.assertEqual(self.delete_image(second).status_code, 204)
        self.assertEqual(self.delete_image(self.blue_photo).status_code, 400)

    def test_can_delete_the_last_photo_after_unpublishing(self):
        self.api.patch(f'/api/products/{self.product.pk}/', {'is_published': False}, format='json')
        self.assertEqual(self.delete_image(self.blue_photo).status_code, 204)

    def test_cannot_move_the_last_photo_to_a_color_without_variants(self):
        from products.models import Color

        green = Color.objects.create(name='Verde')
        response = self.api.patch(f'{URL}{self.blue_photo}/', {'color': green.pk}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('color', response.data)
        self.assertEqual(ProductImage.objects.get().color_id, self.blue.pk)

    def test_can_move_the_last_photo_to_a_color_that_has_a_variant(self):
        response = self.api.patch(f'{URL}{self.blue_photo}/', {'color': self.red.pk}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

    def test_editing_other_fields_of_the_last_photo_is_fine(self):
        response = self.api.patch(f'{URL}{self.blue_photo}/', {'alt_text': 'Frente', 'sort_order': 3}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

    def test_cannot_delete_the_last_variant_with_photo(self):
        from products.models import ProductVariant

        blue_variant = ProductVariant.objects.get(product=self.product, color=self.blue)
        response = self.api.delete(f'/api/product-variants/{blue_variant.pk}/')
        self.assertEqual(response.status_code, 400)
        self.assertIn('última variante con foto', str(response.data))
        self.assertTrue(ProductVariant.objects.filter(pk=blue_variant.pk).exists())

    def test_can_delete_a_variant_without_photo_or_with_another_covering_one(self):
        from products.models import ProductVariant

        red_variant = ProductVariant.objects.get(product=self.product, color=self.red)
        self.assertEqual(self.api.delete(f'/api/product-variants/{red_variant.pk}/').status_code, 204)

    def test_cannot_change_the_color_of_the_last_variant_with_photo(self):
        from products.models import ProductVariant

        blue_variant = ProductVariant.objects.get(product=self.product, color=self.blue)
        response = self.api.patch(f'/api/product-variants/{blue_variant.pk}/', {'color': self.red.pk}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('color', response.data)

    def test_legacy_published_product_without_photos_is_not_blocked_by_the_photo_rule(self):
        # Publicado antes de la regla y sin fotos: la cobertura no cambia, así que no se bloquea.
        from products.models import Product, ProductVariant

        other = Product.objects.create(name='Heredado', category=self.category, sale_price=1, is_published=True)
        ProductVariant.objects.create(product=other, color=self.blue, size=self.s)
        removable = ProductVariant.objects.create(product=other, color=self.red, size=self.s)
        self.assertEqual(self.api.delete(f'/api/product-variants/{removable.pk}/').status_code, 204)
