# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Generic Django/DRF backend template ("Char"): email+JWT auth, CORS, healthcheck,
a native-Django roles/permissions system, OpenAPI docs, and Docker — meant as a
reusable starting point for new backends, not a specific product.

## Commands

```bash
# Local dev (no Docker) — requires Postgres running and .env configured (cp .env.template .env)
python manage.py migrate
python manage.py runserver

# Docker (preferred) — runs backend on :8000, Postgres on :5434, auto-migrates on start
docker compose up --build

# Tests (Django's own test runner, not pytest)
python manage.py test
python manage.py test users              # single app
python manage.py test users.tests.SomeTestCase.test_something   # single test

# Roles: seed Groups/Permissions from core/roles.py (idempotent)
python manage.py seed_roles

# Superuser (prompts for email, not username — AUTH_USER_MODEL is users.User)
python manage.py createsuperuser
```

No linter/formatter is configured in this repo currently.

## Architecture

- `config/` — settings, root urls, wsgi/asgi. Settings are env-driven via
  `django-environ`, reading `.env` at `BASE_DIR/.env` (see `.env.template`).
- `core/` — cross-app infrastructure: healthcheck, the permissions system,
  and shared OpenAPI pieces. Not a "features" app.
- `users/` — custom user app. `users.User` (`AUTH_USER_MODEL`) drops
  `username` and logs in via `email` (`USERNAME_FIELD = 'email'`), with a
  custom `UserManager` in `users/managers.py`.
  Security invariants: emails are stored lowercase and unique
  case-insensitively (`Lower(email)` constraint; login is `iexact`);
  non-superusers cannot see/edit superusers and can only assign groups they
  already hold; they also cannot modify/delete a user with more roles or
  permissions than their own (`users/permissions.py::CanManageUser`); nobody
  can delete or deactivate their own user. `User` is not a `BaseModel`:
  `DELETE` just sets `is_active=False`.

### Permissions / roles system

There is no custom `Role` model. A "role" is just a `django.contrib.auth`
`Group` with `Permission`s attached, managed through Django's own admin/auth
backend — no bespoke role logic anywhere.

- `core/permissions.py` — `DjangoObjectPermissionsWithView` extends DRF's
  `DjangoObjectPermissions` so `GET`/`HEAD`/`OPTIONS` also require
  `view_<model>` (DRF's default only guards writes). This maps every HTTP
  method 1:1 to a Django permission (`add_`/`change_`/`delete_`/`view_`).
- `core/viewsets.py` — `BaseModelViewSet` is a `ModelViewSet` preconfigured
  with that permission class. New model endpoints should subclass this
  instead of DRF's `ModelViewSet` directly:

  ```python
  from core.viewsets import BaseModelViewSet

  class WidgetViewSet(BaseModelViewSet):
      queryset = Widget.objects.all()
      serializer_class = WidgetSerializer
  ```

- Object-level permission checks are already wired (`has_object_permission`
  delegates to `user.has_perm(perm, obj)`), but degrade to model-level
  checks under Django's default auth backend. Adding an object-permission
  backend (e.g. `django-guardian`) to `AUTHENTICATION_BACKENDS` activates
  them with no view/permission-class changes needed.
- `core/roles.py` — the `ROLES` dict (`{group_name: ["<app_label>.<codename>", ...]}`)
  is the single source of truth for roles; `seed_roles` management command
  syncs Groups/Permissions in the DB to match it.

### BaseModel / soft delete

`core/models.py` — `BaseModel` is an abstract model adding audit fields
(`created_at`/`updated_at`, `created_by`/`updated_by`) and soft delete
(`is_deleted`, `deleted_at`, `deleted_by`) to any model that inherits from
it (`created_at`/`is_deleted` are indexed). `objects` (via
`core/managers.py`'s `SoftDeleteManager`) excludes soft-deleted rows;
`all_objects` (`AllObjectsManager`) includes everything.
`instance.delete(user=None)` soft-deletes instead of removing the row;
`instance.restore(user=None)` reverts it. Both (and `QuerySet.delete`) bump
`updated_at`/`updated_by`, and `user` is optional so Django's admin can call
them without arguments.

- `core/serializers.py` — `BaseModelSerializer`: audit/soft-delete fields
  forced read-only. Uniqueness convention: use
  `core.models.unique_when_active('field', name=...)` in `Meta.constraints`
  (unique only among non-deleted rows, so a deleted row's value can be
  reused; the serializer validates it → 400). Plain `unique=True` still
  works but its value is never reusable. `restore()` can raise
  `IntegrityError` if the value was reused. (`Client.email` keeps its
  `unique=True` + restore-on-create flow in `ClientService`.)
- `core/admin.py` — `BaseAdmin`: register `BaseModel` models with it instead
  of `admin.ModelAdmin` (lists deleted rows, Activos/Eliminados filter,
  "Restaurar seleccionados" action, soft delete records `deleted_by`).
- `core/filters.py` — `NullsLastOrderingFilter` (opt-in, nulls last in both
  directions).

`BaseModelViewSet` (`core/viewsets.py`) wires this in automatically for any
model inheriting `BaseModel`: `perform_create`/`perform_update` set
`created_by`/`updated_by` from `request.user` via `serializer.save(...)`,
and `perform_destroy` calls `instance.delete(self.request.user)` — so a
plain `DELETE` request soft-deletes and records who did it, never a
physical `DELETE` query. It also ships `DjangoFilterBackend`, `SearchFilter`
and `OrderingFilter` with a deterministic default `ordering = ['-created_at', '-id']`
(`OrderingFilter` makes the view's `ordering` win over the queryset's
`order_by`, so a viewset that wants another order must set `ordering`).

### OpenAPI docs convention

Endpoint documentation (`@extend_schema`, examples, response descriptions)
always lives in a `schemas.py` file next to each app's `views.py` — never
inline in the view. A view is reduced to its `@..._SCHEMA` decorator plus
real logic (see `users/views.py` / `users/schemas.py`, `core/views.py` /
`core/schemas.py`). Pieces shared across apps (common error responses, etc.)
go in `core/schemas.py`, imported by per-app `schemas.py` modules.

Docs are served via drf-spectacular:
- `GET /api/schema/` — raw OpenAPI YAML
- `GET /api/docs/` — Swagger UI
- `GET /api/redoc/` — Redoc

### Auth

JWT via `rest_framework_simplejwt`. `DEFAULT_PERMISSION_CLASSES` is
`IsAuthenticated` globally — endpoints are locked down by default, opt out
per-view (e.g. `health` uses `AllowAny`).

- `POST /api/auth/token/` — obtain `access`/`refresh` (body: `email`, `password`)
- `POST /api/auth/token/refresh/` — renew `access`. `ROTATE_REFRESH_TOKENS` + `BLACKLIST_AFTER_ROTATION` are on: the response also carries a new `refresh` and the used one is blacklisted, so clients must store the new pair.
- `POST /api/auth/logout/` — blacklists the refresh token

### Environment

All settings have defaults in `config/settings.py` except `SECRET_KEY`,
`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`. `.env.template` lists only
those (plus `DEBUG`); the rest (`ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`,
`EMAIL_BACKEND`, `NUM_PROXIES` (poné 1 detrás de un proxy/LB, si no el throttling por IP no es confiable), `THROTTLE_RATE_*`, `JWT_*`, `SECURE_*`, `CSRF_TRUSTED_ORIGINS`) are optional overrides. Inside Docker, `DB_HOST` is overridden to `db` so
the same `.env` works both locally and in Compose.

### Seguridad de tokens / docs

Desactivar un usuario o cambiarle la contraseña blacklistea sus refresh tokens
(`users/signals.py`). `/api/schema|docs|redoc/` son públicos sólo con `DEBUG=True`;
en producción exigen staff. `/health/` no tiene throttling y chequea la DB.
Recomendado programar `manage.py flushexpiredtokens`.
