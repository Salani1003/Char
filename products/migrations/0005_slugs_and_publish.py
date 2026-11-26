from django.db import migrations, models
from django.utils.text import slugify


# Modelo -> largo máximo del slug.
_MODELS = {'Brand': 140, 'Category': 140, 'Product': 220}


def fill_slugs(apps, schema_editor):
    """
    Completa el slug de las filas existentes (incluidas las eliminadas) desde su
    nombre, numerando las repetidas (`x`, `x-2`, `x-3`...). El manager histórico
    no filtra eliminados, así que el resultado es único sobre toda la tabla.
    """
    for model_name, limit in _MODELS.items():
        model = apps.get_model('products', model_name)
        used = set()
        for obj in model.objects.order_by('pk'):
            base = slugify(obj.name)[: limit - 6].strip('-') or 'item'
            slug, n = base, 1
            while slug in used:
                n += 1
                slug = f'{base}-{n}'
            used.add(slug)
            model.objects.filter(pk=obj.pk).update(slug=slug)


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0004_sku_counter'),
    ]

    operations = [
        migrations.AddField('brand', 'slug', models.SlugField(max_length=140, null=True)),
        migrations.AddField('category', 'slug', models.SlugField(max_length=140, null=True)),
        migrations.AddField('product', 'slug', models.SlugField(max_length=220, null=True)),
        migrations.AddField(
            'product',
            'is_published',
            models.BooleanField(db_index=True, default=False, verbose_name='publicado'),
        ),
        migrations.RunPython(fill_slugs, migrations.RunPython.noop),
        migrations.AlterField('brand', 'slug', models.SlugField(max_length=140)),
        migrations.AlterField('category', 'slug', models.SlugField(max_length=140)),
        migrations.AlterField('product', 'slug', models.SlugField(max_length=220)),
        migrations.AddConstraint(
            'brand',
            models.UniqueConstraint(
                fields=('slug',), condition=models.Q(is_deleted=False), name='brand_slug_active_unique'
            ),
        ),
        migrations.AddConstraint(
            'category',
            models.UniqueConstraint(
                fields=('slug',), condition=models.Q(is_deleted=False), name='category_slug_active_unique'
            ),
        ),
        migrations.AddConstraint(
            'product',
            models.UniqueConstraint(
                fields=('slug',), condition=models.Q(is_deleted=False), name='product_slug_active_unique'
            ),
        ),
    ]
