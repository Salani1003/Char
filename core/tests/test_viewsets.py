from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext, isolate_apps
from rest_framework import serializers
from rest_framework.test import APIRequestFactory, force_authenticate

from core.models import BaseModel
from core.viewsets import BaseModelViewSet
from users.models import User


@isolate_apps('core')
class BaseModelViewSetAuditTests(TestCase):
    """
    Prueba de punta a punta que `BaseModelViewSet` asigna `created_by` al
    crear y `updated_by` al modificar, usando `serializer.save(created_by=request.user)`
    durante la creación y `serializer.save(updated_by=request.user)` durante la
    actualización, sobre el mismo modelo concreto de prueba usado en
    `SoftDeleteTests`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        class AuditViewSetModel(BaseModel):
            class Meta:
                app_label = 'core'

        cls.ConcreteModel = AuditViewSetModel
        with connection.schema_editor() as editor:
            editor.create_model(cls.ConcreteModel)

        class ConcreteModelSerializer(serializers.ModelSerializer):
            class Meta:
                model = AuditViewSetModel
                fields = ['id', 'created_by', 'updated_by']
                read_only_fields = ['created_by', 'updated_by']

        class ConcreteModelViewSet(BaseModelViewSet):
            queryset = AuditViewSetModel.all_objects.all()
            serializer_class = ConcreteModelSerializer

        cls.ConcreteModelViewSet = ConcreteModelViewSet

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            editor.delete_model(cls.ConcreteModel)
        super().tearDownClass()

    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_superuser(email='auditor@example.com', password='pass12345')

    def test_create_assigns_created_by_from_request_user(self):
        request = self.factory.post('/fake-concrete/', {}, format='json')
        force_authenticate(request, user=self.user)
        response = self.ConcreteModelViewSet.as_view({'post': 'create'})(request)

        self.assertEqual(response.status_code, 201)
        instance = self.ConcreteModel.all_objects.get(pk=response.data['id'])
        self.assertEqual(instance.created_by, self.user)

    def test_create_does_not_assign_updated_by(self):
        request = self.factory.post('/fake-concrete/', {}, format='json')
        force_authenticate(request, user=self.user)
        response = self.ConcreteModelViewSet.as_view({'post': 'create'})(request)

        instance = self.ConcreteModel.all_objects.get(pk=response.data['id'])
        self.assertIsNone(instance.updated_by)

    def test_update_assigns_updated_by_from_request_user(self):
        instance = self.ConcreteModel.objects.create()
        request = self.factory.patch(f'/fake-concrete/{instance.pk}/', {}, format='json')
        force_authenticate(request, user=self.user)
        response = self.ConcreteModelViewSet.as_view({'patch': 'partial_update'})(request, pk=instance.pk)

        self.assertEqual(response.status_code, 200)
        instance.refresh_from_db()
        self.assertEqual(instance.updated_by, self.user)

    def test_update_does_not_change_created_by(self):
        instance = self.ConcreteModel.objects.create()
        instance.set_created_by(self.user)
        instance.save(update_fields=['created_by'])

        other_user = User.objects.create_superuser(email='other-auditor@example.com', password='pass12345')
        request = self.factory.patch(f'/fake-concrete/{instance.pk}/', {}, format='json')
        force_authenticate(request, user=other_user)
        self.ConcreteModelViewSet.as_view({'patch': 'partial_update'})(request, pk=instance.pk)

        instance.refresh_from_db()
        self.assertEqual(instance.created_by, self.user)

    def test_create_uses_authenticated_request_user_not_another_user(self):
        other_user = User.objects.create_superuser(email='other-auditor@example.com', password='pass12345')
        request = self.factory.post('/fake-concrete/', {}, format='json')
        force_authenticate(request, user=self.user)
        response = self.ConcreteModelViewSet.as_view({'post': 'create'})(request)

        instance = self.ConcreteModel.all_objects.get(pk=response.data['id'])
        self.assertNotEqual(instance.created_by, other_user)
        self.assertEqual(instance.created_by, self.user)

    def test_create_persists_created_by_in_a_single_write(self):
        table = self.ConcreteModel._meta.db_table
        request = self.factory.post('/fake-concrete/', {}, format='json')
        force_authenticate(request, user=self.user)

        with CaptureQueriesContext(connection) as ctx:
            response = self.ConcreteModelViewSet.as_view({'post': 'create'})(request)

        self.assertEqual(response.status_code, 201)
        writes = [
            q['sql'] for q in ctx.captured_queries
            if table in q['sql'] and (q['sql'].startswith('INSERT') or q['sql'].startswith('UPDATE'))
        ]
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0].startswith('INSERT'))

    def test_update_persists_updated_by_in_a_single_write(self):
        instance = self.ConcreteModel.objects.create()
        table = self.ConcreteModel._meta.db_table
        request = self.factory.patch(f'/fake-concrete/{instance.pk}/', {}, format='json')
        force_authenticate(request, user=self.user)

        with CaptureQueriesContext(connection) as ctx:
            response = self.ConcreteModelViewSet.as_view({'patch': 'partial_update'})(request, pk=instance.pk)

        self.assertEqual(response.status_code, 200)
        writes = [
            q['sql'] for q in ctx.captured_queries
            if table in q['sql'] and (q['sql'].startswith('INSERT') or q['sql'].startswith('UPDATE'))
        ]
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0].startswith('UPDATE'))


@isolate_apps('core')
class BaseModelViewSetDestroyTests(TestCase):
    """
    Prueba de punta a punta que `BaseModelViewSet.perform_destroy` usa el
    borrado lógico de `BaseModel` (en vez del borrado físico estándar de
    DRF), registrando `request.user` como `deleted_by`, usando el mismo
    modelo concreto y estrategia de autenticación de `BaseModelViewSetAuditTests`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        class DestroyViewSetModel(BaseModel):
            class Meta:
                app_label = 'core'

        cls.ConcreteModel = DestroyViewSetModel
        with connection.schema_editor() as editor:
            editor.create_model(cls.ConcreteModel)

        class ConcreteModelSerializer(serializers.ModelSerializer):
            class Meta:
                model = DestroyViewSetModel
                fields = ['id', 'created_by', 'updated_by']
                read_only_fields = ['created_by', 'updated_by']

        class ConcreteModelViewSet(BaseModelViewSet):
            queryset = DestroyViewSetModel.all_objects.all()
            serializer_class = ConcreteModelSerializer

        cls.ConcreteModelViewSet = ConcreteModelViewSet

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            editor.delete_model(cls.ConcreteModel)
        super().tearDownClass()

    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_superuser(email='destroyer@example.com', password='pass12345')
        self.instance = self.ConcreteModel.objects.create()

    def _destroy(self):
        request = self.factory.delete(f'/fake-concrete/{self.instance.pk}/')
        force_authenticate(request, user=self.user)
        return self.ConcreteModelViewSet.as_view({'delete': 'destroy'})(request, pk=self.instance.pk)

    def test_destroy_returns_expected_drf_status(self):
        response = self._destroy()

        self.assertEqual(response.status_code, 204)

    def test_destroy_sets_is_deleted(self):
        self._destroy()

        self.instance.refresh_from_db()
        self.assertTrue(self.instance.is_deleted)

    def test_destroy_sets_deleted_at(self):
        self._destroy()

        self.instance.refresh_from_db()
        self.assertIsNotNone(self.instance.deleted_at)

    def test_destroy_sets_deleted_by_from_request_user(self):
        self._destroy()

        self.instance.refresh_from_db()
        self.assertEqual(self.instance.deleted_by, self.user)

    def test_destroy_keeps_record_visible_via_all_objects(self):
        self._destroy()

        self.assertTrue(self.ConcreteModel.all_objects.filter(pk=self.instance.pk).exists())

    def test_destroy_hides_record_from_objects(self):
        self._destroy()

        self.assertFalse(self.ConcreteModel.objects.filter(pk=self.instance.pk).exists())

    def test_destroy_does_not_perform_physical_delete(self):
        table = self.ConcreteModel._meta.db_table

        with CaptureQueriesContext(connection) as ctx:
            self._destroy()

        physical_deletes = [
            q['sql'] for q in ctx.captured_queries
            if table in q['sql'] and q['sql'].strip().upper().startswith('DELETE')
        ]
        self.assertEqual(physical_deletes, [])
