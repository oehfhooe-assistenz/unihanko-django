"""Bootstrap HolidayCalendar from YAML (idempotent)."""
# File: employees/management/commands/bootstrap_holidays.py
# Version: 1.0.2
# Author: vas
# Modified: 2025-12-06

from pathlib import Path
import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from employees.models import HolidayCalendar
from django.conf import settings

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
    help = "Create/refresh Holiday Calendar from YAML (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file", "-f",
            default=None,
            help="Path to YAML file (default: auto-resolved from fixtures)"
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        file_path = opts["file"]
        if not file_path:
            file_path = get_fixture_path("holiday_calendar.yaml", sensitive=False)
        else:
            file_path = Path(file_path)
        
        dry = opts["dry_run"]
        
        if not file_path.exists():
            raise CommandError(f"YAML file not found: {file_path}")
        
        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
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