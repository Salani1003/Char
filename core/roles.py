"""
Definición centralizada de Roles.

Un "Rol" acá es simplemente un `django.contrib.auth.models.Group` con un
conjunto de `Permission` nativos de Django asignados. No existe un modelo
`Role` propio ni un campo `role` en `User`: el rol de un usuario es, ni
más ni menos, a qué Groups pertenece.

Para definir un rol se agrega una entrada a `ROLES`, donde la clave es el
nombre del Group y el valor es la lista de permisos que debe tener,
expresados como `"<app_label>.<codename>"` (el mismo formato que usa
`user.has_perm(...)`). Los permisos `add_<model>`, `change_<model>`,
`delete_<model>` y `view_<model>` de cada modelo los crea Django
automáticamente al correr las migraciones.

Ejemplo (no incluido por default, sólo ilustrativo):

    ROLES = {
        "Editors": [
            "app.view_article",
            "app.add_article",
            "app.change_article",
        ],
        "Viewers": [
            "app.view_article",
        ],
    }

El comando `python manage.py seed_roles` lee este diccionario y crea los
Groups que falten, asignándoles los Permissions definidos.
"""

ROLES: dict[str, list[str]] = {
    "Administrador": [
        "users.add_user",
        "users.view_user",
        "users.change_user",
        "users.delete_user",
        "auth.view_group",
        "clients.add_client",
        "clients.view_client",
        "clients.change_client",
        "clients.delete_client",
        "products.add_category",
        "products.view_category",
        "products.change_category",
        "products.delete_category",
        "products.add_brand",
        "products.view_brand",
        "products.change_brand",
        "products.delete_brand",
        "products.add_productmodel",
        "products.view_productmodel",
        "products.change_productmodel",
        "products.delete_productmodel",
        "products.add_color",
        "products.view_color",
        "products.change_color",
        "products.delete_color",
        "products.add_size",
        "products.view_size",
        "products.change_size",
        "products.delete_size",
        "products.add_product",
        "products.view_product",
        "products.change_product",
        "products.delete_product",
        "products.view_cost_price",
        "products.add_productvariant",
        "products.view_productvariant",
        "products.change_productvariant",
        "products.delete_productvariant",
    ],
    "Vendedor": [
        "clients.add_client",
        "clients.view_client",
        "clients.change_client",
        "products.view_category",
        "products.view_brand",
        "products.view_productmodel",
        "products.view_color",
        "products.view_size",
        "products.view_product",
        "products.view_productvariant",
    ],
}
