from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower

from users.managers import UserManager


class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta(AbstractUser.Meta):
        constraints = [
            # `unique=True` es case-sensitive: sin esto `A@x.com` y `a@x.com`
            # serían dos usuarios distintos.
            models.UniqueConstraint(Lower('email'), name='users_user_email_ci_unique'),
        ]

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email
