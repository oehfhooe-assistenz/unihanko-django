"""
Bootstrap RoleTransitionReason definitions from YAML (idempotent).

Usage:
  python manage.py bootstrap_reasons --dry-run
  python manage.py bootstrap_reasons
  python manage.py bootstrap_reasons --file /custom/reasons.yaml
"""
# File: people/management/commands/bootstrap_reasons.py
# Version: 1.0.2
# Author: vas
# Modified: 2025-12-06

from pathlib import Path
from typing import Dict, List

import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.conf import settings
from people.models import RoleTransitionReason

def get_fixture_path(filename, *, sensitive=False):
    """
    Resolve fixture file location.
    
    - Non-sensitive: always from repo fixtures/
    - Sensitive: from mount in prod, repo in DEBUG
    """
    if sensitive and not settings.DEBUG:
        # Production: sensitive files ONLY from mount
        return settings.BOOTSTRAP_DATA_DIR / filename
    else:
        # Dev OR non-sensitive: use repo fixtures
        return Path(__file__).parent.parent.parent / "fixtures" / filename

class Command(BaseCommand):
    help = "Create/refresh Role Transition Reasons from YAML (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            "-f",
            default=None,
            help="Path to YAML file (default: auto-resolved from fixtures)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show planned changes without applying them",
        )

    def handle(self, *args, **opts):
        file_path = opts["file"]
        if not file_path:
            file_path = get_fixture_path("transition_reasons.yaml", sensitive=False)
        else:
            file_path = Path(file_path)
        
        dry = opts["dry_run"]

        if not file_path.exists():
            raise CommandError(f"YAML file not found: {file_path}")

        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        reasons_cfg: List[Dict] = data.get("reasons", []) or []

        if not reasons_cfg:
            self.stdout.write(self.style.WARNING("No reasons defined. Nothing to do."))
            return

        created_count = 0
        updated_count = 0
        unchanged_count = 0

        for reason_def in reasons_cfg:
            code = reason_def.get("code")
            name = reason_def.get("name")
            name_en = reason_def.get("name_en", "")
            active = reason_def.get("active", True)

            if not code:
                raise CommandError(f"Missing 'code' in reason definition: {reason_def}")
            if not name:
                raise CommandError(f"Missing 'name' in reason definition: {reason_def}")

            try:
                # Check if exists
                existing = RoleTransitionReason.objects.filter(code=code).first()
                
                if existing:
                    # Check if update needed
                    needs_update = False
                    updates = {}

                    if existing.name != name:
                        updates['name'] = name
                        needs_update = True
                    if existing.name_en != name_en:
                        updates['name_en'] = name_en
                        needs_update = True
                    if existing.active != active:
                        updates['active'] = active
                        needs_update = True

                    if needs_update:
                        if dry:
                            self.stdout.write(
                                self.style.NOTICE(
                                    f"[DRY] Update: {code} | Changes: {', '.join(updates.keys())}"
                                )
                            )
                        else:
                            with transaction.atomic():
                                for field, value in updates.items():
                                    setattr(existing, field, value)
                                existing.full_clean()
                                existing.save()
                                self.stdout.write(self.style.SUCCESS(f"Updated: {code} — {name}"))
                        updated_count += 1
                    else:
                        unchanged_count += 1
                else:
                    if dry:
                        self.stdout.write(self.style.NOTICE(f"[DRY] Create: {code} — {name}"))
                    else:
                        with transaction.atomic():
                            reason = RoleTransitionReason.objects.create(
                                code=code,
                                name=name,
                                name_en=name_en,
                                active=active,
                            )
                            reason.full_clean()
                            reason.save()
                            self.stdout.write(self.style.SUCCESS(f"Created: {code} — {name}"))
                    created_count += 1
                        
            except Exception as e:
                raise CommandError(f"Error processing reason '{code}': {e}")

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