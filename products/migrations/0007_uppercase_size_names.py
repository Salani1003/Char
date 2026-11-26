from django.db import IntegrityError, migrations, transaction

from products.text import STYLE_UPPER, normalize_name


def uppercase_existing_sizes(apps, schema_editor):
    """
    Pasa a mayúsculas los talles ya cargados ("xl" -> "XL"), como hace ahora
    `Size.save()`. Si dos talles se volvieran iguales (ej. "XL" y "XL " con
    espacios distintos) el segundo se deja como está: unificar duplicados es
    una decisión de negocio.
    """
    Size = apps.get_model('products', 'Size')
    for size in Size.objects.order_by('pk'):
        name = normalize_name(size.name, STYLE_UPPER)
        if name == size.name:
            continue
        try:
            with transaction.atomic():
                Size.objects.filter(pk=size.pk).update(name=name)
        except IntegrityError:
            continue


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0006_normalize_catalog_names'),
    ]

    operations = [
        migrations.RunPython(uppercase_existing_sizes, migrations.RunPython.noop),
    ]
