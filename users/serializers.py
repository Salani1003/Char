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
    poder asignarse desde este endpoint como si fueran un rol funcional de
    Char. Los roles funcionales son los `groups` (Django Groups), que sí son
    escribibles acá para que un Administrador pueda asignarlos/modificarlos.
    """

    password = serializers.CharField(write_only=True, required=False, style={'input_type': 'password'})
    groups = serializers.PrimaryKeyRelatedField(many=True, queryset=Group.objects.all(), required=False)

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
            'password',
            'date_joined',
            'last_login',
        ]
        read_only_fields = ['is_staff', 'is_superuser', 'date_joined', 'last_login']

    def validate_password(self, value):
        validate_password(value)
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
