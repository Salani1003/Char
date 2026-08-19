from rest_framework import serializers

from clients.models import Client


class ClientSerializer(serializers.ModelSerializer):
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
