# Char — Documentación del backend

Guía para retomar el backend sin tener que releer todo el código. Para el
detalle fino de cada pieza, las fuentes de verdad son el código, el `README.md`,
el `CLAUDE.md` y `docs/TODO.md` (pendientes). Este documento los resume y
conecta.

> Estado del documento: armado el 16/10/2026 leyendo el código. Los últimos
> cambios del backend son del 22/08/2026. No se ejecutaron los tests ni se
> levantó la app al escribirlo.

---

## 1. Qué es

API REST de **Char** (sistema comercial de una tienda): Django 6.1 + Django
REST Framework, PostgreSQL 18, autenticación por email + JWT, roles y permisos
con el sistema nativo de Django, documentación OpenAPI y Docker.

El front (React) vive en `../frontend` y consume esta API.

## 2. Stack

| Pieza | Versión / lib |
|---|---|
| Python | 3.12 |
| Django | 6.1 |
| DRF | 3.18 |
| Auth | `djangorestframework-simplejwt` 5.5 (con blacklist) |
| Filtros | `django-filter` |
| CORS | `django-cors-headers` |
| Docs | `drf-spectacular` (OpenAPI 3) |
| Config | `django-environ` |
| DB | PostgreSQL 18 (`psycopg2-binary`) |
| Prod | `gunicorn` |

## 3. Cómo levantarlo (siempre con Docker)

```bash
cd ~/Desktop/Char/backend
cp .env.template .env        # solo la primera vez, y completar SECRET_KEY
docker compose up --build    # backend en :8000, Postgres en :5434
```

Al arrancar migra solo (`migrate` + `runserver`). Primera vez en una base
nueva:

```bash
docker compose exec backend python manage.py seed_roles          # crea los roles
docker compose exec backend python manage.py createsuperuser     # pide EMAIL, no username
```

Comandos habituales (todos con el contenedor corriendo):

```bash
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py makemigrations
docker compose exec backend python manage.py test                # todos los tests
docker compose exec backend python manage.py test users          # una app
docker compose exec backend python manage.py test users.tests.test_views   # un módulo
docker compose exec backend python manage.py check --deploy      # chequeo de producción
```

Sin el contenedor levantado: `docker compose run --rm backend python manage.py <comando>`.

Bajar todo: `docker compose down`. **Con `-v` también borra la base**
(`docker compose down -v`), cuidado.

### URLs útiles

| URL | Qué es |
|---|---|
| `http://localhost:8000/api/docs/` | Swagger UI |
| `http://localhost:8000/api/redoc/` | Redoc |
| `http://localhost:8000/api/schema/` | OpenAPI crudo (YAML) |
| `http://localhost:8000/api/health/` | Healthcheck público |
| `http://localhost:8000/admin/` | Admin de Django |

Para probar endpoints protegidos en Swagger: `POST /api/auth/token/`, copiar el
`access` y pegarlo en **Authorize**.

### Conectarse a la base

| Campo | Valor |
|---|---|
| Host | `localhost` |
| Puerto | `5434` (dentro de Docker es 5432) |
| Base / usuario / contraseña | `char` / `char_user` / `char_password` (los de `.env`) |

```bash
docker compose exec db psql -U char_user -d char
```

## 4. Variables de entorno (`.env`)

Obligatorias (sin default en `config/settings.py`): `SECRET_KEY`, `DB_NAME`,
`DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`. `DEBUG` tiene default `False`;
en dev se pone en `True`.

`.env` actual de dev:

```env
DEBUG=True
SECRET_KEY=django-insecure-change-me
DB_NAME=char
DB_USER=char_user
DB_PASSWORD=char_password
DB_HOST=db          # "db" = servicio de Docker Compose
DB_PORT=5432
```

Opcionales (tienen default en `settings.py`, no están en `.env.template`):

| Variable | Default | Para qué |
|---|---|---|
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Hosts que Django acepta |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Orígenes del front |
| `EMAIL_BACKEND` | consola | Cómo se envían mails |
| `LANGUAGE_CODE` / `TIME_ZONE` | `es` / `UTC` | Localización |
| `JWT_ACCESS_TOKEN_MINUTES` | `5` | Vida del access token |
| `JWT_REFRESH_TOKEN_DAYS` | `1` | Vida del refresh token |
| `THROTTLE_RATE_LOGIN` / `_ANON` / `_USER` | `10/min` / `60/hour` / `1000/hour` | Rate limiting |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD`, `CSRF_TRUSTED_ORIGINS` | ver `settings.py` | Hardening HTTPS, **solo con `DEBUG=False`** |

## 5. Estructura

```
backend/
├── config/      settings, urls raíz, wsgi/asgi
├── core/        infraestructura transversal (no es una app de "features")
├── users/       usuario custom por email + auth JWT + grupos
├── clients/     clientes de la tienda
├── products/    catálogo (a medio hacer)
├── docs/        TODO.md y este documento
├── Dockerfile, docker-compose.yml, requirements.txt, manage.py
```

### `core/`

| Archivo | Rol |
|---|---|
| `models.py` | `BaseModel` abstracto: auditoría + soft delete |
| `managers.py`, `querysets.py` | `objects` (excluye borrados) / `all_objects` (todo) |
| `viewsets.py` | `BaseModelViewSet`: permisos + paginación + auditoría + soft delete |
| `permissions.py` | `DjangoObjectPermissionsWithView` |
| `pagination.py` | `DefaultPagination` |
| `roles.py` | Diccionario `ROLES` (fuente de verdad de los roles) |
| `management/commands/seed_roles.py` | Sincroniza Groups/Permissions con `ROLES` |
| `views.py`, `urls.py` | Healthcheck |
| `schemas.py` | Piezas OpenAPI reutilizables (errores comunes) |

## 6. Conceptos clave

### 6.1 `BaseModel` y soft delete

Todo modelo de negocio hereda de `core.models.BaseModel`, que agrega:

- `created_at`, `updated_at`
- `created_by`, `updated_by` (FK a `User`, `SET_NULL`)
- `is_deleted`, `deleted_at`, `deleted_by`

`Model.objects` **excluye** los borrados; `Model.all_objects` los incluye.
`instance.delete(user)` hace soft delete; `instance.restore()` lo revierte.

### 6.2 `BaseModelViewSet`

Subclase de `ModelViewSet` ya preparada. Para exponer un modelo basta:

```python
from core.viewsets import BaseModelViewSet

class WidgetViewSet(BaseModelViewSet):
    queryset = Widget.objects.all()
    serializer_class = WidgetSerializer
```

Gratis: permisos por método HTTP, paginación, `created_by`/`updated_by` desde
`request.user`, y `DELETE` = soft delete registrando quién fue (nunca un
`DELETE` físico).

### 6.3 Roles y permisos

No hay modelo `Role`. Un rol es un `Group` de Django con `Permission`s.

- `DjangoObjectPermissionsWithView` mapea cada método HTTP a un permiso:
  `GET` → `view_`, `POST` → `add_`, `PUT/PATCH` → `change_`, `DELETE` →
  `delete_` (DRF por defecto no exige `view_`; acá sí).
- El chequeo a nivel de objeto cae al de modelo (ver pendientes en §10).
- Los roles se definen en `core/roles.py` y se cargan con `seed_roles`
  (idempotente):

| Rol | Permisos |
|---|---|
| **Administrador** | `users`: add/view/change/delete · `clients`: add/view/change/delete · `auth.view_group` |
| **Vendedor** | `clients`: add/view/change (no borra) |

Ningún rol tiene permisos de `products` todavía. El superusuario es un flag, no
un rol, y se salta todos los chequeos.

**Para agregar un rol:** sumar la entrada a `ROLES` y correr `seed_roles`.

### 6.4 Autenticación (JWT)

- `DEFAULT_PERMISSION_CLASSES = IsAuthenticated`: todo está cerrado por
  defecto; para abrir un endpoint hay que poner `AllowAny` en la view
  (ej. `health`).
- Access token: 5 min. Refresh token: 1 día.
- **Rotación + blacklist**: cada `refresh` entrega un `refresh` **nuevo** e
  invalida el usado. El cliente tiene que guardar el par completo (el front ya
  lo hace con `setTokens`).
- Logout real: `POST /api/auth/logout/` mete el refresh en la blacklist. El
  `access` vivo sigue siendo válido hasta que expire solo.
- Rate limiting: login y refresh usan el scope `login` (10/min). Usa el cache
  en memoria de Django, por proceso: con varios workers de gunicorn el límite
  real se multiplica (comentado en `settings.py`).

### 6.5 Convención de documentación OpenAPI

La documentación de cada endpoint (`@extend_schema`, ejemplos, respuestas)
vive en `schemas.py` junto al `views.py` de cada app, **nunca inline en la
view**. La view queda con su decorador `@..._SCHEMA` y la lógica real. Piezas
compartidas van en `core/schemas.py`.

### 6.6 Reglas del proyecto

- Comentarios de documentación, docstrings y mensajes al usuario final
  (errores de validación, respuestas) **en español**.
- Al cambiar código, actualizar en el mismo cambio JSDoc/docstrings, READMEs y
  `CLAUDE.md` que lo describan.
- Tests con el runner de Django (`manage.py test`), no pytest.

## 7. API

Prefijo `/api/`. Listados paginados: 20 por página, `?page=N`,
`?page_size=N` (máx. 100). Formato: `{count, next, previous, results}`.

### Auth

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/auth/token/` | Login. Body `{email, password}` → `{access, refresh}` |
| POST | `/auth/token/refresh/` | Body `{refresh}` → `{access, refresh}` (rotado) |
| POST | `/auth/logout/` | Body `{refresh}`. Lo mete en la blacklist |

### Usuarios (`users`)

No hay registro público: los usuarios los crea un Administrador.

| Método | Ruta | Permiso | Notas |
|---|---|---|---|
| GET | `/users/` | `view_user` | Filtros `?is_active=`, `?search=` (nombre, apellido, email) |
| POST | `/users/` | `add_user` | `password` obligatoria al crear |
| GET/PATCH/PUT | `/users/{id}/` | `view_`/`change_user` | |
| DELETE | `/users/{id}/` | `delete_user` | **Desactiva** (`is_active=False`), no borra |
| GET | `/users/me/` | solo autenticado | Usuario del token |
| GET | `/groups/` | `view_group` | Solo lectura. Roles disponibles |

`is_staff` e `is_superuser` son de solo lectura en la API.

### Clientes (`clients`)

| Método | Ruta | Permiso |
|---|---|---|
| GET | `/clients/` | `view_client` — `?search=` (nombre, apellido, email), `?ordering=` (default `-created_at`) |
| POST | `/clients/` | `add_client` |
| GET/PATCH/PUT | `/clients/{id}/` | `view_`/`change_client` |
| DELETE | `/clients/{id}/` | `delete_client` (soft delete) |

Campos: `first_name`, `last_name`, `phone`, `email` (único, opcional),
`origin` (`instagram`, `facebook`, `tiktok`, `referral`, `physical_store`,
`google`, `other`).

Comportamiento a recordar: si se da de alta un cliente con el **email de uno
soft-deleted**, se **restaura** ese registro con los datos nuevos
(`clients/services.py`), en vez de dar error de unicidad. Un email de cliente
activo da error de validación, y la race condition del alta está cubierta con
`select_for_update`.

### Catálogo (`products`)

| Método | Ruta | Estado |
|---|---|---|
| CRUD | `/categorias/` | Implementado (campo `nombre`). Sin permisos asignados a ningún rol |

### Otros

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health/` | Healthcheck, sin autenticación |

## 8. Modelos

```
User (AbstractUser, sin username, login por email)
Client (BaseModel)        first_name, last_name, phone, email*, origin
Categoria (BaseModel)     nombre
Color (BaseModel)         nombre*                       ← sin usar por nadie
Producto (BaseModel)      categoria→Categoria, nombre, descripcion,
                          precio_venta, precio_costo
Variante (BaseModel)      producto→Producto, talle, color→Color
                          único (producto, talle, color)
                          talles: XS S M L XL XXL UNICO
Stock (BaseModel)         variante↔Variante (1 a 1), fisica, reservada
                          CHECK reservada <= fisica · disponible = fisica - reservada
```

`*` = único. Las FK de `products` usan `PROTECT`.

## 9. Docker y producción

- `docker-compose.yml` (dev): monta `.:/app`, corre `migrate` +
  `runserver`, Postgres con healthcheck y volumen `postgres_data`.
- `Dockerfile`: imagen `python:3.12-slim`, usuario no-root, `collectstatic` en
  el build y `CMD` de **gunicorn** (3 workers). Es el que sirve para un deploy
  real; el compose de dev lo pisa con `runserver`.
- Con `DEBUG=False` se activa el hardening: redirect a HTTPS, HSTS, cookies
  seguras y `CSRF_TRUSTED_ORIGINS`. `check --deploy` da 2 warnings esperados
  (`SECRET_KEY` de dev y `HSTS_PRELOAD=False`, que es lo correcto por defecto).

## 10. Pendientes (resumen de `docs/TODO.md`)

Por prioridad:

1. **Escalada de privilegios vía `groups`** (`users/serializers.py`): quien
   tenga `change_user` puede asignarse cualquier grupo. Latente: hoy solo
   `Administrador` tiene ese permiso. **Cerrarlo antes de crear un rol
   intermedio.** Opción recomendada: solo se pueden asignar grupos cuyos
   permisos uno ya posee (`validate_groups`), y bloquear la auto-edición de
   `groups` e `is_active`.
2. **Completar `products`**: serializers/views/urls de `Producto`, `Variante`,
   `Stock` y `Color`; permisos `products.*` en `core/roles.py`; unificar
   nomenclatura (hoy en español: `Categoria`, `precio_venta`) con el resto en
   inglés; que el admin use `all_objects` para ver soft-deleted.
3. **`delete()` con firma incompatible con Django**: `BaseModel.delete(user)`
   y `SoftDeleteQuerySet.delete(user)` rompen el "Delete selected" del admin.
   Fix: `user=None` por defecto.
4. **`has_object_permission` neutralizado**: el fallback a permiso de modelo
   hace que un backend de permisos por objeto nunca restrinja más. Decidir si
   es lo buscado.
5. **`LOGGING` ausente** en `settings.py`.
6. **Higiene**: sin linter/formatter/CI; falta `MEDIA_URL`/`MEDIA_ROOT`
   (cuando `products` tenga imágenes); `docker-compose.yml` es solo para dev.

Nota: el TODO todavía lista la paginación como pendiente, pero ya está
implementada (`DefaultPagination`, commit del 22/08). Falta verificar que los
tests de listado (`clients/tests/test_views.py`, `users/tests/test_views.py`)
estén adaptados al formato paginado, y quitar ese ítem del TODO.

## 11. Cómo agregar un recurso nuevo (receta)

1. Modelo heredando de `BaseModel` en `<app>/models.py`; `makemigrations` y
   `migrate`.
2. `serializers.py` (mensajes de validación en español).
3. `schemas.py` con el decorador `@..._SCHEMA` (OpenAPI).
4. `views.py`: `class XViewSet(BaseModelViewSet)` con su decorador de schema.
5. `urls.py` con un `DefaultRouter`, e incluirlo en `config/urls.py`.
6. Permisos del modelo en `core/roles.py` para los roles que correspondan y
   `seed_roles`.
7. Registrar en `admin.py` (usando `all_objects` para ver los borrados).
8. Tests en `<app>/tests/` (modelos, serializers, vistas y permisos; para
   permisos usar usuarios no-superuser con Groups reales, porque el superuser
   se salta los chequeos).
9. Actualizar README, `CLAUDE.md` y este documento.

## 12. Historial resumido (git)

- 19/08: proyecto base, `users`, `clients`, soft delete, permisos y tests.
- 20/08: búsqueda y orden en clients, acción `me`, app `products` (Categoria,
  Color, Producto), fix del 500 con emails soft-deleted.
- 21/08: JWT blacklist y hardening de seguridad, `Variante` y `Stock`.
- 22/08: endpoint de `Categoria`, `DefaultPagination` y ajuste de CORS.
