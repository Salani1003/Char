from django.db.models import F
from rest_framework.filters import OrderingFilter

__all__ = ['NullsLastOrderingFilter']


class NullsLastOrderingFilter(OrderingFilter):
    """
    `OrderingFilter` que manda los valores nulos al final tanto en orden ascendente como
    descendente. En PostgreSQL un `DESC` pone los nulos primero, y en un listado ordenado por un
    campo que no aplica a todas las filas (ej. el stock, que los productos digitales no tienen)
    eso dejaría las filas "sin dato" arriba de todo.

    Agrega `-pk` como desempate final para que la paginación sea determinista.
    """

    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)
        if not ordering:
            return queryset
        terms = [
            F(term[1:]).desc(nulls_last=True) if term.startswith('-') else F(term).asc(nulls_last=True)
            for term in ordering
        ]
        return queryset.order_by(*terms, '-pk')
