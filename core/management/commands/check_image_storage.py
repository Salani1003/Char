import base64

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError

from core.media import ImageStorageError, get_image_storage

# PNG de 1x1 píxel.
_PIXEL = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
)


class Command(BaseCommand):
    help = 'Verifica las credenciales del almacenamiento de imágenes: sube un PNG de 1x1, lo muestra y lo borra.'

    def handle(self, *args, **options):
        storage = get_image_storage()
        folder = f'{settings.IMAGE_FOLDER}/_healthcheck'
        try:
            key = storage.upload(SimpleUploadedFile('check.png', _PIXEL, content_type='image/png'), folder)
        except ImageStorageError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f'Subida OK: {key}'))
        self.stdout.write(f'URL: {storage.url(key)}')
        try:
            storage.delete(key)
        except ImageStorageError as exc:
            raise CommandError(f'Se subió pero no se pudo borrar ({key}): {exc}') from exc
        self.stdout.write(self.style.SUCCESS('Borrado OK. El almacenamiento de imágenes funciona.'))
