from rest_framework import serializers

from clients.models import Client


class ClientSerializer(serializers.ModelSerializer):
    # Se desactiva el UniqueValidator automático de DRF: consulta
    # `Client._default_manager` (`objects`), que excluye los soft-deleted,
    # mientras que la constraint `unique=True` de la base sí los ve. Ese
    # desacople hacía que un update con el email de un cliente borrado
    # pasara la validación y reventara con IntegrityError (500). La
    # validación real vive en `validate_email`, contra `all_objects`.
    email = serializers.EmailField(required=False, allow_null=True, validators=[])

    class Meta:
        model = Client
        fields = [
            'id',
            'first_name',
            'last_name',
            'phone',
            'email',
            'origin',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def validate_email(self, value):
        if not value:
            return value

        existing = Client.all_objects.filter(email=value)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        existing = existing.first()

        if existing is None:
            return value

        if not existing.is_deleted:
            raise serializers.ValidationError('Ya existe un cliente con este email.')

        if self.instance is not None:
            # En un update no hay restauración automática (eso sólo pasa en
            # create, vía ClientService): avisar en vez de dejar pasar un
            # email que rompería la constraint de la base.
            raise serializers.ValidationError(
                'Este email pertenece a un cliente eliminado. Restaurá ese '
                'cliente en lugar de asignarle el email a otro.'
            )

        # En create: se deja pasar. ClientService.create_client vuelve a
        # buscar en all_objects y restaura el cliente borrado en lugar de
        # crear uno nuevo.
        return value
