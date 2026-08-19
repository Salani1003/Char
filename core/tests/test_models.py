from django.db import connection
from django.test import TestCase
from django.test.utils import isolate_apps
from django.utils import timezone

from core.models import BaseModel
from users.models import User


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

        class SoftDeleteTestModel(BaseModel):
            class Meta:
                app_label = 'core'

        cls.ConcreteModel = SoftDeleteTestModel
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

        class RestoreTestModel(BaseModel):
            class Meta:
                app_label = 'core'

        cls.ConcreteModel = RestoreTestModel
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

        class AuditAssignmentTestModel(BaseModel):
            class Meta:
                app_label = 'core'

        cls.ConcreteModel = AuditAssignmentTestModel
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
