from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from users.schemas import TOKEN_OBTAIN_SCHEMA, TOKEN_REFRESH_SCHEMA


@TOKEN_OBTAIN_SCHEMA
class DocumentedTokenObtainPairView(TokenObtainPairView):
    pass


@TOKEN_REFRESH_SCHEMA
class DocumentedTokenRefreshView(TokenRefreshView):
    pass
