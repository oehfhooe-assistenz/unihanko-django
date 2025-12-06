"""Bootstrap HolidayCalendar from YAML (idempotent)."""
# File: employees/management/commands/bootstrap_holidays.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from pathlib import Path
import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from employees.models import HolidayCalendar

class Command(BaseCommand):
    help = "Create/refresh Holiday Calendar from YAML (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument("--file", "-f", default="config/fixtures/holiday_calendar.yaml")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        path = Path(opts["file"])
        dry = opts["dry_run"]
        if not path.exists():
            raise CommandError(f"YAML file not found: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        calendars_cfg = data.get("calendars", []) or []
        if not calendars_cfg:
            self.stdout.write(self.style.WARNING("No holiday calendars defined."))
            return
        
        created_count = updated_count = unchanged_count = 0
        
        for cal_def in calendars_cfg:
            name = cal_def.get("name")
            is_active = cal_def.get("is_active", False)
            rules_text = cal_def.get("rules", "")
            
            if not name:
                raise CommandError(f"Missing 'name' in: {cal_def}")
            
            try:
                # Check if exists
                existing = HolidayCalendar.objects.filter(name=name).first()
                
                if existing:
                    # Check for updates
                    needs_update = False
                    updates = {}
                    if existing.is_active != is_active:
                        updates['is_active'] = is_active
                        needs_update = True
                    if existing.rules_text != rules_text:
                        updates['rules_text'] = rules_text
                        needs_update = True
                    
                    if needs_update:
                        if dry:
                            self.stdout.write(self.style.NOTICE(f"[DRY] Update: {name}"))
                        else:
                            with transaction.atomic():
                                for field, value in updates.items():
                                    setattr(existing, field, value)
                                existing.full_clean()
                                existing.save()
                                self.stdout.write(self.style.SUCCESS(f"Updated: {name}"))
                        updated_count += 1
                    else:
                        unchanged_count += 1
                else:
                    # New record
                    if dry:
                        self.stdout.write(self.style.NOTICE(f"[DRY] Create: {name}"))
                    else:
                        with transaction.atomic():
                            cal = HolidayCalendar.objects.create(
                                name=name,
                                is_active=is_active,
                                rules_text=rules_text
                            )
                            cal.full_clean()
                            cal.save()
                            self.stdout.write(self.style.SUCCESS(f"Created: {name}"))
                    created_count += 1
                    
            except Exception as e:
                raise CommandError(f"Error processing {name}: {e}")
        
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