from django.core.exceptions import ValidationError
from django.db import transaction

from clients.models import Client


class ClientService:
    """Encapsula la lógica de negocio para el alta de clientes."""

    @staticmethod
    @transaction.atomic
    def create_client(data, user=None):
        email = data.get('email')

        if email:
            existing = Client.all_objects.filter(email=email).first()
            if existing:
                if not existing.is_deleted:
                    raise ValidationError('Ya existe un cliente con este email.')
                return ClientService._restore_client(existing, data, user)

        return Client.objects.create(**data, created_by=user, updated_by=user)

    @staticmethod
    def _restore_client(client, data, user):
        client.is_deleted = False
        client.deleted_at = None
        client.deleted_by = None

        client.first_name = data.get('first_name', client.first_name)
        client.last_name = data.get('last_name', client.last_name)
        client.phone = data.get('phone', client.phone)
        client.email = data.get('email', client.email)
        client.origin = data.get('origin', client.origin)
        client.set_updated_by(user)

        client.save(update_fields=[
            'is_deleted',
            'deleted_at',
            'deleted_by',
            'first_name',
            'last_name',
            'phone',
            'email',
            'origin',
            'updated_by',
        ])

        return client
