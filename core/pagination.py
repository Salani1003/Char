from rest_framework.pagination import PageNumberPagination

__all__ = ['DefaultPagination']


class DefaultPagination(PageNumberPagination):
    """
    Paginación por defecto para los viewsets del proyecto. Permite al
    cliente ajustar el tamaño de página con `?page_size=`, con un tope
    para evitar respuestas desmedidas.
    """

    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
