"""
Documentación OpenAPI (drf-spectacular) de las views de `clients`.

Ver `core/schemas.py` para la convención general del proyecto: la
documentación vive acá, no en `views.py`.
"""
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema, extend_schema_view

from core.schemas import FORBIDDEN, NOT_FOUND, UNAUTHORIZED, VALIDATION_ERROR

__all__ = ['CLIENT_VIEWSET_SCHEMA']

_CLIENT_ID_PARAMETER = OpenApiParameter(
    name='id',
    location=OpenApiParameter.PATH,
    description='Identificador único del cliente.',
    type=int,
)

_CLIENT_EXAMPLE = OpenApiExample(
    'Cliente',
    value={
        'id': 1,
        'first_name': 'Ada',
        'last_name': 'Lovelace',
        'phone': '+54 9 11 1234-5678',
        'email': 'ada@example.com',
        'origin': 'instagram',
        'created_at': '2026-01-15T12:00:00Z',
    },
    response_only=True,
)

CLIENT_VIEWSET_SCHEMA = extend_schema_view(
    list=extend_schema(
        tags=['Clients'],
        summary='Listar clientes',
        description='Lista los clientes (excluye los eliminados). Requiere permiso `clients.view_client`.',
        responses={401: UNAUTHORIZED, 403: FORBIDDEN},
        examples=[_CLIENT_EXAMPLE],
    ),
    retrieve=extend_schema(
        tags=['Clients'],
        summary='Obtener un cliente',
        description='Requiere permiso `clients.view_client`.',
        parameters=[_CLIENT_ID_PARAMETER],
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
        examples=[_CLIENT_EXAMPLE],
    ),
    create=extend_schema(
        tags=['Clients'],
        summary='Crear un cliente',
        description=(
            'Crea un cliente. Requiere permiso `clients.add_client`. Si ya '
            'existe un cliente eliminado (soft delete) con el mismo `email`, '
            'se restaura y actualiza en lugar de crear uno nuevo.'
        ),
        examples=[
            OpenApiExample(
                'Alta de cliente',
                value={
                    'first_name': 'Ada',
                    'last_name': 'Lovelace',
                    'phone': '+54 9 11 1234-5678',
                    'email': 'ada@example.com',
                    'origin': 'instagram',
                },
                request_only=True,
            ),
            _CLIENT_EXAMPLE,
        ],
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 400: VALIDATION_ERROR},
    ),
    update=extend_schema(
        tags=['Clients'],
        summary='Actualizar un cliente',
        description='Requiere permiso `clients.change_client`.',
        parameters=[_CLIENT_ID_PARAMETER],
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND, 400: VALIDATION_ERROR},
    ),
    partial_update=extend_schema(
        tags=['Clients'],
        summary='Actualizar parcialmente un cliente',
        description='Requiere permiso `clients.change_client`.',
        parameters=[_CLIENT_ID_PARAMETER],
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND, 400: VALIDATION_ERROR},
    ),
    destroy=extend_schema(
        tags=['Clients'],
        summary='Eliminar un cliente',
        description=(
            'Elimina (soft delete) un cliente. Requiere permiso '
            '`clients.delete_client`.'
        ),
        parameters=[_CLIENT_ID_PARAMETER],
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
)
