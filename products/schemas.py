"""
Documentación OpenAPI (drf-spectacular) de las views de `products`.

Ver `core/schemas.py` para la convención general del proyecto: la
documentación vive acá, no en `views.py`.
"""
from drf_spectacular.utils import OpenApiExample, extend_schema, extend_schema_view

from core.schemas import FORBIDDEN, NOT_FOUND, UNAUTHORIZED, VALIDATION_ERROR

__all__ = [
    'CATEGORIA_VIEWSET_SCHEMA',
]

CATEGORIA_VIEWSET_SCHEMA = extend_schema_view(
    list=extend_schema(
        tags=['Products'],
        summary='Listar categorías',
        description='Lista las categorías de productos. Requiere permiso `products.view_categoria`.',
        responses={401: UNAUTHORIZED, 403: FORBIDDEN},
    ),
    retrieve=extend_schema(
        tags=['Products'],
        summary='Obtener una categoría',
        description='Requiere permiso `products.view_categoria`.',
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
    create=extend_schema(
        tags=['Products'],
        summary='Crear una categoría',
        description='Requiere permiso `products.add_categoria`.',
        examples=[
            OpenApiExample(
                'Alta de categoría',
                value={'nombre': 'Remeras'},
                request_only=True,
            ),
        ],
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 400: VALIDATION_ERROR},
    ),
    update=extend_schema(
        tags=['Products'],
        summary='Actualizar una categoría',
        description='Requiere permiso `products.change_categoria`.',
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND, 400: VALIDATION_ERROR},
    ),
    partial_update=extend_schema(
        tags=['Products'],
        summary='Actualizar parcialmente una categoría',
        description='Requiere permiso `products.change_categoria`.',
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND, 400: VALIDATION_ERROR},
    ),
    destroy=extend_schema(
        tags=['Products'],
        summary='Eliminar una categoría (soft delete)',
        description='Requiere permiso `products.delete_categoria`.',
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
)
