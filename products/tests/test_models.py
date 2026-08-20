from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models
from django.test import TestCase

from products.models import Categoria, Color, Producto
from users.models import User


class CategoriaModelTests(TestCase):
    """
    Prueba el modelo `Categoria`: campos propios (`nombre`), su
    representación en texto y su integración con el soft delete
    heredado de `BaseModel`.
    """

    def test_str_returns_nombre(self):
        categoria = Categoria.objects.create(nombre='Bebidas')

        self.assertEqual(str(categoria), 'Bebidas')

    def test_nombre_max_length_is_100(self):
        field = Categoria._meta.get_field('nombre')

        self.assertEqual(field.max_length, 100)

    def test_nombre_does_not_allow_blank(self):
        categoria = Categoria(nombre='')

        with self.assertRaises(ValidationError):
            categoria.full_clean()

    def test_nombre_is_required_at_db_level(self):
        with self.assertRaises(IntegrityError):
            Categoria.objects.create(nombre=None)

    def test_objects_excludes_soft_deleted_categorias(self):
        categoria = Categoria.objects.create(nombre='Bebidas')
        user = User.objects.create_user(email='deleter@example.com', password='pass12345')

        categoria.delete(user)

        self.assertFalse(Categoria.objects.filter(pk=categoria.pk).exists())
        self.assertTrue(Categoria.all_objects.filter(pk=categoria.pk).exists())


class ColorModelTests(TestCase):
    """
    Prueba el modelo `Color`: campos propios (`nombre`), su
    representación en texto, unicidad y su integración con el
    soft delete heredado de `BaseModel`.
    """

    def test_str_returns_nombre(self):
        color = Color.objects.create(nombre='Rojo')

        self.assertEqual(str(color), 'Rojo')

    def test_nombre_max_length_is_100(self):
        field = Color._meta.get_field('nombre')

        self.assertEqual(field.max_length, 100)

    def test_nombre_does_not_allow_blank(self):
        color = Color(nombre='')

        with self.assertRaises(ValidationError):
            color.full_clean()

    def test_nombre_is_required_at_db_level(self):
        with self.assertRaises(IntegrityError):
            Color.objects.create(nombre=None)

    def test_nombre_is_unique(self):
        Color.objects.create(nombre='Rojo')

        with self.assertRaises(IntegrityError):
            Color.objects.create(nombre='Rojo')

    def test_objects_excludes_soft_deleted_colores(self):
        color = Color.objects.create(nombre='Rojo')
        user = User.objects.create_user(email='deleter@example.com', password='pass12345')

        color.delete(user)

        self.assertFalse(Color.objects.filter(pk=color.pk).exists())
        self.assertTrue(Color.all_objects.filter(pk=color.pk).exists())


class ProductoModelTests(TestCase):
    """
    Prueba el modelo `Producto`: campos propios (`categoria`, `nombre`,
    `descripcion`, `precio_venta`, `precio_costo`), su representación en
    texto, la protección de `categoria` ante borrado y su integración con
    el soft delete heredado de `BaseModel`.
    """

    def setUp(self):
        self.categoria = Categoria.objects.create(nombre='Bebidas')

    def test_str_returns_nombre(self):
        producto = Producto.objects.create(
            categoria=self.categoria,
            nombre='Gaseosa',
            precio_venta=Decimal('100.00'),
            precio_costo=Decimal('50.00'),
        )

        self.assertEqual(str(producto), 'Gaseosa')

    def test_nombre_max_length_is_150(self):
        field = Producto._meta.get_field('nombre')

        self.assertEqual(field.max_length, 150)

    def test_nombre_does_not_allow_blank(self):
        producto = Producto(
            categoria=self.categoria,
            nombre='',
            precio_venta=Decimal('100.00'),
            precio_costo=Decimal('50.00'),
        )

        with self.assertRaises(ValidationError):
            producto.full_clean()

    def test_descripcion_is_optional(self):
        producto = Producto(
            categoria=self.categoria,
            nombre='Gaseosa',
            precio_venta=Decimal('100.00'),
            precio_costo=Decimal('50.00'),
        )

        producto.full_clean()

    def test_categoria_protects_against_deletion(self):
        Producto.objects.create(
            categoria=self.categoria,
            nombre='Gaseosa',
            precio_venta=Decimal('100.00'),
            precio_costo=Decimal('50.00'),
        )

        with self.assertRaises(IntegrityError):
            models.Model.delete(self.categoria)

    def test_objects_excludes_soft_deleted_productos(self):
        producto = Producto.objects.create(
            categoria=self.categoria,
            nombre='Gaseosa',
            precio_venta=Decimal('100.00'),
            precio_costo=Decimal('50.00'),
        )
        user = User.objects.create_user(email='deleter@example.com', password='pass12345')

        producto.delete(user)

        self.assertFalse(Producto.objects.filter(pk=producto.pk).exists())
        self.assertTrue(Producto.all_objects.filter(pk=producto.pk).exists())
