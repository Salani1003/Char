from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from products.models import Brand, Category, Color, ProductModel, Size
from products.text import fold_text, normalize_name
from users.models import User


class TextHelpersTests(TestCase):
    def test_lowercase_words_are_capitalized_per_word(self):
        self.assertEqual(normalize_name('marca x', 'words'), 'Marca X')
        self.assertEqual(normalize_name('cuchillería ñandú', 'words'), 'Cuchillería Ñandú')

    def test_lowercase_sentence_style_capitalizes_first_letter_only(self):
        self.assertEqual(normalize_name('azul marino'), 'Azul marino')

    def test_existing_capitals_are_respected(self):
        for name in ('NIKE', 'MarketPlace', 'KitchenAid', 'IKEA'):
            self.assertEqual(normalize_name(name, 'words'), name)
            self.assertEqual(normalize_name(name), name)

    def test_apostrophes_not_broken(self):
        self.assertEqual(normalize_name("levi's", 'words'), "Levi's")

    def test_spaces_collapsed_and_trimmed(self):
        self.assertEqual(normalize_name('  marca   x  ', 'words'), 'Marca X')
        self.assertEqual(normalize_name('Marca    X'), 'Marca X')

    def test_upper_style_always_uppercases(self):
        for raw, expected in (('xs', 'XS'), ('Xl', 'XL'), ('  xxl ', 'XXL'), ('xl', 'XL'), ('38', '38'), ('único', 'ÚNICO')):
            self.assertEqual(normalize_name(raw, 'upper'), expected)

    def test_idempotent(self):
        for name in ('nike', 'NIKE', 'Azul marino', 'azul  marino'):
            once = normalize_name(name)
            self.assertEqual(normalize_name(once), once)

    def test_fold_ignores_case_accents_and_spaces(self):
        self.assertEqual(fold_text('  ÑANDÚ   Sur '), fold_text('nandu sur'))
        self.assertEqual(fold_text('MarketPlace'), fold_text('marketplace'))
        self.assertNotEqual(fold_text('Market Place'), fold_text('MarketPlace'))


class ModelNormalizationTests(TestCase):
    def test_save_normalizes_name_on_every_catalog(self):
        self.assertEqual(Brand.objects.create(name='nike').name, 'Nike')
        self.assertEqual(Color.objects.create(name='azul marino').name, 'Azul marino')
        self.assertEqual(Category.objects.create(name='vestidos').name, 'Vestidos')
        brand = Brand.objects.get(name='Nike')
        self.assertEqual(ProductModel.objects.create(brand=brand, name='air max').name, 'Air max')

    def test_slug_is_generated_from_normalized_name(self):
        self.assertEqual(Brand.objects.create(name='  market   place ').slug, 'market-place')

    def test_clean_rejects_case_variants(self):
        Brand.objects.create(name='Nike')
        for name in ('nike', 'NIKE', 'nIkE'):
            with self.assertRaises(ValidationError, msg=name):
                Brand(name=name).clean()

    def test_marketplace_example(self):
        Brand.objects.create(name='MarketPlace')
        for name in ('Marketplace', 'marketplace', 'MARKETPLACE'):
            with self.assertRaises(ValidationError, msg=name):
                Brand(name=name).clean()

    def test_clean_rejects_accent_and_space_variants(self):
        Brand.objects.create(name='Ñandú Sur')
        for name in ('Nandu Sur', 'ñandú   sur', 'NANDÚ SUR'):
            with self.assertRaises(ValidationError, msg=name):
                Brand(name=name).clean()

    def test_clean_message_names_the_existing_record(self):
        Brand.objects.create(name='Nike')
        with self.assertRaises(ValidationError) as ctx:
            Brand(name='nike').clean()
        self.assertEqual(ctx.exception.message_dict, {'name': ['Ya existe la marca «Nike».']})

    def test_clean_allows_own_name_and_case_change(self):
        brand = Brand.objects.create(name='Nike')
        brand.name = 'NIKE'
        brand.clean()  # no choca consigo misma
        brand.save()
        self.assertEqual(Brand.objects.get(pk=brand.pk).name, 'NIKE')

    def test_deleted_name_can_be_reused(self):
        Brand.objects.create(name='Nike').delete()
        Brand(name='nike').clean()

    def test_model_unique_per_brand_only(self):
        x = Brand.objects.create(name='X')
        y = Brand.objects.create(name='Y')
        ProductModel.objects.create(brand=x, name='Aurora')
        ProductModel(brand=y, name='aurora').clean()
        with self.assertRaises(ValidationError):
            ProductModel(brand=x, name='AURORA').clean()

    def test_category_unique_per_parent_only(self):
        a = Category.objects.create(name='Vestidos')
        b = Category.objects.create(name='Indumentaria')
        Category.objects.create(name='Otros', parent=a)
        Category(name='otros', parent=b).clean()
        with self.assertRaises(ValidationError):
            Category(name='OTROS', parent=a).clean()
        with self.assertRaises(ValidationError):
            Category(name='vestidos').clean()  # raíz repetida

    def test_database_is_the_last_line_of_defense_for_case(self):
        Brand.objects.create(name='Nike')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Brand.objects.create(name='NIKE')


class ApiNormalizationTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(User.objects.create_superuser(email='admin@example.com', password='pass12345'))

    def post(self, url, **data):
        return self.api.post(url, data, format='json')

    def test_lowercase_input_is_saved_normalized(self):
        self.assertEqual(self.post('/api/brands/', name='nike').data['name'], 'Nike')
        self.assertEqual(self.post('/api/colors/', name='azul marino').data['name'], 'Azul marino')
        self.assertEqual(self.post('/api/categories/', name='vestidos').data['name'], 'Vestidos')

    def test_variants_of_the_same_name_are_rejected_on_every_catalog(self):
        brand = Brand.objects.create(name='Nike')
        Color.objects.create(name='Azul')
        Category.objects.create(name='Vestidos')
        ProductModel.objects.create(brand=brand, name='Aurora')
        cases = [
            ('/api/brands/', {}, ['nike', 'NIKE', 'Nike ']),
            ('/api/colors/', {}, ['azul', 'AZUL']),
            ('/api/categories/', {}, ['vestidos', 'VESTIDOS']),
            ('/api/product-models/', {'brand': brand.pk}, ['aurora', 'AURORA']),
        ]
        for url, extra, names in cases:
            for name in names:
                response = self.post(url, name=name, **extra)
                self.assertEqual(response.status_code, 400, (url, name))
                self.assertIn('name', response.data)

    def test_marketplace_example_via_api(self):
        self.assertEqual(self.post('/api/brands/', name='MarketPlace').status_code, 201)
        for name in ('Marketplace', 'marketplace'):
            self.assertEqual(self.post('/api/brands/', name=name).status_code, 400, name)

    def test_accent_and_inner_space_variants_rejected(self):
        self.post('/api/brands/', name='Ñandú Sur')
        for name in ('Nandu Sur', 'ñandú    sur'):
            self.assertEqual(self.post('/api/brands/', name=name).status_code, 400, name)

    def test_error_includes_existing_record(self):
        brand = Brand.objects.create(name='Nike')
        response = self.post('/api/brands/', name='NIKE')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['existing']['name'], 'Nike')
        self.assertEqual(str(response.data['existing']['id']), str(brand.pk))
        self.assertIn('Nike', str(response.data['name'][0]))

    def test_rename_to_other_record_rejected_but_case_change_of_own_allowed(self):
        a = Brand.objects.create(name='Nike')
        Brand.objects.create(name='Adidas')
        self.assertEqual(self.api.patch(f'/api/brands/{a.pk}/', {'name': 'adidas'}, format='json').status_code, 400)
        response = self.api.patch(f'/api/brands/{a.pk}/', {'name': 'NIKE'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'NIKE')

    def test_patch_without_name_does_not_trigger_duplicate_check(self):
        a = Brand.objects.create(name='Nike')
        response = self.api.patch(f'/api/brands/{a.pk}/', {'slug': 'nike-nuevo'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

    def test_blank_or_spaces_only_rejected(self):
        self.assertEqual(self.post('/api/brands/', name='   ').status_code, 400)

    def test_changing_model_brand_rechecks_duplicates(self):
        x = Brand.objects.create(name='X')
        y = Brand.objects.create(name='Y')
        ProductModel.objects.create(brand=x, name='Aurora')
        mine = ProductModel.objects.create(brand=y, name='Aurora')
        response = self.api.patch(f'/api/product-models/{mine.pk}/', {'brand': x.pk}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_deleted_brand_name_can_be_reused_with_other_case(self):
        Brand.objects.create(name='Nike').delete()
        self.assertEqual(self.post('/api/brands/', name='nike').status_code, 201)


class AdminNormalizationTests(TestCase):
    """El admin valida con `Model.clean()`, así que aplica las mismas reglas que la API."""

    def form(self, model, data):
        from django.forms import modelform_factory

        return modelform_factory(model, fields=['name'])(data=data)

    def test_admin_form_rejects_variants_of_an_existing_name(self):
        Brand.objects.create(name='Nike')
        for name in ('nike', 'NIKE', 'Níke'):
            form = self.form(Brand, {'name': name})
            self.assertFalse(form.is_valid(), name)
            self.assertIn('name', form.errors)

    def test_admin_form_accepts_new_name_and_normalizes_on_save(self):
        form = self.form(Brand, {'name': 'adidas'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().name, 'Adidas')


class SizeNormalizationTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(User.objects.create_superuser(email='admin@example.com', password='pass12345'))

    def test_save_uppercases(self):
        for raw, expected in (('xs', 'XS'), ('s', 'S'), ('m', 'M'), ('l', 'L'), ('xl', 'XL')):
            self.assertEqual(Size.objects.create(name=raw).name, expected)

    def test_api_stores_uppercase_and_returns_it(self):
        response = self.api.post('/api/sizes/', {'name': 'xl', 'order': 5}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['name'], 'XL')

    def test_numbers_are_kept(self):
        self.assertEqual(self.api.post('/api/sizes/', {'name': '38'}, format='json').data['name'], '38')

    def test_case_variants_rejected_and_existing_returned(self):
        Size.objects.create(name='XL')
        for name in ('xl', 'Xl', ' xl '):
            response = self.api.post('/api/sizes/', {'name': name}, format='json')
            self.assertEqual(response.status_code, 400, name)
            self.assertEqual(response.data['existing']['name'], 'XL')

    def test_patch_name_is_uppercased(self):
        size = Size.objects.create(name='XL')
        response = self.api.patch(f'/api/sizes/{size.pk}/', {'name': 'xxl'}, format='json')
        self.assertEqual(response.data['name'], 'XXL')

    def test_admin_form_uppercases_and_rejects_duplicates(self):
        from django.forms import modelform_factory

        form_class = modelform_factory(Size, fields=['name', 'order'])
        form = form_class(data={'name': 'xs', 'order': 1})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().name, 'XS')
        self.assertFalse(form_class(data={'name': 'Xs', 'order': 2}).is_valid())
