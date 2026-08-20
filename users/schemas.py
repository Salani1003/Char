"""
Documentación OpenAPI (drf-spectacular) de las views de `users`.

Ver `core/schemas.py` para la convención general del proyecto: la
documentación vive acá, no en `views.py`.
"""
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema, extend_schema_view

from core.schemas import FORBIDDEN, NOT_FOUND, UNAUTHORIZED, VALIDATION_ERROR

__all__ = [
    'TOKEN_OBTAIN_SCHEMA',
    'TOKEN_REFRESH_SCHEMA',
    'USER_VIEWSET_SCHEMA',
    'GROUP_VIEWSET_SCHEMA',
]

_ACCESS_TOKEN_EXAMPLE = (
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.'
    'eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzYwOTU5MjAwfQ.'
    'access-signature'
)
_NEW_ACCESS_TOKEN_EXAMPLE = (
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.'
    'eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzYwOTU5MjAwfQ.'
    'new-access-signature'
)
_REFRESH_TOKEN_EXAMPLE = (
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.'
    'eyJ0b2tlbl90eXBlIjoicmVmcmVzaCIsImV4cCI6MTc2MTU2NDAwMH0.'
    'refresh-signature'
)

TOKEN_OBTAIN_SCHEMA = extend_schema(
    tags=['Auth'],
    summary='Obtener par de tokens JWT',
    description=(
        'Autentica a un usuario usando su email y contraseña, y devuelve un '
        'par de JSON Web Tokens: un token `access` (usado para autenticar '
        'las siguientes solicitudes) y un token `refresh` (usado para obtener '
        'nuevos tokens de acceso sin reenviar las credenciales).'
    ),
    examples=[
        OpenApiExample(
            'Solicitud de login',
            value={'email': 'demo@demo.com', 'password': '1234'},
            request_only=True,
        ),
        OpenApiExample(
            'Login exitoso',
            value={'access': _ACCESS_TOKEN_EXAMPLE, 'refresh': _REFRESH_TOKEN_EXAMPLE},
            response_only=True,
            status_codes=['200'],
        ),
        OpenApiExample(
            'Credenciales inválidas',
            value={'detail': 'No active account found with the given credentials'},
            response_only=True,
            status_codes=['401'],
        ),
    ],
    responses={
        401: OpenApiResponse(description='Email o contraseña inválidos.'),
    },
)

TOKEN_REFRESH_SCHEMA = extend_schema(
    tags=['Auth'],
    summary='Renovar token de acceso',
    description=(
        'Toma un token `refresh` válido y devuelve un nuevo token `access`, '
        'sin requerir que el usuario reenvíe sus credenciales.'
    ),
    examples=[
        OpenApiExample(
            'Solicitud de renovación',
            value={'refresh': _REFRESH_TOKEN_EXAMPLE},
            request_only=True,
        ),
        OpenApiExample(
            'Renovación exitosa',
            value={'access': _NEW_ACCESS_TOKEN_EXAMPLE},
            response_only=True,
            status_codes=['200'],
        ),
        OpenApiExample(
            'Token de refresco inválido o expirado',
            value={'detail': 'Token is invalid or expired', 'code': 'token_not_valid'},
            response_only=True,
            status_codes=['401'],
        ),
    ],
    responses={
        401: OpenApiResponse(description='El token de refresco es inválido, expiró o fue revocado.'),
    },
)

USER_VIEWSET_SCHEMA = extend_schema_view(
    list=extend_schema(
        tags=['Users'],
        summary='Listar usuarios',
        description='Lista los usuarios internos. Requiere permiso `users.view_user`.',
        responses={401: UNAUTHORIZED, 403: FORBIDDEN},
    ),
    retrieve=extend_schema(
        tags=['Users'],
        summary='Obtener un usuario',
        description='Requiere permiso `users.view_user`.',
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
    create=extend_schema(
        tags=['Users'],
        summary='Crear un usuario interno',
        description=(
            'Crea un usuario interno. No hay registro público: sólo un '
            'Administrador con permiso `users.add_user` puede crear usuarios. '
            'Los roles se asignan vía `groups`; `is_staff`/`is_superuser` son '
            'de sólo lectura desde este endpoint.'
        ),
        examples=[
            OpenApiExample(
                'Alta de usuario',
                value={
                    'email': 'jane.doe@example.com',
                    'password': 'S3curePass!',
                    'first_name': 'Jane',
                    'last_name': 'Doe',
                    'groups': [1],
                },
                request_only=True,
            ),
        ],
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 400: VALIDATION_ERROR},
    ),
    update=extend_schema(
        tags=['Users'],
        summary='Actualizar un usuario',
        description='Requiere permiso `users.change_user`. Permite reasignar `groups` (roles).',
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND, 400: VALIDATION_ERROR},
    ),
    partial_update=extend_schema(
        tags=['Users'],
        summary='Actualizar parcialmente un usuario',
        description='Requiere permiso `users.change_user`. Permite reasignar `groups` (roles).',
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND, 400: VALIDATION_ERROR},
    ),
    destroy=extend_schema(
        tags=['Users'],
        summary='Eliminar un usuario',
        description='Requiere permiso `users.delete_user`.',
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
)

GROUP_VIEWSET_SCHEMA = extend_schema_view(
    list=extend_schema(
        tags=['Users'],
        summary='Listar roles (Groups)',
        description=(
            'Lista los Groups de Django disponibles para asignar como rol a '
            'un usuario. Requiere permiso `auth.view_group`.'
        ),
        responses={401: UNAUTHORIZED, 403: FORBIDDEN},
    ),
    retrieve=extend_schema(
        tags=['Users'],
        summary='Obtener un rol (Group)',
        description='Requiere permiso `auth.view_group`.',
        responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
)
