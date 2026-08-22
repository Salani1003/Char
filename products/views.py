from core.viewsets import BaseModelViewSet
from products.models import Categoria
from products.schemas import CATEGORIA_VIEWSET_SCHEMA
from products.serializers import CategoriaSerializer


@CATEGORIA_VIEWSET_SCHEMA
class CategoriaViewSet(BaseModelViewSet):
    queryset = Categoria.objects.all().order_by('nombre')
    serializer_class = CategoriaSerializer
