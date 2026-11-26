"""
Almacenamiento de imágenes detrás de una interfaz (adaptador).

El resto del sistema habla con `ImageStorage` y nunca con el proveedor, así el
proveedor se puede cambiar sin tocar los módulos de dominio y los tests usan un
almacenamiento falso. Se elige con `settings.IMAGE_STORAGE` (ruta de la clase).

Alcance: imágenes públicas del catálogo. Los archivos privados (ebooks, ADR 0004)
NO pasan por acá: requieren URLs firmadas y expirables, otra decisión.
"""
import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.module_loading import import_string

__all__ = [
    'ImageStorage',
    'ImageStorageError',
    'ImageStorageNotConfigured',
    'CloudinaryImageStorage',
    'get_image_storage',
    'validate_image_upload',
]

logger = logging.getLogger(__name__)

# Firmas de archivo (magic bytes). Se confía en el contenido, nunca en el
# `Content-Type` ni en la extensión que declara el cliente.
ALLOWED_IMAGE_TYPES = ('JPEG', 'PNG', 'WEBP')


class ImageStorageError(Exception):
    """El proveedor falló o rechazó la operación."""


class ImageStorageNotConfigured(ImageStorageError):
    """Faltan las credenciales del proveedor."""


def sniff_image_type(header: bytes):
    """Devuelve 'JPEG', 'PNG', 'WEBP' o None según los primeros bytes del archivo."""
    if header.startswith(b'\xff\xd8\xff'):
        return 'JPEG'
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'PNG'
    if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        return 'WEBP'
    return None


def validate_image_upload(file) -> str:
    """
    Valida un archivo subido: no vacío, dentro del tamaño máximo y con contenido de
    imagen JPEG/PNG/WEBP. Devuelve el tipo detectado o lanza `ValidationError`.
    (SVG y GIF quedan afuera a propósito: el SVG puede traer scripts.)
    """
    max_bytes = settings.IMAGE_MAX_BYTES
    if not file.size:
        raise ValidationError('El archivo está vacío.')
    if file.size > max_bytes:
        raise ValidationError(f'La imagen pesa {file.size / 1024 / 1024:.1f} MB y el máximo es {max_bytes / 1024 / 1024:.0f} MB.')
    position = file.tell() if hasattr(file, 'tell') else 0
    file.seek(0)
    header = file.read(12)
    file.seek(position)
    kind = sniff_image_type(header)
    if kind is None:
        raise ValidationError('El archivo no es una imagen válida. Formatos admitidos: JPEG, PNG y WEBP.')
    return kind


class ImageStorage:
    """Interfaz que debe cumplir cualquier proveedor."""

    def upload(self, file, folder: str) -> str:
        """Sube `file` a `folder` y devuelve la clave (`storage_key`) con la que se lo recupera."""
        raise NotImplementedError

    def delete(self, key: str) -> None:
        """Borra el archivo del proveedor. Debe tolerar que ya no exista."""
        raise NotImplementedError

    def url(self, key: str, width=None, height=None) -> str:
        """URL pública de entrega ('' si no hay proveedor configurado). Con `width`/`height` recorta y centra."""
        raise NotImplementedError


class CloudinaryImageStorage(ImageStorage):
    """
    Cloudinary. La clave guardada es el `public_id` (incluye la carpeta). La URL
    se arma sin llamar a la API; `f_auto,q_auto` hace que Cloudinary entregue el
    formato y la calidad óptimos para cada navegador.
    """

    DELIVERY = 'f_auto,q_auto'

    @property
    def cloud_name(self):
        return settings.CLOUDINARY_CLOUD_NAME

    @property
    def is_configured(self) -> bool:
        return bool(self.cloud_name and settings.CLOUDINARY_API_KEY and settings.CLOUDINARY_API_SECRET)

    def _credentials(self) -> dict:
        if not self.is_configured:
            raise ImageStorageNotConfigured(
                'Cloudinary no está configurado: definir CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY y CLOUDINARY_API_SECRET.'
            )
        return {
            'cloud_name': self.cloud_name,
            'api_key': settings.CLOUDINARY_API_KEY,
            'api_secret': settings.CLOUDINARY_API_SECRET,
            'secure': True,
        }

    def upload(self, file, folder: str) -> str:
        credentials = self._credentials()
        import cloudinary.uploader  # import tardío: sólo hace falta al subir

        try:
            result = cloudinary.uploader.upload(
                file,
                folder=folder,
                resource_type='image',
                # Nombre aleatorio: no se confía en el nombre que trae el cliente.
                use_filename=False,
                unique_filename=True,
                overwrite=False,
                **credentials,
            )
        except Exception as exc:  # errores de API y de red del SDK
            logger.exception('Falló la subida a Cloudinary')
            raise ImageStorageError('No se pudo subir la imagen a Cloudinary.') from exc
        return result['public_id']

    def delete(self, key: str) -> None:
        credentials = self._credentials()
        import cloudinary.uploader

        try:
            cloudinary.uploader.destroy(key, resource_type='image', invalidate=True, **credentials)
        except Exception as exc:
            logger.exception('Falló el borrado en Cloudinary (%s)', key)
            raise ImageStorageError('No se pudo borrar la imagen de Cloudinary.') from exc

    def url(self, key: str, width=None, height=None) -> str:
        if not (self.cloud_name and key):
            return ''
        steps = []
        if width or height:
            crop = ['c_fill']
            if width:
                crop.append(f'w_{width}')
            if height:
                crop.append(f'h_{height}')
            steps.append(','.join(crop))
        steps.append(self.DELIVERY)
        return f'https://res.cloudinary.com/{self.cloud_name}/image/upload/{"/".join(steps)}/{key}'


def get_image_storage() -> ImageStorage:
    return import_string(settings.IMAGE_STORAGE)()
