from django.urls import path

from users.views import DocumentedTokenObtainPairView, DocumentedTokenRefreshView

urlpatterns = [
    path('auth/token/', DocumentedTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', DocumentedTokenRefreshView.as_view(), name='token_refresh'),
]
