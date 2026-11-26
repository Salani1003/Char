import io
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from core.media import (
    CloudinaryImageStorage,
    ImageStorageError,
    ImageStorageNotConfigured,
    get_image_storage,
    sniff_image_type,
    validate_image_upload,
)
from core.tests.fakes import FakeImageStorage

CONFIGURED = dict(CLOUDINARY_CLOUD_NAME='demo', CLOUDINARY_API_KEY='key', CLOUDINARY_API_SECRET='secret')


class SniffTests(SimpleTestCase):
    def test_detects_supported_formats(self):
        self.assertEqual(sniff_image_type(b'\xff\xd8\xff\xe0' + b'\0' * 8), 'JPEG')
        self.assertEqual(sniff_image_type(b'\x89PNG\r\n\x1a\n' + b'\0' * 4), 'PNG')
        self.assertEqual(sniff_image_type(b'RIFF\0\0\0\0WEBP'), 'WEBP')

    def test_rejects_everything_else(self):
        for header in (b'GIF89a', b'%PDF-1.7', b'<svg xmlns', b'', b'RIFF\0\0\0\0WAVE'):
            self.assertIsNone(sniff_image_type(header.ljust(12, b'\0')), header)


class ValidateUploadTests(SimpleTestCase):
    def file(self, content, name='a.png'):
        return SimpleUploadedFile(name, content)

    def test_valid_image_passes_and_stream_is_rewound(self):
        f = self.file(b'\x89PNG\r\n\x1a\n' + b'\0' * 20)
        self.assertEqual(validate_image_upload(f), 'PNG')
        self.assertEqual(f.read(4), b'\x89PNG')

    @override_settings(IMAGE_MAX_BYTES=10)
    def test_too_big(self):
        with self.assertRaisesMessage(ValidationError, 'máximo'):
            validate_image_upload(self.file(b'\x89PNG\r\n\x1a\n' + b'\0' * 20))

    def test_empty_and_invalid(self):
        with self.assertRaises(ValidationError):
            validate_image_upload(self.file(b''))
        with self.assertRaises(ValidationError):
            validate_image_upload(self.file(b'no soy una imagen'))


@override_settings(**CONFIGURED, IMAGE_STORAGE='core.media.CloudinaryImageStorage')
class CloudinaryStorageTests(SimpleTestCase):
    def test_url_has_optimal_delivery_and_no_api_call(self):
        self.assertEqual(
            CloudinaryImageStorage().url('char/products/1/abc'),
            'https://res.cloudinary.com/demo/image/upload/f_auto,q_auto/char/products/1/abc',
        )

    def test_thumbnail_url_crops(self):
        self.assertEqual(
            CloudinaryImageStorage().url('char/x', width=400, height=400),
            'https://res.cloudinary.com/demo/image/upload/c_fill,w_400,h_400/f_auto,q_auto/char/x',
        )

    def test_url_is_empty_without_cloud_name_or_key(self):
        with override_settings(CLOUDINARY_CLOUD_NAME=''):
            self.assertEqual(CloudinaryImageStorage().url('char/x'), '')
        self.assertEqual(CloudinaryImageStorage().url(''), '')

    def test_upload_sends_folder_random_name_and_credentials_and_returns_public_id(self):
        with mock.patch('cloudinary.uploader.upload', return_value={'public_id': 'char/products/1/abc'}) as upload:
            key = CloudinaryImageStorage().upload(io.BytesIO(b'x'), 'char/products/1')
        self.assertEqual(key, 'char/products/1/abc')
        kwargs = upload.call_args.kwargs
        self.assertEqual(kwargs['folder'], 'char/products/1')
        self.assertFalse(kwargs['use_filename'])
        self.assertTrue(kwargs['unique_filename'])
        self.assertEqual((kwargs['cloud_name'], kwargs['api_key'], kwargs['api_secret']), ('demo', 'key', 'secret'))

    def test_provider_errors_are_wrapped(self):
        with mock.patch('cloudinary.uploader.upload', side_effect=RuntimeError('boom')):
            with self.assertRaises(ImageStorageError):
                CloudinaryImageStorage().upload(io.BytesIO(b'x'), 'char')

    def test_delete_calls_destroy(self):
        with mock.patch('cloudinary.uploader.destroy') as destroy:
            CloudinaryImageStorage().delete('char/x')
        self.assertEqual(destroy.call_args.args, ('char/x',))

    @override_settings(CLOUDINARY_API_SECRET='')
    def test_not_configured_raises_a_specific_error(self):
        with self.assertRaises(ImageStorageNotConfigured):
            CloudinaryImageStorage().upload(io.BytesIO(b'x'), 'char')
        with self.assertRaises(ImageStorageNotConfigured):
            CloudinaryImageStorage().delete('char/x')

    def test_default_storage_is_cloudinary(self):
        self.assertIsInstance(get_image_storage(), CloudinaryImageStorage)


@override_settings(IMAGE_STORAGE='core.tests.fakes.FakeImageStorage', IMAGE_FOLDER='test')
class CheckImageStorageCommandTests(SimpleTestCase):
    def setUp(self):
        FakeImageStorage.reset()

    def test_uploads_and_deletes_a_pixel(self):
        out = io.StringIO()
        call_command('check_image_storage', stdout=out)
        self.assertEqual(len(FakeImageStorage.uploaded), 1)
        self.assertTrue(FakeImageStorage.uploaded[0][0].startswith('test/_healthcheck/'))
        self.assertEqual(FakeImageStorage.deleted, [FakeImageStorage.uploaded[0][0]])
        self.assertIn('funciona', out.getvalue())

    def test_reports_configuration_errors(self):
        FakeImageStorage.configured = False
        with self.assertRaises(CommandError):
            call_command('check_image_storage', stdout=io.StringIO())
