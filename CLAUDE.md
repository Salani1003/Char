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

# Verifica las credenciales de Cloudinary: sube un PNG de 1x1, lo muestra y lo borra
python manage.py check_image_storage

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

- `products/` — catálogos, producto y variantes : `Category` (a lo sumo 2 niveles, `parent` opcional; el producto irá
  a una hoja y filtrar por una raíz incluye sus hijas), `Brand`, `ProductModel`
  (modelo de una marca), `Color` y `Size` (con `order`). Todos son `BaseModel`
  con nombre único case-insensitive entre activos (`Lower('name')`, validado en
  `UniqueNameSerializer`). No se borra una categoría con subcategorías ni una
  marca con modelos. Endpoints: `categories`, `brands`, `product-models`, `colors`, `sizes`, `products`.
  `Product`: categoría hoja obligatoria, `brand`/`product_model` opcionales (la marca
  se deriva del modelo y deben coincidir), `sale_price`, `cost_price` opcional y
  promo (`promo_price` + `promo_start`/`promo_end`, las tres juntas, inclusivas,
  precio < venta; reglas en `Product.clean()`, reutilizadas por el serializer).
  `current_price` = promo si hoy está en rango, si no venta (`effective_price`
  espeja esto en SQL para filtrar/ordenar). `cost_price` sólo se lee/escribe con
  el permiso `products.view_cost_price` (sólo Administrador); sin él se omite.
  `ProductVariant` (`product-variants`): producto + color + talle (único entre
  activas) + `sku` asignado por el sistema (`CHAR-0001`…, contador `SkuCounter` bajo
  `select_for_update`, de sólo lectura, nunca se reutiliza);
  el producto no cambia tras crearla; el saldo vive en `stock.StockLevel`; acá sólo `min_stock` (umbral de reposición, default 0 = sin alerta; entero ≥ 0, se edita por `PATCH` con `change_productvariant`, sin permiso aparte).
  Nombres de catálogos (`Brand`, `ProductModel`, `Category`, `Color`) sin repetidos:
  `NormalizedNameMixin` los normaliza al guardar (`products/text.py`: espacios colapsados;
  todo en minúsculas → capitalizado, por palabra en marcas y sólo la inicial en el resto;
  con alguna mayúscula se respeta) y `clean()` rechaza uno que ya exista entre activos sin
  distinguir mayúsculas, tildes ni espacios repetidos ("Nike"="nike"="NIKE", "Ñandú"="Nandu"),
  acotado por marca (modelos) o por padre (categorías). Vale igual en API (400 con `existing`)
  y admin; el índice `Lower(name)` es el respaldo de la base. `Size` se guarda siempre en
  MAYÚSCULAS (`STYLE_UPPER`: "xl" → "XL") y es único globalmente.
  Orden de los catálogos (para selectores, sin reordenar en el front): `Brand`, `Color`
  y `ProductModel` salen alfabéticos sin distinguir mayúsculas (`Lower(name)`; modelos por
  marca y luego nombre); `Category` agrupada por categoría principal (la principal primero)
  y luego por nombre. Las tildes dependen del collation de Postgres (`en_US.utf8` en
  Docker: bien para Á/é; la ñ se ordena junto a la n, no como letra aparte). Con collation
  `C` el test `products/tests/test_ordering.py` falla. Para cargar todas las opciones usar
  `?page_size=100` (máx.); para muchas, buscar con `?search=`.
  Apoyo al front: `Category` trae `label` ("Vestidos › Largos"), `parent_name`, `has_children` y `products_count` (activos; anotados en
  el viewset, sin consultas por fila) y se filtra con `?leaf=true|false` (leaf = asignable
  a productos); `Product` trae `category_label` ("Vestidos › Largos"), `brand_name` y
  `product_model_name`; `Color.hex` se guarda siempre en mayúsculas (`#14284B`).
  Slugs (`Category`, `Brand`, `Product`; futura tienda online): únicos entre activos
  (`unique_when_active`), opcionales al crear — los genera `products/slugs.py` desde el
  nombre (colisión: prefijo del padre en categorías, luego `-2`, `-3`…) con reintento
  ante carreras (`AutoSlugMixin`), y `SlugFallbackMixin` cubre admin/shell/tests. No
  cambian al renombrar; `slug: ""` en un PATCH de producto lo regenera sólo si no está
  publicado. `Product.is_published` (default `false`, filtrable) marca si va a la tienda y sólo se
  activa con ≥1 variante activa **que tenga foto** (una `ProductImage` activa de su color; la
  exigencia rige al pasar a publicado, no se revalida al editar uno ya publicado) (no se puede crear ya publicado; mientras esté publicado tampoco se puede dejar sin ninguna variante con foto: no se elimina ni se cambia de color la última foto o la última variante con foto; no se elimina la última
  variante de un producto publicado — ambas reglas sólo en la API/`clean`, no en el admin masivo).
  Mismo criterio que `Cali/cali_backend`.
  `GET product-variants/` es la grilla de variantes: cada fila trae nombres (producto, color
  con `color_hex`, talle, categoría, marca, modelo), `is_published` y precios del producto
  (`current_price`, `is_on_promo`; sin costo). Filtros: `product`, `color`, `size`, `category`
  (raíz incluye hijas), `brand`, `product_model`, `is_published`, `on_promo`, `min_price`,
  `max_price`; `search`; `ordering` por `sku`, `created_at`, `product__name`, `color__name`,
  `size__order`, `effective_price`, `product__sale_price`. Al escribir sólo se usan
  `product`, `color` y `size`. `effective_price()` (en `products/filters.py`) es el precio vigente en SQL.
  `GET product-variants/` trae además `quantity` e `is_low_stock` (mismos nombres y criterio que `stock/`; anotados con `stock.annotations.with_stock`, sin consultas por fila), sólo con `stock.view_stocklevel` (sin él los campos se omiten); `ordering=quantity`.
  `GET products/` trae `variants_count` (activas; para todo el que ve productos) y, sólo en el listado y con
  `products.view_productvariant`, `variants` (`{id, sku, color{id,name,hex}, size{id,name,order}}` por color y talle);
  filtro `?has_variants=true|false` y `ordering=variants_count`.
  `GET products/{id}/with-variants/` devuelve el producto + `variants` activas (color/talle
  anidados; exige `view_product` y `view_productvariant`); `GET products/{id}/` no las incluye.
  No se borra categoría/marca/modelo con productos activos, ni producto/color/talle
  con variantes activas.

- `stock/` — stock de un único local (sin modelo de ubicación). Nunca hay stock negativo (`CheckConstraint`
  + `InsufficientStock` → 400 con `detail`, `variant`, `available`, `requested`; los números viajan como texto).
  Los **movimientos son la fuente de verdad** (`StockMovement`: inmutable, sin soft delete, con `quantity` con signo,
  `stock_before`/`stock_after`, `kind` ingreso/egreso/ajuste y `reason`) y cada uno es una **línea de una
  `StockOperation`**, el "documento" que los agrupa: un ingreso/egreso en lote, la confirmación de un recuento
  (aunque no tenga diferencias: queda una operación sin líneas) y cada anulación son una operación. El historial
  principal es `stock-operations/` (una fila por operación con `lines_count` y `units`; el detalle trae `movements`);
  `stock-movements/` son las líneas sueltas (útil para el historial de una variante con `?variant=`). Toda operación se
  crea desde los servicios, nunca a mano: `apply_movement` sin `operation` crea una de una sola línea.
  `StockLevel` es el saldo por variante y **sólo se
  toca desde `stock/services.py`**: `apply_movement` (bloquea el saldo con `select_for_update`, se une a la transacción
  abierta), `apply_movements` (lote atómico → devuelve la operación; orden por id de variante), `reverse_movement`,
  `adjust_to_count`, `confirm_count`/`cancel_count`. Nunca modifiques `StockLevel` ni crees `StockMovement` a mano. Un
  error se corrige con `POST stock-movements/{id}/reverse/` (motivo `anulacion`; una sola vez; no se anulan anulaciones
  ni ajustes; anula una línea, no la operación entera). Motivos:
  ingreso `compra`/`cambio_entrada`/`stock_inicial`/`otro`; egreso `rotura_merma`/`perdida`/`uso_interno`/
  `devolucion_proveedor`/`cambio_salida`/`venta`/`otro`; ajuste `recuento`/`correccion`. `venta` y `anulacion` los genera el
  sistema: `POST stock-operations/` los rechaza. El stock inicial se carga con un ingreso en lote `stock_inicial`. No hay
  devoluciones de cliente; los cambios los hace el módulo `sales/` (atómicos, ver abajo).
  `StockOperation.sale` / `.exchange` (FK nullable) enlazan la operación con su documento de ventas (filtros `?sale=`,
  `?exchange=` en `stock-operations/`). Una línea de una operación de venta o cambio **no se anula suelta**
  (`reverse_movement` responde 400: se anula desde la venta/cambio); `reverse_operation(operation)` anula una operación entera
  en UNA operación `anulacion` (atómica; hereda el enlace a la venta/cambio) y es lo que usa `sales/`.
  No se mueve stock de una variante eliminada y no se elimina una variante con stock > 0
  (`ProductVariantViewSet.perform_destroy`; sólo en la API, no en el admin).
  Endpoints: `stock/` (grilla de variantes activas con `quantity`, `min_stock`, `is_low_stock` = `min_stock > 0` y
  `quantity <= min_stock`, y `image_url`/`thumbnail_url` con el mismo criterio que `product-variants` vía `products.filters.variant_image_key`, sólo con `products.view_productimage`, si no `null`; filtros `in_stock`, `out_of_stock`, `low_stock`, `category`…), `stock/summary/`, `stock-movements/`
  (líneas: listar/ver/anular), `stock-operations/` (historial agrupado; `POST` registra el ingreso/egreso en lote), `stock-counts/`. Nada se edita ni se borra.
  Recuentos (`StockCount`, `BaseModel`): borrador → `confirm` o `cancel`; parcial (sólo se ajustan las variantes cargadas);
  `POST items/` hace upsert de una línea, `POST items/bulk/` de muchas a la vez (atómico; las no mencionadas quedan) y `DELETE items/{variant_id}/` quita una; al confirmar se calcula la diferencia con
  el saldo bloqueado (`system_quantity`, `difference`) y se crea un ajuste `recuento` sólo si hubo diferencia. Confirmado o
  cancelado queda congelado; no se borra. Permisos (`core/permissions.py::ActionPermission`, por acción, no un CRUD de
  modelo): `view_stocklevel`, `view_stockmovement`, `add_stockmovement` (ingresar, egresar, anular), `view_stockcount`,
  `add_stockcount` (armar, confirmar y cancelar: no hay aprobación en dos pasos). Administrador todo; Vendedor sólo ver.
  El admin es de sólo consulta. `ActionPermission` vive en `core/permissions.py` (lo usan `stock/` y `sales/`).

- `sales/` — ventas y cambios de un único local. Ni la venta ni el cambio se editan ni se borran: se **anulan** (no son
  `BaseModel`; `status` `completada`/`anulada`, con `voided_at`/`voided_by`/`void_reason`; el motivo es obligatorio).
  **El stock se toca sólo por `stock/services.py`**, desde `sales/services.py` (nunca a mano). Los endpoints son finos: la
  lógica va en los servicios, que son atómicos y bloquean la fila de la venta (`select_for_update`) para que anular una venta,
  anular un cambio y cambiar no corran a la vez.
  `Sale` (`sales/`): cliente opcional (`clients.Client`, `PROTECT`), `payment_method` (`transferencia`, `efectivo`,
  `tarjeta_credito`, `tarjeta_debito`, `qr`), `subtotal` (a precio de lista), `total` (lo cobrado), `discount_percent`/
  `discount_reason`, `note` e `idempotency_key` opcional y única (reenviar la misma devuelve la venta ya registrada con 200).
  `SaleItem`: variante + cantidad con el precio **congelado** al vender: `list_price` (`Product.get_current_price()`: promo si está
  en rango, si no venta), `discount_percent`, `unit_price` (lo que pagó, redondeado al centavo), `subtotal` y `exchanged_quantity`.
  **El precio nunca viaja en el POST.** Variante única por venta. Sólo se vende lo activo; sin stock → `InsufficientStock` (400,
  mismo formato que stock) y no queda nada guardado. `create_sale` descuenta con `apply_movements(EGRESO, venta, sale=...)`;
  `void_sale` devuelve el stock con `reverse_operation` y se bloquea si la venta tiene cambios activos (primero se anulan).
  Descuento: sólo los valores de `settings.SALE_DISCOUNT_CHOICES` (hoy 0, 5, 10), a toda la venta, y con 5 o 10 exige
  `sales.apply_discount` (403; hoy sólo Administrador). No hay descuento manual libre ni por ítem.
  `Exchange`/`ExchangeItem` (`exchanges/`): cambio **sobre una venta** completada y dentro de `settings.EXCHANGE_WINDOW_DAYS` (30
  días desde la fecha local de la venta, inclusive; sin excepciones por permiso). Cualquier producto admite cambio (no hay
  `allows_exchange`: lo que no se cambie es regla de negocio fuera del sistema). Se devuelven ítems de ESA venta (`sale_item` +
  cantidad, hasta `quantity − exchanged_quantity`; cambios parciales y sucesivos) y se lleva cualquier variante activa (puede
  no llevarse nada), nunca la misma variante que devuelve. Valuación: lo devuelto vale lo que el cliente **pagó** (`unit_price`
  de la venta, con su descuento); lo nuevo, el precio vigente hoy **sin descuento**. `difference = nuevo − devuelto`.
  **No hay devoluciones de dinero**: `difference > 0` la paga el cliente (`payment_method` obligatorio); `0` o negativa no hay
  pago (un `payment_method` enviado se ignora) y el valor no compensado queda en `unreturned_amount` (propiedad). Lo que se lleva
  de un cambio no se vuelve a cambiar. Atómico: dos operaciones de stock enlazadas al cambio (ingreso `cambio_entrada` y egreso
  `cambio_salida`); si falta stock de lo nuevo no queda nada. `void_exchange` deshace ambas y libera las unidades; falla (400) si
  lo que había entrado ya se vendió. `POST exchanges/preview/` calcula `returned_total`, `new_total`, `difference` y
  `unreturned_amount` sin guardar nada (mismas validaciones, y avisa si no hay stock de lo que se lleva).
  Endpoints: `sales/` (listar/ver/crear, `POST {id}/void/`), `exchanges/` (listar/ver/crear, `POST preview/`, `POST {id}/void/`).
  `GET sales/{id}/` trae `items` (con `exchangeable_quantity`), `exchanges` (resumen) y `can_exchange` (completada, en plazo y con
  unidades por cambiar); el listado trae `items_count`/`units` (subconsultas: el buscador por SKU no los multiplica) y
  `exchange_deadline`. Filtros de ventas: `client`, `status`, `payment_method`, `created_by`, `product`, `variant`, `has_discount`,
  `has_exchanges` (sólo cambios activos), `min_total`, `max_total`, `date_from`/`date_to` (inclusivos, hora de Buenos Aires),
  `search` (cliente, nota, SKU). Permisos por acción (`core/permissions.py::ActionPermission`): `view_sale`, `add_sale`,
  `void_sale`, `apply_discount`, `view_exchange`, `add_exchange` (crear y preview), `void_exchange`. Vendedor: ver y crear
  ventas y cambios; Administrador todo (anular y descontar). El admin es de sólo consulta. Guía de API para el front:
  `docs/sales-brief.md` (contratos, pantallas y orden de implementación).

- `core/media.py` — adaptador de almacenamiento de imágenes: `ImageStorage`
  (`upload`/`delete`/`url`) + `CloudinaryImageStorage`, elegido con `settings.IMAGE_STORAGE`
  (ruta de la clase). El dominio sólo habla con `get_image_storage()`; cambiar de proveedor es
  escribir otra subclase y apuntar la setting. `validate_image_upload` valida por contenido
  (JPEG/PNG/WEBP, `IMAGE_MAX_BYTES`). Sin credenciales la API de imágenes responde 503 (errores en
  `core/exceptions.py`). Tests: `core.tests.fakes.FakeImageStorage` (con `override_settings(IMAGE_STORAGE=...)`).
- `ProductImage` (`product-images`): imagen de un producto **en un color** (producto + color
  obligatorios, sin depender del talle ni de que exista la variante); varias por producto-color,
  ordenadas con la principal (`is_primary`) primero y después por `sort_order` (si no llega, al final de esa galería). Una sola principal por producto-color (índice único parcial): al marcarla en el alta o en un PATCH (también al cambiar de color) se desmarca la anterior; la primera subida no queda principal sola y borrar la principal no promueve otra. Se sube por `multipart`
  (`file`, una por request); el backend la envía al proveedor y guarda sólo `storage_key` (de
  lectura; `url`/`thumbnail_url` se arman con el adaptador). El archivo y el producto no cambian
  (se borra y se sube otra); `color`, `alt_text` y `sort_order` sí. `DELETE` borra primero el
  archivo del proveedor (si falla: 502 y no se elimina) y no es restaurable. No se elimina un
  producto ni un color con imágenes activas. `GET products/{id}/with-variants/` trae `images`.
  La grilla `product-variants` trae `image_url`/`thumbnail_url` (la principal del producto en el
  color de la variante o, si no hay, la de menor orden; `null` si no hay; subconsulta anotada, sin consultas por fila).
  El admin es de sólo consulta. Cloudinary: `CLOUDINARY_*`, `IMAGE_FOLDER` (default `char`).

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

`core/viewsets.py` también ofrece `RestoreModelMixin` (opt-in, va antes de
`BaseModelViewSet`): agrega `POST <recurso>/{id}/restore/`, que revierte el soft
delete y exige `change_<modelo>` (`DjangoRestorePermission`). Lo usa `ClientViewSet`.
`Client.email` es obligatorio, único y siempre en minúsculas.

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
`EMAIL_BACKEND`, `TIME_ZONE` (default `America/Argentina/Buenos_Aires`: los filtros de fecha y el plazo de cambio cuentan días locales), `EXCHANGE_WINDOW_DAYS` (30), `NUM_PROXIES` (poné 1 detrás de un proxy/LB, si no el throttling por IP no es confiable), `THROTTLE_RATE_*`, `JWT_*`, `SECURE_*`, `CSRF_TRUSTED_ORIGINS`) are optional overrides. Inside Docker, `DB_HOST` is overridden to `db` so
the same `.env` works both locally and in Compose.

### Seguridad de tokens / docs

Desactivar un usuario o cambiarle la contraseña blacklistea sus refresh tokens
(`users/signals.py`). `/api/schema|docs|redoc/` son públicos sólo con `DEBUG=True`;
en producción exigen staff. `/health/` no tiene throttling y chequea la DB.
Recomendado programar `manage.py flushexpiredtokens`.
