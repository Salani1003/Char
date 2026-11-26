from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from products.models import Brand, Category, Color, ProductModel, Size


class CategoryModelTests(TestCase):
    def test_sibling_names_are_unique_case_insensitive(self):
        parent = Category.objects.create(name='Vestidos')
        Category.objects.create(name='Largos', parent=parent)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Category.objects.create(name='largos', parent=parent)

    def test_same_name_allowed_under_different_parents(self):
        a = Category.objects.create(name='Vestidos')
        b = Category.objects.create(name='Indumentaria')
        Category.objects.create(name='Otros', parent=a)
        Category.objects.create(name='Otros', parent=b)

    def test_root_names_are_unique(self):
        Category.objects.create(name='Vestidos')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Category.objects.create(name='VESTIDOS')

    def test_deleted_name_can_be_reused(self):
        Category.objects.create(name='Vestidos').delete()
        Category.objects.create(name='Vestidos')

    def test_clean_rejects_third_level(self):
        root = Category.objects.create(name='Vestidos')
        child = Category.objects.create(name='Largos', parent=root)
        with self.assertRaises(ValidationError):
            Category(name='Fiesta', parent=child).clean()

    def test_clean_rejects_parent_for_category_with_children(self):
        root = Category.objects.create(name='Vestidos')
        Category.objects.create(name='Largos', parent=root)
        other = Category.objects.create(name='Indumentaria')
        root.parent = other
        with self.assertRaises(ValidationError):
            root.clean()


class CatalogModelTests(TestCase):
    def test_brand_name_unique_case_insensitive(self):
        Brand.objects.create(name='Marca X')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Brand.objects.create(name='marca x')

    def test_model_name_unique_per_brand(self):
        x = Brand.objects.create(name='X')
        y = Brand.objects.create(name='Y')
        ProductModel.objects.create(brand=x, name='Aurora')
        ProductModel.objects.create(brand=y, name='Aurora')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductModel.objects.create(brand=x, name='aurora')

    def test_color_hex_validated(self):
        with self.assertRaises(ValidationError):
            Color(name='Azul', hex='azul').full_clean()
        Color(name='Azul', hex='#1F4E9E').full_clean()
        Color(name='Rojo').full_clean(exclude=['created_by', 'updated_by', 'deleted_by'])

    def test_sizes_ordered_by_order_then_name(self):
        Size.objects.create(name='M', order=3)
        Size.objects.create(name='XS', order=1)
        Size.objects.create(name='S', order=2)
        self.assertEqual([s.name for s in Size.objects.all()], ['XS', 'S', 'M'])
