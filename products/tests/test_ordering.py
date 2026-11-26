from django.test import TestCase
from rest_framework.test import APIClient

from products.models import Brand, Category, Color, ProductModel
from users.models import User

# Mezcla mayúsculas/minúsculas y tildes a propósito: el orden esperado es el
# alfabético del español (sin palabras con "n" que dependan de si la ñ se
# ordena como letra aparte: con el collation `en_US` se ordena junto a la n). Si la base usara un collation sin reglas lingüísticas
# (ej. `C`), "Árbol" y "Ñandú" caerían al final y este test lo detecta.
NAMES = ['zeta', 'Árbol', 'banana', 'Ñandú', 'Alfa', 'mesa']
# Los nombres todo en minúsculas se guardan capitalizados (ver products.text).
EXPECTED = ['Alfa', 'Árbol', 'Banana', 'Mesa', 'Ñandú', 'Zeta']


class AlphabeticalOrderingTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(User.objects.create_superuser(email='admin@example.com', password='pass12345'))

    def names(self, url, **params):
        response = self.api.get(url, {'page_size': 100, **params})
        self.assertEqual(response.status_code, 200)
        return [r['name'] for r in response.data['results']]

    def test_brands_alphabetical_ignoring_case_and_accents(self):
        for name in NAMES:
            Brand.objects.create(name=name)
        self.assertEqual(self.names('/api/brands/'), EXPECTED)

    def test_colors_alphabetical(self):
        for name in NAMES:
            Color.objects.create(name=name)
        self.assertEqual(self.names('/api/colors/'), EXPECTED)

    def test_models_alphabetical_within_brand(self):
        brand = Brand.objects.create(name='X')
        for name in NAMES:
            ProductModel.objects.create(brand=brand, name=name)
        self.assertEqual(self.names('/api/product-models/', brand=brand.pk), EXPECTED)

    def test_models_grouped_by_brand_alphabetically(self):
        b = Brand.objects.create(name='beta')
        a = Brand.objects.create(name='Alfa')
        ProductModel.objects.create(brand=b, name='Uno')
        ProductModel.objects.create(brand=a, name='zzz')
        ProductModel.objects.create(brand=a, name='Aaa')
        self.assertEqual(self.names('/api/product-models/'), ['Aaa', 'Zzz', 'Uno'])

    def test_categories_grouped_by_parent_then_alphabetical(self):
        vestidos = Category.objects.create(name='vestidos')
        indumentaria = Category.objects.create(name='Indumentaria')
        for name in ('Largos', 'cortos'):
            Category.objects.create(name=name, parent=vestidos)
        for name in ('Sweaters', 'blusas', 'Blazers'):
            Category.objects.create(name=name, parent=indumentaria)
        self.assertEqual(
            self.names('/api/categories/'),
            ['Indumentaria', 'Blazers', 'Blusas', 'Sweaters', 'Vestidos', 'Cortos', 'Largos'],
        )

    def test_categories_search_keeps_alphabetical_order(self):
        root = Category.objects.create(name='Vestidos')
        for name in ('Largos', 'Largos fiesta', 'Cortos largos'):
            Category.objects.create(name=name, parent=root)
        self.assertEqual(
            self.names('/api/categories/', search='largos'),
            ['Cortos largos', 'Largos', 'Largos fiesta'],
        )

    def test_explicit_ordering_param_still_works(self):
        for name in ('b', 'a', 'c'):
            Brand.objects.create(name=name)
        self.assertEqual(self.names('/api/brands/', ordering='-name'), ['C', 'B', 'A'])

    def test_restore_works_with_annotated_ordering(self):
        for model, kwargs in ((Brand, {}), (Color, {})):
            obj = model.objects.create(name='X', **kwargs)
            obj.delete()
            url = '/api/brands/' if model is Brand else '/api/colors/'
            self.assertEqual(self.api.post(f'{url}{obj.pk}/restore/').status_code, 200)
