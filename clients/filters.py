import django_filters

from clients.models import Client

__all__ = ['ClientFilter']


class ClientFilter(django_filters.FilterSet):
    """
    Filtros del listado de clientes:

      * `origin`: uno o varios orígenes (`?origin=instagram&origin=google`).
      * `created_from` / `created_to`: rango de fecha de alta, ambos
        inclusivos, en formato `YYYY-MM-DD`.
    """

    origin = django_filters.MultipleChoiceFilter(choices=Client.Origin.choices)
    created_from = django_filters.DateFilter(field_name='created_at', lookup_expr='date__gte')
    created_to = django_filters.DateFilter(field_name='created_at', lookup_expr='date__lte')

    class Meta:
        model = Client
        fields = ['origin', 'created_from', 'created_to']
