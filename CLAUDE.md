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
it. `objects` (via `core/managers.py`'s `SoftDeleteManager`) excludes
soft-deleted rows; `all_objects` (`AllObjectsManager`) includes everything.
`instance.delete(user)` soft-deletes instead of removing the row;
`instance.restore()` reverts it.

`BaseModelViewSet` (`core/viewsets.py`) wires this in automatically for any
model inheriting `BaseModel`: `perform_create`/`perform_update` set
`created_by`/`updated_by` from `request.user` via `serializer.save(...)`,
and `perform_destroy` calls `instance.delete(self.request.user)` — so a
plain `DELETE` request soft-deletes and records who did it, never a
physical `DELETE` query.

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
- `POST /api/auth/token/refresh/` — renew `access`

### Environment

All settings have defaults in `config/settings.py` except `SECRET_KEY`,
`DB_USER`, `DB_PASSWORD`. Inside Docker, `DB_HOST` is overridden to `db` so
the same `.env` works both locally and in Compose.
