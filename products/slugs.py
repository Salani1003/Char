"""
Generación de slugs (la "dirección" de un producto, marca o categoría en la
futura tienda). El backend decide el slug cuando el cliente no lo envía, para
que el front no tenga que adivinar colisiones.
"""
from itertools import chain, count

from django.utils.text import slugify

__all__ = ['generate_unique_slug']

DEFAULT_SLUG = 'item'


def _candidates(base, prefix):
    """`base`, luego `prefijo-base` (ej. `vestidos-largos`) y por último `base-2`, `base-3`..."""
    first = [base]
    if prefix:
        first.append(f'{prefix}-{base}')
    return chain(first, (f'{base}-{n}' for n in count(2)))


def generate_unique_slug(model, name, prefix=None, exclude=(), exclude_pk=None):
    """
    Devuelve un slug libre entre los registros ACTIVOS de `model` (la
    unicidad es `unique_when_active`: el slug de un registro eliminado se
    puede reutilizar). `prefix` desambigua antes de recurrir a un número
    (para una subcategoría, el slug de su padre). `exclude` descarta slugs ya
    intentados (reintento tras una carrera entre dos altas simultáneas).
    `exclude_pk` ignora a ese registro, para regenerar el slug de uno
    existente sin que su dirección actual cuente como ocupada.
    """
    limit = model._meta.get_field('slug').max_length
    base = slugify(name)[: limit - 6].strip('-') or DEFAULT_SLUG
    for candidate in _candidates(base, prefix):
        candidate = candidate[:limit]
        if candidate in exclude:
            continue
        if not model.objects.filter(slug=candidate).exclude(pk=exclude_pk).exists():
            return candidate
