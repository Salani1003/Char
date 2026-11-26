from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Hace obligatorio `Client.email`. Falla si ya existen clientes con email
    NULL: completarlos (o borrarlos) antes de migrar.
    """

    dependencies = [
        ('clients', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='client',
            name='email',
            field=models.EmailField(max_length=254, unique=True),
        ),
    ]
