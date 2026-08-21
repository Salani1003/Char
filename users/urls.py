from django.urls import include, path
from rest_framework.routers import DefaultRouter

from users.views import (
    DocumentedTokenBlacklistView,
    DocumentedTokenObtainPairView,
    DocumentedTokenRefreshView,
    GroupViewSet,
    UserViewSet,
)

router = DefaultRouter()
router.register('users', UserViewSet, basename='user')
router.register('groups', GroupViewSet, basename='group')

urlpatterns = [
    path('auth/token/', DocumentedTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', DocumentedTokenRefreshView.as_view(), name='token_refresh'),
    path('auth/logout/', DocumentedTokenBlacklistView.as_view(), name='token_blacklist'),
    path('', include(router.urls)),
]
