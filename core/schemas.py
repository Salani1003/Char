"""
Piezas de documentación OpenAPI (drf-spectacular) reutilizables entre apps.

Convención del proyecto: la documentación de cada endpoint vive en un módulo
`schemas.py` al lado de `views.py`, nunca dentro de la view. Cada view queda
así reducida a su decorador (`@algo_schema`), sin ruido visual de
descripciones, ejemplos o respuestas de error.

Este módulo junta lo que se repite entre apps (respuestas de error comunes,
etc.) para que `<app>/schemas.py` no tenga que redefinirlo cada vez.
"""
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers

__all__ = ['UNAUTHORIZED', 'FORBIDDEN', 'NOT_FOUND', 'VALIDATION_ERROR', 'HEALTH_SCHEMA']

UNAUTHORIZED = OpenApiResponse(description='Credenciales inválidas o ausentes.')
FORBIDDEN = OpenApiResponse(description='El usuario no tiene permiso para realizar esta acción.')
NOT_FOUND = OpenApiResponse(description='El recurso solicitado no existe.')
VALIDATION_ERROR = OpenApiResponse(description='Los datos enviados no son válidos.')

HEALTH_SCHEMA = extend_schema(
    tags=['Core'],
    summary='Healthcheck',
    description='Endpoint público para verificar que el servicio está arriba.',
    responses=inline_serializer('HealthResponse', {'status': serializers.CharField()}),
    examples=[
        OpenApiExample(
            'Servicio saludable',
            value={'status': 'ok'},
            response_only=True,
            status_codes=['200'],
        ),
    ],
)
