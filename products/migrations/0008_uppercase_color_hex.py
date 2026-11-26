from django.db import migrations


def uppercase_hex(apps, schema_editor):
    """Pasa a mayúsculas el tono de los colores ya cargados (`#14284b` -> `#14284B`)."""
    Color = apps.get_model('products', 'Color')
    for color in Color.objects.exclude(hex='').order_by('pk'):
        upper = color.hex.strip().upper()
        if upper != color.hex:
            Color.objects.filter(pk=color.pk).update(hex=upper)


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0007_uppercase_size_names'),
    ]

    operations = [
        migrations.RunPython(uppercase_hex, migrations.RunPython.noop),
    ]
