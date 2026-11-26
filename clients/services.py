from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from clients.models import Client


class ClientService:
    """Encapsula la lógica de negocio para el alta de clientes."""

    @staticmethod
    @transaction.atomic
    def create_client(data, user=None):
        data = dict(data)
        email = data['email'] = data['email'].strip().lower()

        # select_for_update: bloquea la fila (si existe) hasta el commit,
        # para que dos requests concurrentes con el mismo email no lean
        # ambos "no existe" antes de que el primero haga commit.
        existing = Client.all_objects.select_for_update().filter(email__iexact=email).first()
        if existing:
            if not existing.is_deleted:
                raise ValidationError('Ya existe un cliente con este email.')
            return ClientService._restore_client(existing, data, user)

        try:
            return Client.objects.create(**data, created_by=user, updated_by=user)
        except IntegrityError as exc:
            # Red de seguridad: si igual se cuelan dos creates simultáneos
            # con el mismo email (p. ej. select_for_update no aplicable por
            # no soportar el backend, o ambos entraron antes del lock), no
            # dejar que la IntegrityError se propague como 500.
            raise ValidationError('Ya existe un cliente con este email.') from exc

    @staticmethod
    def _restore_client(client, data, user):
        client.is_deleted = False
        client.deleted_at = None
        client.deleted_by = None

        # Se pisan TODOS los campos de datos: lo que no venga en el request
        # queda vacío, para que el cliente nuevo no herede datos personales
        # (teléfono, etc.) del registro borrado.
        client.first_name = data['first_name']
        client.last_name = data['last_name']
        client.phone = data.get('phone')
        client.email = data['email']
        client.origin = data['origin']
        client.created_by = user
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
            'created_by',
            'updated_by',
            'updated_at',
        ])

        return client
