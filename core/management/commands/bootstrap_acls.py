# core/management/commands/bootstrap_acls.py
"""
Sync Django Groups & Permissions from a YAML file (idempotent).

Usage:
  python manage.py bootstrap_acls --dry-run
  python manage.py bootstrap_acls
  python manage.py bootstrap_acls --file config/access.yaml
"""
from pathlib import Path
from typing import Dict, List, Set

import yaml
from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError

PERM_KINDS = {"view", "add", "change", "delete"}


def get_model(label: str):
    """
    'people.Person' -> model class
    """
    try:
        app_label, model_name = label.split(".", 1)
    except ValueError:
        raise CommandError(f"Invalid model label '{label}'. Use 'app_label.ModelName'.")
    model = apps.get_model(app_label, model_name)
    if not model:
        raise CommandError(f"Model not found: {label}")
    return model


def perms_for_model(model, kinds: List[str]) -> List[Permission]:
    """
    Map ['view','add','change'] -> Permission objects for given model.
    """
    ct = ContentType.objects.get_for_model(model)
    out: List[Permission] = []
    for k in kinds:
        if k not in PERM_KINDS:
            raise CommandError(f"Unknown perm kind '{k}' for model {model._meta.label}.")
        codename = f"{k}_{model._meta.model_name}"
        try:
            out.append(Permission.objects.get(codename=codename, content_type=ct))
        except Permission.DoesNotExist:
            raise CommandError(
                f"Permission {ct.app_label}.{codename} does not exist. "
                f"Did you run migrations?"
            )
    return out


def custom_perms_for_model(model, codes: List[str]) -> List[Permission]:
    """
    Fetch custom permissions defined on a model (Meta.permissions).
    """
    ct = ContentType.objects.get_for_model(model)
    out: List[Permission] = []
    for code in codes or []:
        try:
            out.append(Permission.objects.get(codename=code, content_type=ct))
        except Permission.DoesNotExist:
            raise CommandError(
                f"Custom permission {ct.app_label}.{code} not found for model {model._meta.label}. "
                f"Define it in Meta.permissions and migrate."
            )
    return out


class Command(BaseCommand):
    help = "Create/refresh Django Groups & Permissions from a YAML file (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            "-f",
            default="config/access.yaml",
            help="Path to YAML config (default: config/access.yaml)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show planned changes without applying them.",
        )

    def handle(self, *args, **opts):
        path = Path(opts["file"])
        dry = opts["dry_run"]

        if not path.exists():
            raise CommandError(f"YAML file not found: {path}")

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        groups_cfg: Dict = data.get("groups", {}) or {}

        if not groups_cfg:
            self.stdout.write(self.style.WARNING("No groups defined. Nothing to do."))
            return

        resolved_perms: Dict[str, Set[Permission]] = {}

        def resolve_group(name: str, stack=None) -> Set[Permission]:
            stack = stack or []
            if name in resolved_perms:
                return resolved_perms[name]
            if name in stack:
                raise CommandError(f"Circular inheritance: {' > '.join(stack + [name])}")

            cfg = groups_cfg.get(name)
            if cfg is None:
                raise CommandError(f"Group '{name}' referenced but not defined.")

            perms: Set[Permission] = set()

            # Inherit first
            for parent in (cfg.get("inherits") or []):
                perms |= resolve_group(parent, stack + [name])

            # Model perms
            for model_label, kinds in (cfg.get("models") or {}).items():
                model = get_model(model_label)
                perms |= set(perms_for_model(model, kinds))

            # Custom perms per model
            for model_label, codes in (cfg.get("custom_perms") or {}).items():
                model = get_model(model_label)
                perms |= set(custom_perms_for_model(model, codes))

            resolved_perms[name] = perms
            return perms

        # Build all permission sets
        for gname in groups_cfg.keys():
            resolve_group(gname)

        # Apply to DB (exact sync)
        for gname, perms_set in resolved_perms.items():
            group, created = Group.objects.get_or_create(name=gname)
            current = set(group.permissions.all())

            add = perms_set - current
            remove = current - perms_set

            if dry:
                if created:
                    self.stdout.write(self.style.NOTICE(f"[DRY] Create group: {gname}"))
                if add:
                    self.stdout.write(self.style.NOTICE(f"[DRY] Grant -> {gname}: "
                                                        f"{', '.join(sorted(p.codename for p in add))}"))
                if remove:
                    self.stdout.write(self.style.NOTICE(f"[DRY] Revoke -> {gname}: "
                                                        f"{', '.join(sorted(p.codename for p in remove))}"))
            else:
                group.permissions.set(list(perms_set))
                self.stdout.write(self.style.SUCCESS(f"Synced group: {gname} ({len(perms_set)} perms)"))

        if dry:
            self.stdout.write(self.style.WARNING("Dry run complete. No changes applied."))
