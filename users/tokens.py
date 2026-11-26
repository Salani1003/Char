from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken


def revoke_user_tokens(user):
    """
    Blacklistea todos los refresh tokens vigentes del usuario. Se usa al
    desactivarlo o cambiarle la contraseña: sin esto, sus refresh tokens
    (días de vida) siguen pudiendo pedir access tokens nuevos.
    """
    BlacklistedToken.objects.bulk_create(
        [
            BlacklistedToken(token=token)
            for token in OutstandingToken.objects.filter(user=user, blacklistedtoken__isnull=True)
        ],
        ignore_conflicts=True,
    )
