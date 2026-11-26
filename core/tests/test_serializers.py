from django.test import TestCase
from core.serializers import AUDIT_FIELDS, BaseModelSerializer
from users.models import User


class _UserLikeSerializer(BaseModelSerializer):
    """User no hereda de BaseModel: se usa sólo para probar la mecánica."""

    class Meta:
        model = User
        fields = ['id', 'email']


class BaseModelSerializerTests(TestCase):
    def test_audit_fields_constant(self):
        self.assertIn('created_by', AUDIT_FIELDS)

    def test_unique_validator_still_applies(self):
        User.objects.create_user(email='a@example.com', password='x')
        serializer = _UserLikeSerializer(data={'email': 'a@example.com'})
        self.assertFalse(serializer.is_valid())
        self.assertIn('email', serializer.errors)


class ReverseRelationFieldTests(TestCase):
    """`get_fields` no debe fallar con campos que son relaciones inversas (nested)."""

    def test_serializer_with_reverse_relation_builds_fields(self):
        from rest_framework import serializers

        from products.models import Categoria

        class CategoriaConProductos(BaseModelSerializer):
            productos = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

            class Meta:
                model = Categoria
                fields = ['id', 'nombre', 'productos']

        self.assertIn('productos', CategoriaConProductos().fields)
