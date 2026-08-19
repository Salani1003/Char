from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView


@extend_schema(
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
            value={'email': 'jane.doe@example.com', 'password': 'S3curePass!'},
            request_only=True,
        ),
        OpenApiExample(
            'Login exitoso',
            value={
                'access': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzYwOTU5MjAwfQ.access-signature',
                'refresh': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoicmVmcmVzaCIsImV4cCI6MTc2MTU2NDAwMH0.refresh-signature',
            },
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
class DocumentedTokenObtainPairView(TokenObtainPairView):
    pass


@extend_schema(
    tags=['Auth'],
    summary='Renovar token de acceso',
    description=(
        'Toma un token `refresh` válido y devuelve un nuevo token `access`, '
        'sin requerir que el usuario reenvíe sus credenciales.'
    ),
    examples=[
        OpenApiExample(
            'Solicitud de renovación',
            value={
                'refresh': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoicmVmcmVzaCIsImV4cCI6MTc2MTU2NDAwMH0.refresh-signature',
            },
            request_only=True,
        ),
        OpenApiExample(
            'Renovación exitosa',
            value={
                'access': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzYwOTU5MjAwfQ.new-access-signature',
            },
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
class DocumentedTokenRefreshView(TokenRefreshView):
    pass
