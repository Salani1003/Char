from django.db import connection
from django.test import TestCase
from django.test.utils import isolate_apps
from django.utils import timezone

from core.models import BaseModel
from users.models import User


@isolate_apps('core')
class SoftDeleteQuerySetTests(TestCase):
    """
    Prueba `QuerySet.delete(user)` (borrado lógico masivo) contra el mismo
    modelo concreto de prueba usado en `SoftDeleteTests`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        class QuerySetTestModel(BaseModel):
            class Meta:
                app_label = 'core'

        cls.ConcreteModel = QuerySetTestModel
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

        class ManagerTestModel(BaseModel):
            class Meta:
                app_label = 'core'

        cls.ConcreteModel = ManagerTestModel
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
