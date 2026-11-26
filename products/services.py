from core.media import get_image_storage
from products.models import ProductImage

__all__ = ['clear_primary_images', 'delete_image']


def clear_primary_images(product, color, exclude_pk=None) -> None:
    """
    Desmarca la imagen principal vigente de un producto-color. Se llama ANTES de guardar la nueva
    principal: el índice único parcial no admite dos principales ni un instante.
    """
    ProductImage.objects.filter(product=product, color=color, is_primary=True).exclude(pk=exclude_pk).update(
        is_primary=False
    )


def delete_image(image, user) -> None:
    """
    Elimina una imagen: primero borra el archivo del proveedor y recién después la marca como
    eliminada. Si el proveedor falla se propaga `ImageStorageError` y la imagen NO se elimina
    (nunca queda un registro borrado con el archivo vivo y público). No es restaurable.
    """
    get_image_storage().delete(image.storage_key)
    image.delete(user)
