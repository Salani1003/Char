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
    "Administrator": [
        "users.add_user",
        "users.view_user",
        "users.change_user",
        "users.delete_user",
        "auth.view_group",
    ],
}
