from django.db.models.signals import pre_save
from django.dispatch import receiver

from users.models import User
from users.tokens import revoke_user_tokens


@receiver(pre_save, sender=User)
def revoke_tokens_on_sensitive_change(sender, instance, update_fields=None, **kwargs):
    """
    Revoca los refresh tokens cuando el usuario se desactiva o cambia su
    contraseña, sea desde la API, el admin o un shell.
    """
    if instance.pk is None:
        return
    if update_fields is not None and not {'password', 'is_active'} & set(update_fields):
        return  # p. ej. `update_last_login`
    previous = User.objects.filter(pk=instance.pk).values('password', 'is_active').first()
    if previous is None:
        return
    deactivated = previous['is_active'] and not instance.is_active
    password_changed = previous['password'] != instance.password
    if deactivated or password_changed:
        revoke_user_tokens(instance)
