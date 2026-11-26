from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from users.models import User


class GroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = ['id', 'name']


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer de administración de usuarios internos.

    `is_staff`/`is_superuser` quedan de sólo lectura: son conceptos técnicos
    de Django (acceso al admin site / bypass total de permisos) y no deben
    poder asignarse desde este endpoint como si fueran un rol funcional de la
    aplicación. Los roles funcionales son los `groups` (Django Groups), que sí son
    escribibles acá para que un Administrador pueda asignarlos/modificarlos.
    """

    password = serializers.CharField(write_only=True, required=False, style={'input_type': 'password'})
    groups = serializers.PrimaryKeyRelatedField(many=True, queryset=Group.objects.all(), required=False)
    # Nombres de los grupos (roles) del usuario, para que el cliente sepa su rol sin
    # tener que consultar `/groups/` (que exige `auth.view_group`). De sólo lectura.
    group_names = serializers.SerializerMethodField(help_text='Nombres de los grupos (roles) del usuario.')

    class Meta:
        model = User
        fields = [
            'id',
            'email',
            'first_name',
            'last_name',
            'is_active',
            'is_staff',
            'is_superuser',
            'groups',
            'group_names',
            'password',
            'date_joined',
            'last_login',
        ]
        read_only_fields = ['is_staff', 'is_superuser', 'date_joined', 'last_login']

    def get_group_names(self, obj) -> list[str]:
        # `.all()` aprovecha el prefetch del viewset; se ordena en Python para no hacer otra consulta.
        return sorted(group.name for group in obj.groups.all())

    def validate_email(self, value):
        value = value.lower()
        existing = User.objects.filter(email__iexact=value)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError('Ya existe un usuario con este email.')
        return value

    def validate_is_active(self, value):
        # Anti-lockout: nadie se desactiva a sí mismo (el `DELETE` propio se
        # bloquea en `users.permissions.CanManageUser`).
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if value is False and self.instance is not None and user is not None and self.instance.pk == user.pk:
            raise serializers.ValidationError('No podés desactivar tu propio usuario.')
        return value

    def validate_groups(self, groups):
        """
        Anti-escalada de privilegios: quien no es superuser sólo puede
        asignar Groups que él mismo ya tiene. Sin esto, un usuario con
        `users.change_user` podría darse (o dar a otro) cualquier rol.
        """
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if user is None or user.is_superuser:
            return groups
        allowed = set(user.groups.values_list('pk', flat=True))
        forbidden = [g.name for g in groups if g.pk not in allowed]
        if forbidden:
            raise serializers.ValidationError(
                'No podés asignar roles que no tenés: ' + ', '.join(forbidden)
            )
        return groups

    def validate_password(self, value):
        validate_password(value, user=self.instance)
        return value

    def create(self, validated_data):
        if 'password' not in validated_data:
            raise serializers.ValidationError({'password': 'Este campo es obligatorio.'})
        password = validated_data.pop('password')
        groups = validated_data.pop('groups', [])
        user = User.objects.create_user(password=password, **validated_data)
        if groups:
            user.groups.set(groups)
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        groups = validated_data.pop('groups', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()

        if groups is not None:
            instance.groups.set(groups)

        return instance
