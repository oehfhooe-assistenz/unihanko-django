"""Bootstrap Semester definitions from YAML (idempotent)."""
# File: academia/management/commands/bootstrap_semesters.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from pathlib import Path
from datetime import date
import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from academia.models import Semester

class Command(BaseCommand):
    help = "Create/refresh Semesters from YAML (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument("--file", "-f", default="config/fixtures/semesters.yaml")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        path = Path(opts["file"])
        dry = opts["dry_run"]
        if not path.exists():
            raise CommandError(f"YAML file not found: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        semesters_cfg = data.get("semesters", []) or []
        if not semesters_cfg:
            self.stdout.write(self.style.WARNING("No semesters defined."))
            return
        
        created_count = updated_count = unchanged_count = 0
        
        for sem_def in semesters_cfg:
            code = sem_def.get("code")
            display_name = sem_def.get("display_name")
            start_date = sem_def.get("start_date")
            end_date = sem_def.get("end_date")
            
            if not code:
                raise CommandError(f"Missing 'code' in: {sem_def}")
            if not display_name:
                raise CommandError(f"Missing 'display_name' in: {sem_def}")
            if not start_date or not end_date:
                raise CommandError(f"Missing dates in: {sem_def}")
            
            if isinstance(start_date, str):
                start_date = date.fromisoformat(start_date)
            if isinstance(end_date, str):
                end_date = date.fromisoformat(end_date)
            
            try:
                # Check if exists
                existing = Semester.objects.filter(code=code).first()
                
                if existing:
                    needs_update = False
                    updates = {}
                    if existing.display_name != display_name:
                        updates['display_name'] = display_name
                        needs_update = True
                    if existing.start_date != start_date:
                        updates['start_date'] = start_date
                        needs_update = True
                    if existing.end_date != end_date:
                        updates['end_date'] = end_date
                        needs_update = True
                    if needs_update:
                        if dry:
                            self.stdout.write(self.style.NOTICE(f"[DRY] Update: {code}"))
                        else:
                            with transaction.atomic():
                                for field, value in updates.items():
                                    setattr(existing, field, value)
                                existing.full_clean()
                                existing.save()
                                self.stdout.write(self.style.SUCCESS(f"Updated: {code}"))
                        updated_count += 1
                    else:
                        unchanged_count += 1
                else:
                    if dry:
                        self.stdout.write(self.style.NOTICE(f"[DRY] Create: {code}"))
                    else:
                        with transaction.atomic():
                            sem = Semester.objects.create(
                                code=code,
                                display_name=display_name,
                                start_date=start_date,
                                end_date=end_date,
                            )
                            sem.full_clean()
                            sem.save()
                            self.stdout.write(self.style.SUCCESS(f"Created: {code}"))
                    created_count += 1
            except Exception as e:
                raise CommandError(f"Error processing {code}: {e}")
        
        summary = []
        if created_count:
            summary.append(f"{created_count} created")
        if updated_count:
            summary.append(f"{updated_count} updated")
        if unchanged_count:
            summary.append(f"{unchanged_count} unchanged")
        if dry:
            self.stdout.write(self.style.WARNING(f"\nDry run. {', '.join(summary)}. No changes applied."))
        else:
            self.stdout.write(self.style.SUCCESS(f"\n✓ Bootstrap complete! {', '.join(summary)}."))