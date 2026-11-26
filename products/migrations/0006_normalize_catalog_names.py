from django.db import IntegrityError, migrations, transaction

from products.text import STYLE_SENTENCE, STYLE_WORDS, normalize_name

# Modelo -> estilo de capitalización (ver `products.text.normalize_name`).
_STYLES = {'Brand': STYLE_WORDS, 'Category': STYLE_SENTENCE, 'ProductModel': STYLE_SENTENCE, 'Color': STYLE_SENTENCE}


def normalize_existing_names(apps, schema_editor):
    """
    Aplica a los registros ya cargados la misma normalización que ahora hace
    `save()` (todo en minúsculas -> capitalizado; espacios colapsados). Si
    normalizar un nombre chocara con otro registro (ej. "Marca  X" y "Marca X"
    ya existían por separado), ese registro se deja como está: unificar
    duplicados es una decisión de negocio, no de una migración.
    """
    for model_name, style in _STYLES.items():
        model = apps.get_model('products', model_name)
        for obj in model.objects.order_by('pk'):
            name = normalize_name(obj.name, style)
            if name == obj.name:
                continue
            try:
                with transaction.atomic():
                    model.objects.filter(pk=obj.pk).update(name=name)
            except IntegrityError:
                continue


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0005_slugs_and_publish'),
    ]

    operations = [
        migrations.RunPython(normalize_existing_names, migrations.RunPython.noop),
    ]
