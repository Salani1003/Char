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
    email = models.EmailField(null=True, blank=True, unique=True)
    origin = models.CharField(max_length=20, choices=Origin.choices)
