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

        from django.db import models
        from django.test.utils import isolate_apps

        from core.models import BaseModel

        with isolate_apps('core'):

            class Parent(BaseModel):
                class Meta:
                    app_label = 'core'

            class Child(BaseModel):
                parent = models.ForeignKey(Parent, on_delete=models.CASCADE, related_name='children')

                class Meta:
                    app_label = 'core'

            class ParentSerializer(BaseModelSerializer):
                children = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

                class Meta:
                    model = Parent
                    fields = ['id', 'children']

            self.assertIn('children', ParentSerializer().fields)
