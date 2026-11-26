from django.db import connection
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.schemas import HEALTH_SCHEMA


@HEALTH_SCHEMA
@api_view(['GET'])
@permission_classes([AllowAny])
# Sin throttling: lo consultan balanceadores/orquestadores a alta frecuencia
# desde una misma IP y un 429 haría que marquen el servicio como caído.
@throttle_classes([])
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
    except Exception:
        return Response({'status': 'error'}, status=503)
    return Response({'status': 'ok'})
