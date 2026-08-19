from clients.models import Client
from clients.serializers import ClientSerializer
from core.viewsets import BaseModelViewSet


class ClientViewSet(BaseModelViewSet):
    queryset = Client.objects.all()
    serializer_class = ClientSerializer
