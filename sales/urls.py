from rest_framework.routers import DefaultRouter

from sales.views import ExchangeViewSet, SaleViewSet

router = DefaultRouter()
router.register('sales', SaleViewSet, basename='sale')
router.register('exchanges', ExchangeViewSet, basename='exchange')

urlpatterns = router.urls
