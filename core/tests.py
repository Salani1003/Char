from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext, isolate_apps
from django.utils import timezone
from rest_framework import generics, serializers
from rest_framework.test import APIRequestFactory, force_authenticate

from core.models import BaseModel
from core.permissions import DjangoObjectPermissionsWithView
from core.viewsets import BaseModelViewSet
from users.models import User


class _UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email']


class _UserListCreateView(generics.ListCreateAPIView):
    queryset = User.objects.all()
    serializer_class = _UserSerializer
    permission_classes = [DjangoObjectPermissionsWithView]


class DjangoObjectPermissionsWithViewTests(TestCase):
    """
    Prueba de punta a punta la clase de permiso genérica contra una vista
    genérica de DRF, verificando que el acceso a nivel de endpoint queda
    totalmente gobernado por los Groups/Permissions nativos de Django
    (sin lógica de permisos custom).
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(email='member@example.com', password='pass12345')
        self.content_type = ContentType.objects.get_for_model(User)

    def _grant(self, codename):
        permission = Permission.objects.get(content_type=self.content_type, codename=codename)
        group, _ = Group.objects.get_or_create(name=f'has_{codename}')
        group.permissions.add(permission)
        self.user.groups.add(group)

    def test_read_denied_without_view_permission(self):
        request = self.factory.get('/fake-users/')
        force_authenticate(request, user=self.user)
        response = _UserListCreateView.as_view()(request)
        self.assertEqual(response.status_code, 403)

    def test_read_allowed_with_view_permission_granted_via_group(self):
        self._grant('view_user')
        request = self.factory.get('/fake-users/')
        force_authenticate(request, user=self.user)
        response = _UserListCreateView.as_view()(request)
        self.assertEqual(response.status_code, 200)

    def test_write_denied_without_add_permission(self):
        request = self.factory.post(
            '/fake-users/', {'email': 'new@example.com'}, format='json'
        )
        force_authenticate(request, user=self.user)
        response = _UserListCreateView.as_view()(request)
        self.assertEqual(response.status_code, 403)

    def test_write_allowed_with_add_permission_granted_via_group(self):
        self._grant('add_user')
        request = self.factory.post(
            '/fake-users/', {'email': 'new@example.com'}, format='json'
        )
        force_authenticate(request, user=self.user)
        response = _UserListCreateView.as_view()(request)
        self.assertEqual(response.status_code, 201)

    def test_unauthenticated_request_denied(self):
        request = self.factory.get('/fake-users/')
        response = _UserListCreateView.as_view()(request)
        self.assertEqual(response.status_code, 401)


class SeedRolesCommandTests(TestCase):
    """
    Verifica que `seed_roles` crea Groups y asigna Permissions nativos de
    Django a partir de `core.roles.ROLES`, que es idempotente, y que avisa
    claramente cuando se define un permiso inexistente.
    """

    def _run(self):
        out, err = StringIO(), StringIO()
        call_command('seed_roles', stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_creates_group_and_assigns_defined_permissions(self):
        roles = {'Editors': ['users.view_user', 'users.change_user']}
        with mock.patch('core.management.commands.seed_roles.ROLES', roles):
            self._run()

        group = Group.objects.get(name='Editors')
        codenames = set(group.permissions.values_list('codename', flat=True))
        self.assertEqual(codenames, {'view_user', 'change_user'})

    def test_is_idempotent(self):
        roles = {'Editors': ['users.view_user']}
        with mock.patch('core.management.commands.seed_roles.ROLES', roles):
            self._run()
            self._run()

        self.assertEqual(Group.objects.filter(name='Editors').count(), 1)
        group = Group.objects.get(name='Editors')
        self.assertEqual(group.permissions.count(), 1)

    def test_removes_stale_permissions_on_rerun(self):
        roles = {'Editors': ['users.view_user', 'users.change_user']}
        with mock.patch('core.management.commands.seed_roles.ROLES', roles):
            self._run()

        roles = {'Editors': ['users.view_user']}
        with mock.patch('core.management.commands.seed_roles.ROLES', roles):
            self._run()

        group = Group.objects.get(name='Editors')
        codenames = set(group.permissions.values_list('codename', flat=True))
        self.assertEqual(codenames, {'view_user'})

    def test_warns_on_unknown_permission(self):
        roles = {'Editors': ['users.this_permission_does_not_exist']}
        with mock.patch('core.management.commands.seed_roles.ROLES', roles):
            _, err = self._run()

        self.assertIn('this_permission_does_not_exist', err)
        group = Group.objects.get(name='Editors')
        self.assertEqual(group.permissions.count(), 0)

    def test_warns_on_malformed_permission(self):
        roles = {'Editors': ['not-a-valid-codename']}
        with mock.patch('core.management.commands.seed_roles.ROLES', roles):
            _, err = self._run()

        self.assertIn('not-a-valid-codename', err)


@isolate_apps('core')
class SoftDeleteTests(TestCase):
    """
    Prueba `BaseModel.delete()` (borrado lógico) contra un modelo concreto de prueba,
    creado y destruido en la base de datos de test vía schema_editor, ya
    que `BaseModel` es abstracto y no tiene tabla propia.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        class ConcreteModel(BaseModel):
            class Meta:
                app_label = 'core'

        cls.ConcreteModel = ConcreteModel
        with connection.schema_editor() as editor:
            editor.create_model(cls.ConcreteModel)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            editor.delete_model(cls.ConcreteModel)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(email='deleter@example.com', password='pass12345')
        self.instance = self.ConcreteModel.objects.create()

    def test_delete_sets_flag_timestamp_and_user(self):
        before = timezone.now()
        self.instance.delete(self.user)
        after = timezone.now()

        self.instance.refresh_from_db()
        self.assertTrue(self.instance.is_deleted)
        self.assertIsNotNone(self.instance.deleted_at)
        self.assertTrue(before <= self.instance.deleted_at <= after)
        self.assertEqual(self.instance.deleted_by, self.user)

    def test_delete_persists_only_deletion_fields(self):
        original_created_at = self.instance.created_at
        original_created_by = self.instance.created_by
        original_updated_at = self.instance.updated_at
        original_updated_by = self.instance.updated_by

        self.instance.delete(self.user)

        stored = self.ConcreteModel.all_objects.get(pk=self.instance.pk)
        self.assertTrue(stored.is_deleted)
        self.assertEqual(stored.deleted_by, self.user)
        self.assertEqual(stored.created_at, original_created_at)
        self.assertEqual(stored.created_by, original_created_by)
        self.assertEqual(stored.updated_at, original_updated_at)
        self.assertEqual(stored.updated_by, original_updated_by)

    def test_delete_is_idempotent(self):
        self.instance.delete(self.user)
        self.instance.refresh_from_db()
        first_deleted_at = self.instance.deleted_at

        other_user = User.objects.create_user(email='other@example.com', password='pass12345')
        self.instance.delete(other_user)
        self.instance.refresh_from_db()

        self.assertEqual(self.instance.deleted_at, first_deleted_at)
        self.assertEqual(self.instance.deleted_by, self.user)

    def test_delete_does_not_remove_row_from_database(self):
        self.instance.delete(self.user)

        self.assertTrue(self.ConcreteModel.all_objects.filter(pk=self.instance.pk).exists())


@isolate_apps('core')
class RestoreTests(TestCase):
    """
    Prueba `BaseModel.restore()` contra el mismo modelo concreto de prueba
    usado en `SoftDeleteTests`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        class ConcreteModel(BaseModel):
            class Meta:
                app_label = 'core'

        cls.ConcreteModel = ConcreteModel
        with connection.schema_editor() as editor:
            editor.create_model(cls.ConcreteModel)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            editor.delete_model(cls.ConcreteModel)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(email='deleter@example.com', password='pass12345')
        self.instance = self.ConcreteModel.objects.create()
        self.instance.delete(self.user)
        self.instance.refresh_from_db()

    def test_restore_clears_is_deleted(self):
        self.instance.restore()
        self.instance.refresh_from_db()

        self.assertFalse(self.instance.is_deleted)

    def test_restore_clears_deleted_at(self):
        self.instance.restore()
        self.instance.refresh_from_db()

        self.assertIsNone(self.instance.deleted_at)

    def test_restore_clears_deleted_by(self):
        self.instance.restore()
        self.instance.refresh_from_db()

        self.assertIsNone(self.instance.deleted_by)

    def test_restore_on_active_instance_does_not_modify_values(self):
        active = self.ConcreteModel.objects.create()

        active.restore()
        active.refresh_from_db()

        self.assertFalse(active.is_deleted)
        self.assertIsNone(active.deleted_at)
        self.assertIsNone(active.deleted_by)

    def test_restore_does_not_modify_audit_fields(self):
        original_created_at = self.instance.created_at
        original_created_by = self.instance.created_by
        original_updated_at = self.instance.updated_at
        original_updated_by = self.instance.updated_by

        self.instance.restore()

        stored = self.ConcreteModel.all_objects.get(pk=self.instance.pk)
        self.assertEqual(stored.created_at, original_created_at)
        self.assertEqual(stored.created_by, original_created_by)
        self.assertEqual(stored.updated_at, original_updated_at)
        self.assertEqual(stored.updated_by, original_updated_by)

    def test_restore_makes_instance_visible_via_objects(self):
        self.instance.restore()

        self.assertTrue(self.ConcreteModel.objects.filter(pk=self.instance.pk).exists())

    def test_restore_keeps_instance_in_database_via_all_objects(self):
        self.instance.restore()

        self.assertTrue(self.ConcreteModel.all_objects.filter(pk=self.instance.pk).exists())

    def test_restore_is_idempotent_on_active_instance(self):
        active = self.ConcreteModel.objects.create()

        original_created_at = active.created_at
        original_created_by = active.created_by
        original_updated_at = active.updated_at
        original_updated_by = active.updated_by
        original_is_deleted = active.is_deleted
        original_deleted_at = active.deleted_at
        original_deleted_by = active.deleted_by

        active.restore()
        active.refresh_from_db()

        self.assertEqual(active.created_at, original_created_at)
        self.assertEqual(active.created_by, original_created_by)
        self.assertEqual(active.updated_at, original_updated_at)
        self.assertEqual(active.updated_by, original_updated_by)
        self.assertEqual(active.is_deleted, original_is_deleted)
        self.assertEqual(active.deleted_at, original_deleted_at)
        self.assertEqual(active.deleted_by, original_deleted_by)

    def test_delete_then_restore_full_cycle(self):
        instance = self.ConcreteModel.objects.create()

        instance.delete(self.user)
        instance.refresh_from_db()
        self.assertTrue(instance.is_deleted)

        instance.restore()
        instance.refresh_from_db()

        self.assertFalse(instance.is_deleted)
        self.assertIsNone(instance.deleted_at)
        self.assertIsNone(instance.deleted_by)
        self.assertTrue(self.ConcreteModel.objects.filter(pk=instance.pk).exists())
        self.assertTrue(self.ConcreteModel.all_objects.filter(pk=instance.pk).exists())


@isolate_apps('core')
class AuditAssignmentTests(TestCase):
    """
    Prueba `BaseModel.set_created_by()` y `BaseModel.set_updated_by()` contra
    el mismo modelo concreto de prueba usado en `SoftDeleteTests`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        class ConcreteModel(BaseModel):
            class Meta:
                app_label = 'core'

        cls.ConcreteModel = ConcreteModel
        with connection.schema_editor() as editor:
            editor.create_model(cls.ConcreteModel)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            editor.delete_model(cls.ConcreteModel)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(email='author@example.com', password='pass12345')
        self.instance = self.ConcreteModel.objects.create()

    def test_set_created_by_assigns_created_by(self):
        self.instance.set_created_by(self.user)

        self.assertEqual(self.instance.created_by, self.user)

    def test_set_updated_by_assigns_updated_by(self):
        self.instance.set_updated_by(self.user)

        self.assertEqual(self.instance.updated_by, self.user)

    def test_set_created_by_does_not_save(self):
        self.instance.set_created_by(self.user)

        stored = self.ConcreteModel.all_objects.get(pk=self.instance.pk)
        self.assertIsNone(stored.created_by)

    def test_set_updated_by_does_not_save(self):
        self.instance.set_updated_by(self.user)

        stored = self.ConcreteModel.all_objects.get(pk=self.instance.pk)
        self.assertIsNone(stored.updated_by)

    def test_set_created_by_does_not_modify_other_fields(self):
        original_updated_by = self.instance.updated_by
        original_is_deleted = self.instance.is_deleted
        original_deleted_at = self.instance.deleted_at
        original_deleted_by = self.instance.deleted_by

        self.instance.set_created_by(self.user)

        self.assertEqual(self.instance.updated_by, original_updated_by)
        self.assertEqual(self.instance.is_deleted, original_is_deleted)
        self.assertEqual(self.instance.deleted_at, original_deleted_at)
        self.assertEqual(self.instance.deleted_by, original_deleted_by)

    def test_set_updated_by_does_not_modify_other_fields(self):
        original_created_by = self.instance.created_by
        original_is_deleted = self.instance.is_deleted
        original_deleted_at = self.instance.deleted_at
        original_deleted_by = self.instance.deleted_by

        self.instance.set_updated_by(self.user)

        self.assertEqual(self.instance.created_by, original_created_by)
        self.assertEqual(self.instance.is_deleted, original_is_deleted)
        self.assertEqual(self.instance.deleted_at, original_deleted_at)
        self.assertEqual(self.instance.deleted_by, original_deleted_by)


@isolate_apps('core')
class BaseModelViewSetAuditTests(TestCase):
    """
    Prueba de punta a punta que `BaseModelViewSet` asigna `created_by` al
    crear y `updated_by` al modificar, usando `request.user` a través de
    `set_created_by`/`set_updated_by` del mismo modelo concreto de prueba
    usado en `SoftDeleteTests`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        class ConcreteModel(BaseModel):
            class Meta:
                app_label = 'core'

        cls.ConcreteModel = ConcreteModel
        with connection.schema_editor() as editor:
            editor.create_model(cls.ConcreteModel)

        class ConcreteModelSerializer(serializers.ModelSerializer):
            class Meta:
                model = ConcreteModel
                fields = ['id', 'created_by', 'updated_by']
                read_only_fields = ['created_by', 'updated_by']

        class ConcreteModelViewSet(BaseModelViewSet):
            queryset = ConcreteModel.all_objects.all()
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
class SoftDeleteQuerySetTests(TestCase):
    """
    Prueba `QuerySet.delete(user)` (borrado lógico masivo) contra el mismo
    modelo concreto de prueba usado en `SoftDeleteTests`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        class ConcreteModel(BaseModel):
            class Meta:
                app_label = 'core'

        cls.ConcreteModel = ConcreteModel
        with connection.schema_editor() as editor:
            editor.create_model(cls.ConcreteModel)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            editor.delete_model(cls.ConcreteModel)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(email='deleter@example.com', password='pass12345')
        self.other_user = User.objects.create_user(email='other@example.com', password='pass12345')
        self.instance_a = self.ConcreteModel.objects.create()
        self.instance_b = self.ConcreteModel.objects.create()
        self.excluded = self.ConcreteModel.objects.create()

    def _targeted_queryset(self):
        return self.ConcreteModel.objects.filter(
            pk__in=[self.instance_a.pk, self.instance_b.pk]
        )

    def test_queryset_delete_marks_records_as_deleted(self):
        self._targeted_queryset().delete(self.user)

        self.instance_a.refresh_from_db()
        self.instance_b.refresh_from_db()
        self.assertTrue(self.instance_a.is_deleted)
        self.assertTrue(self.instance_b.is_deleted)

    def test_queryset_delete_sets_deleted_at(self):
        before = timezone.now()
        self._targeted_queryset().delete(self.user)
        after = timezone.now()

        self.instance_a.refresh_from_db()
        self.assertIsNotNone(self.instance_a.deleted_at)
        self.assertTrue(before <= self.instance_a.deleted_at <= after)

    def test_queryset_delete_sets_deleted_by(self):
        self._targeted_queryset().delete(self.user)

        self.instance_a.refresh_from_db()
        self.instance_b.refresh_from_db()
        self.assertEqual(self.instance_a.deleted_by, self.user)
        self.assertEqual(self.instance_b.deleted_by, self.user)

    def test_queryset_delete_does_not_remove_rows_from_database(self):
        self._targeted_queryset().delete(self.user)

        self.assertTrue(self.ConcreteModel.all_objects.filter(pk=self.instance_a.pk).exists())
        self.assertTrue(self.ConcreteModel.all_objects.filter(pk=self.instance_b.pk).exists())

    def test_queryset_delete_does_not_overwrite_already_deleted_deleted_at(self):
        self.instance_a.delete(self.user)
        self.instance_a.refresh_from_db()
        first_deleted_at = self.instance_a.deleted_at

        self._targeted_queryset().delete(self.other_user)
        self.instance_a.refresh_from_db()

        self.assertEqual(self.instance_a.deleted_at, first_deleted_at)

    def test_queryset_delete_does_not_overwrite_already_deleted_deleted_by(self):
        self.instance_a.delete(self.user)

        self._targeted_queryset().delete(self.other_user)
        self.instance_a.refresh_from_db()

        self.assertEqual(self.instance_a.deleted_by, self.user)

    def test_queryset_delete_affects_multiple_records(self):
        updated_count = self._targeted_queryset().delete(self.user)

        self.assertEqual(updated_count, 2)

    def test_queryset_delete_on_mixed_active_and_deleted_records(self):
        self.instance_b.delete(self.user)
        self.instance_b.refresh_from_db()
        original_deleted_at = self.instance_b.deleted_at
        original_deleted_by = self.instance_b.deleted_by

        self._targeted_queryset().delete(self.other_user)

        self.instance_a.refresh_from_db()
        self.instance_b.refresh_from_db()
        self.assertTrue(self.instance_a.is_deleted)
        self.assertEqual(self.instance_a.deleted_by, self.other_user)
        self.assertEqual(self.instance_b.deleted_at, original_deleted_at)
        self.assertEqual(self.instance_b.deleted_by, original_deleted_by)

    def test_queryset_delete_does_not_affect_records_outside_queryset(self):
        self._targeted_queryset().delete(self.user)

        self.excluded.refresh_from_db()
        self.assertFalse(self.excluded.is_deleted)
        self.assertIsNone(self.excluded.deleted_at)
        self.assertIsNone(self.excluded.deleted_by)


@isolate_apps('core')
class SoftDeleteManagerTests(TestCase):
    """
    Prueba que `objects` sólo expone registros activos y que `all_objects`
    expone todos los registros, usando el mismo modelo concreto de prueba
    empleado en `SoftDeleteTests`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        class ConcreteModel(BaseModel):
            class Meta:
                app_label = 'core'

        cls.ConcreteModel = ConcreteModel
        with connection.schema_editor() as editor:
            editor.create_model(cls.ConcreteModel)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            editor.delete_model(cls.ConcreteModel)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(email='deleter@example.com', password='pass12345')
        self.active = self.ConcreteModel.objects.create()
        self.deleted = self.ConcreteModel.objects.create()
        self.deleted.delete(self.user)

    def test_objects_all_returns_only_active_records(self):
        results = list(self.ConcreteModel.objects.all())

        self.assertEqual(results, [self.active])

    def test_objects_filter_never_returns_deleted_records(self):
        results = self.ConcreteModel.objects.filter(pk=self.deleted.pk)

        self.assertFalse(results.exists())

    def test_all_objects_all_returns_active_and_deleted_records(self):
        results = set(self.ConcreteModel.all_objects.all())

        self.assertEqual(results, {self.active, self.deleted})

    def test_all_objects_filter_can_find_deleted_records(self):
        result = self.ConcreteModel.all_objects.filter(pk=self.deleted.pk).first()

        self.assertEqual(result, self.deleted)

    def test_objects_delete_keeps_soft_delete_behavior(self):
        self.ConcreteModel.objects.filter(pk=self.active.pk).delete(self.user)

        self.active.refresh_from_db()
        self.assertTrue(self.active.is_deleted)
        self.assertEqual(self.active.deleted_by, self.user)

    def test_all_objects_delete_keeps_soft_delete_behavior(self):
        self.ConcreteModel.all_objects.filter(pk=self.active.pk).delete(self.user)

        self.active.refresh_from_db()
        self.assertTrue(self.active.is_deleted)
        self.assertEqual(self.active.deleted_by, self.user)

    def test_manager_operations_do_not_perform_physical_delete(self):
        self.ConcreteModel.objects.filter(pk=self.active.pk).delete(self.user)
        self.ConcreteModel.all_objects.filter(pk=self.deleted.pk).delete(self.user)

        self.assertTrue(self.ConcreteModel.all_objects.filter(pk=self.active.pk).exists())
        self.assertTrue(self.ConcreteModel.all_objects.filter(pk=self.deleted.pk).exists())
