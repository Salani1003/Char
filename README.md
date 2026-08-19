# Backend Template

Backend genérico construido con Django y Django REST Framework, pensado como
punto de partida para cualquier proyecto nuevo: autenticación por email + JWT,
CORS, healthcheck, roles/permisos y Docker listos desde el arranque.

## Stack

- Python 3.12
- Django 6.1
- Django REST Framework + Simple JWT
- django-cors-headers
- PostgreSQL 18
- Docker / Docker Compose
- Gunicorn (producción)

## Estructura del proyecto

```
backend/
├── config/         # Configuración del proyecto (settings, urls, wsgi, asgi)
├── core/           # App principal (health check, permisos/roles, utilidades comunes)
├── users/          # App de usuarios (modelo de usuario custom por email)
├── manage.py
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

La app `users` define un modelo de usuario custom (`users.User`) configurado
como `AUTH_USER_MODEL`, que usa **email en lugar de username** para loguearse.

## Requisitos

- Python 3.12+
- PostgreSQL (o Docker, para levantar todo con Compose)

## Configuración

1. Copiá el archivo de variables de entorno de ejemplo:

   ```bash
   cp .env.template .env
   ```

2. Completá las variables en `.env`:

   ```
   DEBUG=True
   SECRET_KEY=<tu-secret-key>

   ALLOWED_HOSTS=localhost,127.0.0.1
   CORS_ALLOWED_ORIGINS=http://localhost:3000

   DB_NAME=<nombre-db>
   DB_USER=<usuario>
   DB_PASSWORD=<password>
   DB_HOST=localhost
   DB_PORT=5432

   EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
   ```

   Todas las variables tienen un default razonable en `config/settings.py`
   salvo `SECRET_KEY`, `DB_USER` y `DB_PASSWORD`.

## Uso con Docker (recomendado)

```bash
docker compose up --build
```

Esto levanta:

- `backend`: servidor Django en `http://localhost:8000`, esperando a que
  Postgres esté saludable y aplicando migraciones automáticamente al iniciar.
- `db`: PostgreSQL en el puerto `5434`.

`DB_HOST` se pisa a `db` dentro del contenedor, así que el mismo `.env` sirve
tanto para Docker como para correr el proyecto en un entorno local.

## Uso local (sin Docker)

1. Creá y activá un entorno virtual:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. Instalá las dependencias:

   ```bash
   pip install -r requirements.txt
   ```

3. Aplicá las migraciones:

   ```bash
   python manage.py migrate
   ```

4. Creá un superusuario (pide **email**, no username):

   ```bash
   python manage.py createsuperuser
   ```

5. Levantá el servidor de desarrollo:

   ```bash
   python manage.py runserver
   ```

El servidor queda disponible en `http://localhost:8000`.

## Endpoints

- `GET /api/health/` — healthcheck público, sin autenticación.
- `POST /api/auth/token/` — obtiene `access` y `refresh` (body: `email`, `password`).
- `POST /api/auth/token/refresh/` — renueva el `access` token.
- `/admin/` — admin de Django.

Por defecto, todos los endpoints de DRF requieren autenticación JWT
(`IsAuthenticated`); ajustar `permission_classes` por vista según haga falta.

## Roles y permisos

El template usa el sistema **nativo de Django** (`django.contrib.auth`):
`Group`, `Permission` y `user.has_perm(...)`. No hay lógica de roles
custom — los roles son simplemente Groups con Permissions asignadas,
administrables desde `/admin/` (o por fixture/migración de datos en cada
proyecto que use este template).

Integración con DRF en `core/permissions.py` y `core/viewsets.py`:

- **`core.permissions.DjangoObjectPermissionsWithView`**: extiende
  `DjangoObjectPermissions` de DRF para que también el `GET` (no sólo
  escrituras) requiera el permiso `view_<modelo>`. Con esto, cada método
  HTTP queda mapeado 1:1 a un permiso Django (`add_`/`change_`/`delete_`/`view_`),
  chequeado contra los permisos/grupos del usuario autenticado.
- **`core.viewsets.BaseModelViewSet`**: `ModelViewSet` base que ya trae
  configurada esa permission class. Para exponer un modelo con permisos
  por endpoint alcanza con:

  ```python
  from core.viewsets import BaseModelViewSet

  class WidgetViewSet(BaseModelViewSet):
      queryset = Widget.objects.all()
      serializer_class = WidgetSerializer
  ```

**Nivel de endpoint**: funciona out-of-the-box (backend de permisos por
defecto de Django evalúa a nivel de modelo).

**Nivel de objeto**: la permission class ya llama a
`has_object_permission` en retrieve/update/delete, delegando en
`user.has_perm(perm, obj)`. Bajo el backend por defecto ese `obj` se
ignora (degrada a nivel de modelo), así que no rompe nada hoy. El día
que un proyecto derivado necesite reglas por objeto, alcanza con agregar
un backend de permisos de objeto (p. ej. `django-guardian`) a
`AUTHENTICATION_BACKENDS` — sin tocar código de vistas ni permisos.

**Seed de roles**: `core/roles.py` define el diccionario `ROLES`
(vacío por default), donde cada entrada es un Group con su lista de
permisos (`"<app_label>.<codename>"`). Para crear/actualizar los Groups
en la base de datos a partir de ese diccionario:

```bash
python manage.py seed_roles
```

Es idempotente: correrlo de nuevo deja el mismo resultado. Cada proyecto
derivado de este template define sus propios roles completando `ROLES`.

## Tests

```bash
python manage.py test
```

## Producción

La imagen de Docker corre como usuario no-root y trae `gunicorn` en las
dependencias. Para producción, reemplazar el `command` del servicio `backend`
en `docker-compose.yml` (o el `CMD` del `Dockerfile`) por algo como:

```bash
gunicorn config.wsgi:application --bind 0.0.0.0:8000
```

y correr `python manage.py collectstatic` antes de servir.
