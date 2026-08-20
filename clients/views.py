from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError

from clients.models import Client
from clients.schemas import CLIENT_VIEWSET_SCHEMA
from clients.serializers import ClientSerializer
from clients.services import ClientService
from core.viewsets import BaseModelViewSet


@CLIENT_VIEWSET_SCHEMA
class ClientViewSet(BaseModelViewSet):
    queryset = Client.objects.all()
    serializer_class = ClientSerializer

    def perform_create(self, serializer):
        try:
            client = ClientService.create_client(serializer.validated_data, user=self.request.user)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc

        serializer.instance = client
