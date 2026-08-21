from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.throttling import SimpleRateThrottle

from users.models import User
from users.views import (
    DocumentedTokenBlacklistView,
    DocumentedTokenObtainPairView,
    DocumentedTokenRefreshView,
    UserViewSet,
)


class UserViewSetTests(TestCase):
    """
    `User` no hereda de `core.models.BaseModel` (no tiene created_by/
    updated_by ni soft delete), así que `UserViewSet` sobreescribe
    perform_create/perform_update/perform_destroy en vez de heredar el
    comportamiento de `BaseModelViewSet`. Estos tests cubren esa
    diferencia de comportamiento.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = User.objects.create_superuser(email='admin@example.com', password='pass12345')

    def _valid_payload(self, **overrides):
        data = {
            'email': 'new-user@example.com',
            'password': 'pass12345',
            'first_name': 'Ada',
            'last_name': 'Lovelace',
        }
        data.update(overrides)
        return data

    def _list(self, query_string=''):
        request = self.factory.get('/users/' + query_string)
        force_authenticate(request, user=self.admin)
        return UserViewSet.as_view({'get': 'list'})(request)

    def _create(self, payload):
        request = self.factory.post('/users/', payload, format='json')
        force_authenticate(request, user=self.admin)
        return UserViewSet.as_view({'post': 'create'})(request)

    def _update(self, pk, payload):
        request = self.factory.patch(f'/users/{pk}/', payload, format='json')
        force_authenticate(request, user=self.admin)
        return UserViewSet.as_view({'patch': 'partial_update'})(request, pk=pk)

    def _destroy(self, pk):
        request = self.factory.delete(f'/users/{pk}/')
        force_authenticate(request, user=self.admin)
        return UserViewSet.as_view({'delete': 'destroy'})(request, pk=pk)

    def test_create_creates_user(self):
        response = self._create(self._valid_payload())

        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(email='new-user@example.com').exists())

    def test_create_does_not_crash_on_created_by(self):
        """
        Regresión: `BaseModelViewSet.perform_create` original llamaba a
        `serializer.save(created_by=request.user)`, pero `User` no tiene
        ese campo, así que el registro de usuarios tiraba un 500.
        """
        response = self._create(self._valid_payload())
        self.assertEqual(response.status_code, 201)

    def test_update_updates_user(self):
        user = User.objects.create_user(email='member@example.com', password='pass12345')

        response = self._update(user.pk, {'first_name': 'Grace'})

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.first_name, 'Grace')

    def test_destroy_deactivates_user_instead_of_deleting(self):
        user = User.objects.create_user(email='member@example.com', password='pass12345')

        response = self._destroy(user.pk)

        self.assertEqual(response.status_code, 204)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_destroy_does_not_physically_delete(self):
        user = User.objects.create_user(email='member@example.com', password='pass12345')

        self._destroy(user.pk)

        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    def test_list_can_filter_by_is_active_false(self):
        inactive = User.objects.create_user(email='inactive@example.com', password='pass12345')
        inactive.is_active = False
        inactive.save(update_fields=['is_active'])
        User.objects.create_user(email='active@example.com', password='pass12345')

        response = self._list('?is_active=false')

        self.assertEqual(response.status_code, 200)
        emails = {row['email'] for row in response.data}
        self.assertEqual(emails, {inactive.email})

    def test_list_can_filter_by_is_active_true(self):
        inactive = User.objects.create_user(email='inactive@example.com', password='pass12345')
        inactive.is_active = False
        inactive.save(update_fields=['is_active'])
        active = User.objects.create_user(email='active@example.com', password='pass12345')

        response = self._list('?is_active=true')

        self.assertEqual(response.status_code, 200)
        emails = {row['email'] for row in response.data}
        self.assertIn(active.email, emails)
        self.assertNotIn(inactive.email, emails)

    def test_list_without_filter_returns_all_users(self):
        inactive = User.objects.create_user(email='inactive@example.com', password='pass12345')
        inactive.is_active = False
        inactive.save(update_fields=['is_active'])

        response = self._list()

        self.assertEqual(response.status_code, 200)
        emails = {row['email'] for row in response.data}
        self.assertIn(inactive.email, emails)
        self.assertIn(self.admin.email, emails)


class TokenObtainThrottleTests(TestCase):
    """
    `/api/auth/token/` es el blanco directo de fuerza bruta de contraseñas:
    verifica que el `throttle_scope = 'login'` de `DocumentedTokenObtainPairView`
    corte los intentos en vez de dejarlos pasar sin límite.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        cache.clear()
        self.addCleanup(cache.clear)

    def _obtain_token(self):
        request = self.factory.post(
            '/auth/token/', {'email': 'nadie@example.com', 'password': 'mala'}, format='json'
        )
        return DocumentedTokenObtainPairView.as_view()(request)

    def test_exceeding_login_rate_returns_429(self):
        # `SimpleRateThrottle.THROTTLE_RATES` se fija como atributo de clase
        # al importar `rest_framework.throttling` (lee `DEFAULT_THROTTLE_RATES`
        # una sola vez), así que `override_settings` no lo actualiza en
        # caliente. Se parchea el dict compartido directamente para acotar
        # el rate a 2/min sin depender de repetir 11 requests reales.
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {'login': '2/min'}):
            self._obtain_token()
            self._obtain_token()

            response = self._obtain_token()

        self.assertEqual(response.status_code, 429)


class TokenBlacklistTests(TestCase):
    """
    Cubre el logout real: rotación de refresh tokens (SIMPLE_JWT) + blacklist.
    Sin esto, un `refresh` seguía siendo válido hasta expirar aunque el
    cliente lo descartara.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(email='member@example.com', password='pass12345')

    def _obtain_token(self):
        request = self.factory.post(
            '/auth/token/', {'email': 'member@example.com', 'password': 'pass12345'}, format='json'
        )
        return DocumentedTokenObtainPairView.as_view()(request)

    def _refresh(self, refresh_token):
        request = self.factory.post('/auth/token/refresh/', {'refresh': refresh_token}, format='json')
        return DocumentedTokenRefreshView.as_view()(request)

    def _blacklist(self, refresh_token):
        request = self.factory.post('/auth/logout/', {'refresh': refresh_token}, format='json')
        return DocumentedTokenBlacklistView.as_view()(request)

    def test_refresh_rotates_and_blacklists_the_used_token(self):
        refresh = self._obtain_token().data['refresh']

        first_refresh = self._refresh(refresh)
        self.assertEqual(first_refresh.status_code, 200)
        self.assertIn('refresh', first_refresh.data)
        self.assertNotEqual(first_refresh.data['refresh'], refresh)

        # El refresh ya usado (rotado) quedó en la blacklist: reusarlo falla.
        reused = self._refresh(refresh)
        self.assertEqual(reused.status_code, 401)

    def test_logout_blacklists_refresh_token(self):
        refresh = self._obtain_token().data['refresh']

        logout_response = self._blacklist(refresh)
        self.assertEqual(logout_response.status_code, 200)

        refresh_after_logout = self._refresh(refresh)
        self.assertEqual(refresh_after_logout.status_code, 401)

    def test_logout_with_already_blacklisted_token_returns_401(self):
        refresh = self._obtain_token().data['refresh']
        self._blacklist(refresh)

        response = self._blacklist(refresh)

        self.assertEqual(response.status_code, 401)
