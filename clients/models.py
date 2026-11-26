from django.db import models

from core.models import BaseModel


class Client(BaseModel):
    class Origin(models.TextChoices):
        INSTAGRAM = 'instagram', 'Instagram'
        FACEBOOK = 'facebook', 'Facebook'
        TIKTOK = 'tiktok', 'TikTok'
        REFERRAL = 'referral', 'Recomendación'
        PHYSICAL_STORE = 'physical_store', 'Local físico'
        GOOGLE = 'google', 'Google'
        OTHER = 'other', 'Otro'

    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, null=True, blank=True)
    email = models.EmailField(unique=True)
    origin = models.CharField(max_length=20, choices=Origin.choices)

    def save(self, *args, **kwargs):
        # Email siempre en minúsculas: `unique=True` distingue mayúsculas y
        # `A@x.com`/`a@x.com` serían dos clientes distintos.
        self.email = self.email.strip().lower()
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'email' not in update_fields:
            kwargs['update_fields'] = [*update_fields, 'email']
        super().save(*args, **kwargs)
