from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.db import connection, models
from django.test import RequestFactory, TestCase
from django.test.utils import isolate_apps

from core.admin import BaseAdmin, DeletedFilter
from core.models import BaseModel, unique_when_active
from core.serializers import BaseModelSerializer
from users.models import User


@isolate_apps('core')
class BaseAdminAndUniqueTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        class AdminWidget(BaseModel):
            code = models.CharField(max_length=20)

            class Meta:
                app_label = 'core'
                constraints = [unique_when_active('code', name='adminwidget_code_active')]

            def __str__(self):
                return self.code

        class AdminWidgetSerializer(BaseModelSerializer):
            class Meta:
                model = AdminWidget
                fields = ['id', 'code']

        class StrictWidget(BaseModel):
            slug = models.CharField(max_length=20, unique=True)

            class Meta:
                app_label = 'core'

        class StrictWidgetSerializer(BaseModelSerializer):
            class Meta:
                model = StrictWidget
                fields = ['id', 'slug']

        cls.Model = AdminWidget
        cls.Serializer = AdminWidgetSerializer
        cls.StrictModel = StrictWidget
        cls.StrictSerializer = StrictWidgetSerializer
        with connection.schema_editor() as editor:
            editor.create_model(AdminWidget)
            editor.create_model(StrictWidget)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            editor.delete_model(cls.Model)
            editor.delete_model(cls.StrictModel)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_superuser(email='admin@example.com', password='pass12345')
        self.admin = BaseAdmin(self.Model, AdminSite())
        self.request = RequestFactory().post('/')
        self.request.user = self.user
        self.request.session = {}
        self.request._messages = FallbackStorage(self.request)

    # --- admin
    def test_queryset_includes_deleted(self):
        active = self.Model.objects.create(code='a')
        deleted = self.Model.objects.create(code='b')
        deleted.delete(self.user)
        pks = set(self.admin.get_queryset(self.request).values_list('pk', flat=True))
        self.assertEqual(pks, {active.pk, deleted.pk})

    def test_list_display_gets_is_deleted_column(self):
        self.assertIn('is_deleted', self.admin.get_list_display(self.request))

    def test_deleted_filter(self):
        a = self.Model.objects.create(code='a')
        b = self.Model.objects.create(code='b')
        b.delete(self.user)
        qs = self.admin.get_queryset(self.request)
        for value, expected in (('no', {a.pk}), ('yes', {b.pk})):
            f = DeletedFilter(self.request, {'deleted': [value]}, self.Model, self.admin)
            self.assertEqual(set(f.queryset(self.request, qs).values_list('pk', flat=True)), expected)

    def test_delete_model_is_soft_and_records_user(self):
        obj = self.Model.objects.create(code='a')
        self.admin.delete_model(self.request, obj)
        stored = self.Model.all_objects.get(pk=obj.pk)
        self.assertTrue(stored.is_deleted)
        self.assertEqual(stored.deleted_by, self.user)

    def test_delete_queryset_is_soft_and_records_user(self):
        obj = self.Model.objects.create(code='a')
        self.admin.delete_queryset(self.request, self.Model.objects.filter(pk=obj.pk))
        self.assertEqual(self.Model.all_objects.get(pk=obj.pk).deleted_by, self.user)

    def test_save_model_sets_audit_users(self):
        obj = self.Model(code='a')
        self.admin.save_model(self.request, obj, form=None, change=False)
        self.assertEqual(obj.created_by, self.user)
        self.assertEqual(obj.updated_by, self.user)

    def test_restore_action(self):
        obj = self.Model.objects.create(code='a')
        obj.delete(self.user)
        self.admin.restore_selected(self.request, self.Model.all_objects.filter(pk=obj.pk))
        self.assertFalse(self.Model.all_objects.get(pk=obj.pk).is_deleted)

    def test_restore_action_reports_unique_conflict_and_continues(self):
        old = self.Model.objects.create(code='dup')
        old.delete(self.user)
        self.Model.objects.create(code='dup')  # reutiliza el valor
        free = self.Model.objects.create(code='free')
        free.delete(self.user)

        self.admin.restore_selected(self.request, self.Model.all_objects.filter(pk__in=[old.pk, free.pk]))

        self.assertTrue(self.Model.all_objects.get(pk=old.pk).is_deleted)
        self.assertFalse(self.Model.all_objects.get(pk=free.pk).is_deleted)

    # --- unique_when_active + serializer
    def test_value_of_deleted_record_can_be_reused(self):
        old = self.Model.objects.create(code='x')
        old.delete(self.user)
        serializer = self.Serializer(data={'code': 'x'})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        self.assertEqual(self.Model.objects.filter(code='x').count(), 1)

    def test_duplicate_among_active_is_400_not_integrity_error(self):
        self.Model.objects.create(code='x')
        serializer = self.Serializer(data={'code': 'x'})
        self.assertFalse(serializer.is_valid())
        self.assertIn('code', serializer.errors)

    def test_update_to_own_value_is_valid(self):
        obj = self.Model.objects.create(code='x')
        serializer = self.Serializer(obj, data={'code': 'x'})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_unique_true_value_of_deleted_record_is_400_not_integrity_error(self):
        old = self.StrictModel.objects.create(slug='x')
        old.delete(self.user)
        serializer = self.StrictSerializer(data={'slug': 'x'})
        self.assertFalse(serializer.is_valid())
        self.assertIn('slug', serializer.errors)
