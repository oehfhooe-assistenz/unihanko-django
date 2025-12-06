"""
Bootstrap Role definitions from YAML (idempotent).

Usage:
  python manage.py bootstrap_roles --dry-run
  python manage.py bootstrap_roles
  python manage.py bootstrap_roles --file config/roles.yaml
"""
# File: people/management/commands/bootstrap_roles.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from pathlib import Path
from typing import Dict, List
from decimal import Decimal

import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from people.models import Role


class Command(BaseCommand):
    help = "Create/refresh Roles from YAML (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            "-f",
            default="config/fixtures/roles.yaml",
            help="Path to YAML config (default: config/fixtures/roles.yaml)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show planned changes without applying them",
        )

    def handle(self, *args, **opts):
        path = Path(opts["file"])
        dry = opts["dry_run"]

        if not path.exists():
            raise CommandError(f"YAML file not found: {path}")

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        roles_cfg: List[Dict] = data.get("roles", []) or []

        if not roles_cfg:
            self.stdout.write(self.style.WARNING("No roles defined. Nothing to do."))
            return

        created_count = 0
        updated_count = 0
        unchanged_count = 0

        for role_def in roles_cfg:
            name = role_def.get("name")
            short_name = role_def.get("short_name", "")
            ects_cap = Decimal(str(role_def.get("ects_cap", 0)))
            is_elected = role_def.get("is_elected", False)
            kind = role_def.get("kind", "OTHER")
            notes = role_def.get("notes", "")
            is_stipend_reimbursed = role_def.get("is_stipend_reimbursed", False)
            is_system = role_def.get("is_system", False)
            default_monthly_amount = role_def.get("default_monthly_amount")
            
            if default_monthly_amount is not None:
                default_monthly_amount = Decimal(str(default_monthly_amount))

            if not name:
                raise CommandError(f"Missing 'name' in role definition: {role_def}")

            try:
                # Check if exists
                existing = Role.objects.filter(name=name).first()
                
                if existing:
                    # Check if update needed
                    needs_update = False
                    updates = {}

                    if existing.short_name != short_name:
                        updates['short_name'] = short_name
                        needs_update = True
                    if existing.ects_cap != ects_cap:
                        updates['ects_cap'] = ects_cap
                        needs_update = True
                    if existing.is_elected != is_elected:
                        updates['is_elected'] = is_elected
                        needs_update = True
                    if existing.kind != kind:
                        updates['kind'] = kind
                        needs_update = True
                    if existing.notes != notes:
                        updates['notes'] = notes
                        needs_update = True
                    if existing.is_stipend_reimbursed != is_stipend_reimbursed:
                        updates['is_stipend_reimbursed'] = is_stipend_reimbursed
                        needs_update = True
                    if existing.is_system != is_system:
                        updates['is_system'] = is_system
                        needs_update = True
                    if existing.default_monthly_amount != default_monthly_amount:
                        updates['default_monthly_amount'] = default_monthly_amount
                        needs_update = True

                    if needs_update:
                        if dry:
                            self.stdout.write(
                                self.style.NOTICE(
                                    f"[DRY] Update: {name} | Changes: {', '.join(updates.keys())}"
                                )
                            )
                        else:
                            with transaction.atomic():
                                for field, value in updates.items():
                                    setattr(existing, field, value)
                                existing.full_clean()  # Validate
                                existing.save()
                                self.stdout.write(self.style.SUCCESS(f"Updated: {name}"))
                        updated_count += 1
                    else:
                        unchanged_count += 1
                else:
                    if dry:
                        self.stdout.write(self.style.NOTICE(f"[DRY] Create: {name}"))
                    else:
                        with transaction.atomic():
                            role = Role.objects.create(
                                name=name,
                                short_name=short_name,
                                ects_cap=ects_cap,
                                is_elected=is_elected,
                                kind=kind,
                                notes=notes,
                                is_stipend_reimbursed=is_stipend_reimbursed,
                                is_system=is_system,
                                default_monthly_amount=default_monthly_amount,
                            )
                            role.full_clean()  # Validate
                            role.save()
                            self.stdout.write(self.style.SUCCESS(f"Created: {name}"))
                    created_count += 1
                        
            except Exception as e:
                raise CommandError(f"Error processing role '{name}': {e}")

        # Summary
        summary = []
        if created_count:
            summary.append(f"{created_count} created")
        if updated_count:
            summary.append(f"{updated_count} updated")
        if unchanged_count:
            summary.append(f"{unchanged_count} unchanged")

        if dry:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDry run complete. {', '.join(summary)}. No changes applied."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"\n✓ Bootstrap complete! {', '.join(summary)}.")
            )