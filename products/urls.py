from rest_framework.routers import DefaultRouter

from products.views import BrandViewSet, CategoryViewSet, ColorViewSet, ProductImageViewSet, ProductModelViewSet, ProductVariantViewSet, ProductViewSet, SizeViewSet

router = DefaultRouter()
router.register('categories', CategoryViewSet, basename='category')
router.register('brands', BrandViewSet, basename='brand')
router.register('product-models', ProductModelViewSet, basename='productmodel')
router.register('products', ProductViewSet, basename='product')
router.register('product-variants', ProductVariantViewSet, basename='productvariant')
router.register('product-images', ProductImageViewSet, basename='productimage')
router.register('colors', ColorViewSet, basename='color')
router.register('sizes', SizeViewSet, basename='size')

urlpatterns = router.urls
