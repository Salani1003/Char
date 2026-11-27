from rest_framework.routers import DefaultRouter

from stock.views import StockCountViewSet, StockMovementViewSet, StockOperationViewSet, StockViewSet

router = DefaultRouter()
router.register('stock', StockViewSet, basename='stock')
router.register('stock-counts', StockCountViewSet, basename='stockcount')
router.register('stock-operations', StockOperationViewSet, basename='stockoperation')
router.register('stock-movements', StockMovementViewSet, basename='stockmovement')

urlpatterns = router.urls
