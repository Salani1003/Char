from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from core.roles import ROLES


class Command(BaseCommand):
    help = (
        "Crea (o actualiza) los Groups definidos en core.roles.ROLES y les "
        "asigna los Permissions nativos de Django correspondientes. "
        "Idempotente: correrlo varias veces deja el mismo resultado."
    )

    def handle(self, *args, **options):
        unknown_permissions = []

        for role_name, codenames in ROLES.items():
            group, created = Group.objects.get_or_create(name=role_name)
            if created:
                self.stdout.write(f"Creado Group '{role_name}'")
            else:
                self.stdout.write(f"Group '{role_name}' ya existía")

            permissions = []
            for codename in codenames:
                try:
                    app_label, perm_codename = codename.split(".", 1)
                except ValueError:
                    unknown_permissions.append(codename)
                    self.stderr.write(
                        self.style.WARNING(
                            f"Permiso mal formado '{codename}' (se esperaba "
                            "'<app_label>.<codename>'), ignorado"
                        )
                    )
                    continue

                try:
                    permission = Permission.objects.get(
                        content_type__app_label=app_label, codename=perm_codename
                    )
                except Permission.DoesNotExist:
                    unknown_permissions.append(codename)
                    self.stderr.write(
                        self.style.WARNING(
                            f"Permiso '{codename}' no existe, ignorado"
                        )
                    )
                    continue

                permissions.append(permission)

            group.permissions.set(permissions)
            self.stdout.write(
                f"  -> {len(permissions)} permiso(s) asignado(s) a '{role_name}'"
            )

        if unknown_permissions:
            self.stderr.write(
                self.style.ERROR(
                    f"{len(unknown_permissions)} permiso(s) definido(s) en "
                    "ROLES no existen y fueron ignorados: "
                    f"{', '.join(unknown_permissions)}"
                )
            )

        self.stdout.write(self.style.SUCCESS("seed_roles finalizado"))
