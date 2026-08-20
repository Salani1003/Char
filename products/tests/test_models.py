from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from products.models import Categoria
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
