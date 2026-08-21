# TODO — pendientes de la auditoría de seguridad/calidad

Este archivo junta los hallazgos de una auditoría del backend que quedaron
pendientes. Los críticos ya se resolvieron (ver [Ya resuelto](#ya-resuelto)
al final); lo que sigue son items abiertos, ordenados por importancia.

## Escalada de privilegios vía `groups`

**El problema.** `UserSerializer.groups` (`users/serializers.py:26`) es
escribible sin ninguna restricción:

```python
groups = serializers.PrimaryKeyRelatedField(many=True, queryset=Group.objects.all(), required=False)
```

`is_staff`/`is_superuser` sí están protegidos (`read_only_fields`,
`users/serializers.py:43`), pero eso no alcanza: los permisos *funcionales* de
Char viven en los Groups (ver `core/roles.py`), no en esos flags técnicos. El
grupo es el vector real — cualquier usuario con `users.change_user` puede
mandar `PATCH /api/users/{id}/ {"groups": [<id de Administrator>]}` y
asignarse (o asignarle a otro) cualquier rol, sin que nada lo frene.

**Severidad honesta: latente, no explotable hoy.** El único rol definido con
`users.change_user` es `Administrator` (`core/roles.py:34-44`), y ese rol ya
tiene `add`/`view`/`change`/`delete` sobre `User` — o sea, el techo actual es
"un Administrator se reasigna a sí mismo Administrator", que no suma nada. El
problema se activa el día que aparezca un rol intermedio con `change_user`
pero menos permisos que `Administrator` (un "Supervisor", un "RRHH"): ese rol
podría auto-promoverse a `Administrator` con un solo `PATCH`. Es una bomba de
tiempo estructural, no un incendio activo — pero conviene cerrarla antes de
agregar ese próximo rol, no después.

**Opciones para cerrarlo** (elegir una; quedan documentadas para no tener que
rediscutir el espacio de soluciones):

1. **Subconjunto de permisos (recomendada).** Un usuario sólo puede asignar
   grupos cuyos permisos él mismo ya posee. Es el invariante clásico
   anti-escalada: nadie puede otorgar lo que no tiene. No genera cuello de
   botella operativo y escala solo a medida que se agreguen roles nuevos. Los
   superusers quedan exentos de la regla (ya pueden todo).

   ```
   Administrator (todos los permisos de users + clients)
     → puede asignar: Administrator, Vendedor         ✓

   Supervisor (change_user + view_client, ejemplo futuro)
     → puede asignar sólo grupos con permisos ⊆ los suyos
     → NO puede asignar Administrator                  ✗ (400)
   ```

2. **Sólo superuser toca `groups`.** `groups` pasa a ser de sólo lectura salvo
   que quien hace el request sea `is_superuser`. Máxima simplicidad y
   seguridad, pero cada alta o cambio de rol pasa a depender de un superuser —
   cuello de botella si se piensa delegar la administración de usuarios.

3. **Permiso dedicado `users.assign_groups` + subconjunto.** Se agrega un
   permiso custom (no ligado 1:1 a un método HTTP) que separa "editar un
   usuario" de "asignarle roles", combinado con la regla de subconjunto de la
   opción 1. Más preciso, pero suma un permiso no nativo al modelo, apartándose
   un poco de la filosofía "roles = Groups nativos de Django" del resto del
   repo (ver `core/roles.py`, docstring).

**Decisión secundaria: auto-edición.** Independientemente de la opción de
arriba, definir si un usuario puede modificarse a sí mismo `groups` e
`is_active` vía la API. Recomendado bloquear ambos en el propio usuario: cierra
la auto-promoción aunque la regla principal tuviera un agujero, y evita que
alguien se autobloquee (`is_active=false` a sí mismo) por accidente.

**Dónde tocar:**
- `validate_groups` (nuevo) en `users/serializers.py`, para meter la regla
  elegida — mismo patrón que ya usa `validate_password` en el mismo archivo.
- Tests en `users/tests/test_permissions.py`: ya tiene el helper `_grant()`
  (línea 23) para armar usuarios con permisos puntuales vía Groups/Permissions
  reales; reutilizarlo para el caso "usuario con `change_user` pero sin los
  permisos del grupo que intenta asignar".

## Resto de pendientes

- **Paginación global ausente.** `DEFAULT_PAGINATION_CLASS` no está en
  `REST_FRAMEWORK` (`config/settings.py`). `GET /api/clients/` y
  `GET /api/users/` devuelven la tabla completa en un solo response. Al
  agregarla, ajustar los tests de listado que hoy asumen una lista plana
  (`clients/tests/test_views.py`, `users/tests/test_views.py`).

- **App `products` a medio hacer.** Existen modelos + admin + tests de modelo,
  pero:
  - `products/views.py` sigue siendo el stub de `startapp`.
  - No hay `serializers.py`, `urls.py` ni `schemas.py`; la app no está en
    `config/urls.py`, así que no es alcanzable por la API.
  - `core/roles.py` no define ningún permiso `products.*`, ni siquiera para
    `Administrator`.
  - `Color` (`products/models.py`) es un modelo huérfano: nada lo referencia
    (ni FK ni M2M).
  - Nomenclatura en español (`Categoria`, `precio_venta`) contra el inglés del
    resto del repo (`Client`, `first_name`) — conviene unificar antes de que
    crezca más.
  - `products/admin.py` no sobreescribe `get_queryset` con `all_objects`
    (al revés de `clients/admin.py:14`), así que los registros soft-deleted
    desaparecen del admin sin forma de restaurarlos desde ahí.

- **`LOGGING` ausente.** No hay bloque `LOGGING` en `config/settings.py`. En
  producción, con `DEBUG=False`, los errores no quedan trazados salvo lo que
  gunicorn tire por stdout.

- **`delete()` con firma incompatible con Django.** `BaseModel.delete(self, user)`
  (`core/models.py:59`) y `SoftDeleteQuerySet.delete(self, user)`
  (`core/querysets.py:6`) rompen la firma esperada por Django
  (`delete(using=None, keep_parents=False)` / `delete()` sin argumentos). El
  "Delete selected" del admin y cualquier cascada interna de Django que llame
  `.delete()` sin argumentos revientan con `TypeError`. Fix: `user=None` por
  default en ambas.

- **`has_object_permission` neutralizado.** El fallback
  `if not (user.has_perms(perms, obj) or user.has_perms(perms))` en
  `core/permissions.py:68` hace que el chequeo a nivel de objeto nunca sea
  determinante: el permiso a nivel de modelo siempre alcanza, incluso si el día
  de mañana se agrega `django-guardian` u otro backend de permisos por objeto.
  Revisar si es el comportamiento buscado (documentado como intencional en el
  docstring de la clase) o si conviene que un backend de permisos por objeto sí
  pueda restringir más allá del permiso de modelo.

- **Higiene general:**
  - Sin linter/formatter ni CI configurados.
  - `CLAUDE.md` dice que sólo `SECRET_KEY`, `DB_USER` y `DB_PASSWORD` no tienen
    default en settings, pero `DB_NAME`, `DB_HOST` y `DB_PORT` tampoco lo
    tienen (`config/settings.py`) — corregir el doc o darles default.
  - Falta `MEDIA_URL`/`MEDIA_ROOT` (relevante cuando `products` sume imágenes).
  - `docker-compose.yml` monta `.:/app`: sirve sólo para dev, no para un
    deploy real (eso ya lo cubre el `Dockerfile` con gunicorn).

## Ya resuelto

De una ronda anterior de esta misma auditoría, ya en `main` y verificado con
166/166 tests OK:

- **Bug 500 en `clients`**: `PATCH`/`PUT` con el email de un cliente
  soft-deleted tiraba `IntegrityError` sin capturar. Arreglado en
  `clients/serializers.py` (`validate_email` contra `all_objects`) +
  `clients/services.py` (`select_for_update` para la race condition del create).
- **Gunicorn en producción**: `Dockerfile` corre `gunicorn`, no `runserver`,
  con `collectstatic` en el build.
- **Rate limiting en el login**: `ScopedRateThrottle` con `throttle_scope='login'`
  en `/api/auth/token/` y `/api/auth/token/refresh/`.
- **Logout real / blacklist de JWT**: `rest_framework_simplejwt.token_blacklist`
  instalado, `SIMPLE_JWT` con rotación + blacklist, endpoint
  `POST /api/auth/logout/`.
- **Hardening HTTPS**: bloque `if not DEBUG:` en `config/settings.py` con SSL
  redirect, HSTS, cookies seguras, `CSRF_TRUSTED_ORIGINS`.

`python manage.py check --deploy` con `DEBUG=False` da 2 warnings esperados
(no son huecos de configuración): `SECRET_KEY` débil porque el `.env` de dev
usa una de prueba, y `SECURE_HSTS_PRELOAD=False`, que es la elección correcta
por default (enviar el dominio al preload list de los browsers es una decisión
explícita y difícil de revertir).
