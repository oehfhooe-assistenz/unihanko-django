"""
Bootstrap Assembly Term definitions from YAML (idempotent).

Usage:
  python manage.py bootstrap_terms --dry-run
  python manage.py bootstrap_terms
  python manage.py bootstrap_terms --file config/terms.yaml
"""
# File: assembly/management/commands/bootstrap_terms.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from pathlib import Path
from typing import Dict, List
from datetime import date

import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from assembly.models import Term


class Command(BaseCommand):
    help = "Create/refresh Assembly Terms from YAML (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            "-f",
            default="config/terms.yaml",
            help="Path to YAML config (default: config/fixtures/terms.yaml)",
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
        terms_cfg: List[Dict] = data.get("terms", []) or []

        if not terms_cfg:
            self.stdout.write(self.style.WARNING("No terms defined. Nothing to do."))
            return

        created_count = 0
        updated_count = 0
        unchanged_count = 0

        for term_def in terms_cfg:
            label = term_def.get("label")
            start_date = term_def.get("start_date")
            end_date = term_def.get("end_date")
            is_active = term_def.get("is_active", False)

            if not label:
                raise CommandError(f"Missing 'label' in term definition: {term_def}")
            if not start_date:
                raise CommandError(f"Missing 'start_date' in term definition: {term_def}")

            # Parse dates
            if isinstance(start_date, str):
                start_date = date.fromisoformat(start_date)
            if isinstance(end_date, str):
                end_date = date.fromisoformat(end_date)

            # Generate code
            y1 = start_date.year % 100
            y2 = (start_date.year + 2) % 100 if not end_date else end_date.year % 100
            code = f"HV{y1:02d}_{y2:02d}"

            try:
                # Check if exists
                existing = Term.objects.filter(code=code).first()
                
                if existing:
                    # Check if update needed
                    needs_update = False
                    updates = {}

                    if existing.label != label:
                        updates['label'] = label
                        needs_update = True
                    if existing.start_date != start_date:
                        updates['start_date'] = start_date
                        needs_update = True
                    if existing.end_date != end_date:
                        updates['end_date'] = end_date
                        needs_update = True
                    if existing.is_active != is_active:
                        updates['is_active'] = is_active
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
                                existing.full_clean()  # Validate
                                existing.save()
                                self.stdout.write(self.style.SUCCESS(f"Updated: {code} — {label}"))
                        updated_count += 1
                    else:
                        unchanged_count += 1
                else:
                    # New record
                    if dry:
                        self.stdout.write(self.style.NOTICE(f"[DRY] Create: {code} — {label}"))
                    else:
                        with transaction.atomic():
                            term = Term.objects.create(
                                code=code,
                                label=label,
                                start_date=start_date,
                                end_date=end_date,
                                is_active=is_active,
                            )
                            term.full_clean()  # Validate
                            term.save()
                            self.stdout.write(self.style.SUCCESS(f"Created: {code} — {label}"))
                    created_count += 1
                        
            except Exception as e:
                raise CommandError(f"Error processing term '{code}': {e}")

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