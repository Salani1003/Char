from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models
from django.test import TestCase

from products.models import Categoria, Color, Producto, Stock, Variante
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


class VarianteModelTests(TestCase):
    """
    Prueba el modelo `Variante`: campos propios (`producto`, `talle`,
    `color`), su representación en texto, la protección de `producto` y
    `color` ante borrado, la restricción de unicidad y su integración con
    el soft delete heredado de `BaseModel`.
    """

    def setUp(self):
        self.categoria = Categoria.objects.create(nombre='Bebidas')
        self.producto = Producto.objects.create(
            categoria=self.categoria,
            nombre='Remera',
            precio_venta=Decimal('100.00'),
            precio_costo=Decimal('50.00'),
        )
        self.color = Color.objects.create(nombre='Rojo')

    def test_str_returns_producto_talle_color(self):
        variante = Variante.objects.create(
            producto=self.producto, talle=Variante.Talle.M, color=self.color
        )

        self.assertEqual(str(variante), 'Remera - M - Rojo')

    def test_talle_max_length_is_5(self):
        field = Variante._meta.get_field('talle')

        self.assertEqual(field.max_length, 5)

    def test_talle_only_accepts_valid_choices(self):
        variante = Variante(
            producto=self.producto, talle='INVALIDO', color=self.color
        )

        with self.assertRaises(ValidationError):
            variante.full_clean()

    def test_producto_protects_against_deletion(self):
        Variante.objects.create(
            producto=self.producto, talle=Variante.Talle.M, color=self.color
        )

        with self.assertRaises(IntegrityError):
            models.Model.delete(self.producto)

    def test_color_protects_against_deletion(self):
        Variante.objects.create(
            producto=self.producto, talle=Variante.Talle.M, color=self.color
        )

        with self.assertRaises(IntegrityError):
            models.Model.delete(self.color)

    def test_unique_together_producto_talle_color(self):
        Variante.objects.create(
            producto=self.producto, talle=Variante.Talle.M, color=self.color
        )

        with self.assertRaises(IntegrityError):
            Variante.objects.create(
                producto=self.producto, talle=Variante.Talle.M, color=self.color
            )

    def test_id_sequence_starts_at_1000(self):
        variante = Variante.objects.create(
            producto=self.producto, talle=Variante.Talle.M, color=self.color
        )

        self.assertGreaterEqual(variante.id, 1000)

    def test_objects_excludes_soft_deleted_variantes(self):
        variante = Variante.objects.create(
            producto=self.producto, talle=Variante.Talle.M, color=self.color
        )
        user = User.objects.create_user(email='deleter@example.com', password='pass12345')

        variante.delete(user)

        self.assertFalse(Variante.objects.filter(pk=variante.pk).exists())
        self.assertTrue(Variante.all_objects.filter(pk=variante.pk).exists())


class StockModelTests(TestCase):
    """
    Prueba el modelo `Stock`: campos propios (`variante`, `fisica`,
    `reservada`), la propiedad `disponible`, su representación en texto, la
    relación uno a uno con `Variante`, la restricción de que `reservada` no
    supere a `fisica` y su integración con el soft delete heredado de
    `BaseModel`.
    """

    def setUp(self):
        categoria = Categoria.objects.create(nombre='Bebidas')
        producto = Producto.objects.create(
            categoria=categoria,
            nombre='Remera',
            precio_venta=Decimal('100.00'),
            precio_costo=Decimal('50.00'),
        )
        color = Color.objects.create(nombre='Rojo')
        self.variante = Variante.objects.create(
            producto=producto, talle=Variante.Talle.M, color=color
        )

    def test_str_includes_disponible(self):
        stock = Stock.objects.create(variante=self.variante, fisica=10, reservada=3)

        self.assertIn('disponible: 7', str(stock))

    def test_fisica_defaults_to_zero(self):
        stock = Stock.objects.create(variante=self.variante)

        self.assertEqual(stock.fisica, 0)

    def test_reservada_defaults_to_zero(self):
        stock = Stock.objects.create(variante=self.variante)

        self.assertEqual(stock.reservada, 0)

    def test_disponible_returns_fisica_minus_reservada(self):
        stock = Stock.objects.create(variante=self.variante, fisica=10, reservada=4)

        self.assertEqual(stock.disponible, 6)

    def test_reservada_cannot_exceed_fisica(self):
        with self.assertRaises(IntegrityError):
            Stock.objects.create(variante=self.variante, fisica=1, reservada=2)

    def test_fisica_cannot_be_negative(self):
        with self.assertRaises(IntegrityError):
            Stock.objects.create(variante=self.variante, fisica=-1)

    def test_reservada_cannot_be_negative(self):
        with self.assertRaises(IntegrityError):
            Stock.objects.create(variante=self.variante, fisica=10, reservada=-1)

    def test_variante_is_one_to_one(self):
        Stock.objects.create(variante=self.variante, fisica=10, reservada=0)

        with self.assertRaises(IntegrityError):
            Stock.objects.create(variante=self.variante, fisica=5, reservada=0)

    def test_variante_protects_against_deletion(self):
        Stock.objects.create(variante=self.variante, fisica=10, reservada=0)

        with self.assertRaises(IntegrityError):
            models.Model.delete(self.variante)

    def test_objects_excludes_soft_deleted_stocks(self):
        stock = Stock.objects.create(variante=self.variante, fisica=10, reservada=0)
        user = User.objects.create_user(email='deleter@example.com', password='pass12345')

        stock.delete(user)

        self.assertFalse(Stock.objects.filter(pk=stock.pk).exists())
        self.assertTrue(Stock.all_objects.filter(pk=stock.pk).exists())
