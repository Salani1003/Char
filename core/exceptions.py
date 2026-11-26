from rest_framework.exceptions import APIException

__all__ = ['ImageStorageUnavailable', 'ImageUploadFailed', 'ImageDeleteFailed']


class ImageStorageUnavailable(APIException):
    status_code = 503
    default_detail = 'El almacenamiento de imágenes no está configurado.'
    default_code = 'image_storage_unavailable'


class ImageUploadFailed(APIException):
    status_code = 502
    default_detail = 'No se pudo subir la imagen. Intente de nuevo.'
    default_code = 'image_upload_failed'


class ImageDeleteFailed(APIException):
    status_code = 502
    default_detail = 'No se pudo eliminar la imagen del almacenamiento. La imagen no se eliminó: intente de nuevo.'
    default_code = 'image_delete_failed'
