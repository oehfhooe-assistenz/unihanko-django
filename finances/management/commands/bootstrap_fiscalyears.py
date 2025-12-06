"""Bootstrap FiscalYear definitions from YAML (idempotent)."""
# File: finances/management/commands/bootstrap_fiscalyears.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from pathlib import Path
from datetime import date
import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from finances.models import FiscalYear

class Command(BaseCommand):
    help = "Create/refresh Fiscal Years from YAML (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument("--file", "-f", default="config/fixtures/fiscal_years.yaml")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        path = Path(opts["file"])
        dry = opts["dry_run"]
        if not path.exists():
            raise CommandError(f"YAML file not found: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        years_cfg = data.get("fiscal_years", []) or []
        if not years_cfg:
            self.stdout.write(self.style.WARNING("No fiscal years defined."))
            return
        
        created_count = updated_count = unchanged_count = 0
        
        for fy_def in years_cfg:
            start = fy_def.get("start")
            label = fy_def.get("label", "")
            is_active = fy_def.get("is_active", False)
            
            if not start:
                raise CommandError(f"Missing 'start' in: {fy_def}")
            
            if isinstance(start, str):
                start = date.fromisoformat(start)
            
            # Generate code from start date
            y1 = start.year % 100
            y2 = (start.year + 1) % 100
            code = f"WJ{y1:02d}_{y2:02d}"
            
            try:
                # Check if exists
                existing = FiscalYear.objects.filter(code=code).first()
                
                if existing:
                    # Check for updates
                    needs_update = False
                    updates = {}
                    if existing.label != label:
                        updates['label'] = label
                        needs_update = True
                    if existing.start != start:
                        updates['start'] = start
                        needs_update = True
                    if existing.is_active != is_active:
                        updates['is_active'] = is_active
                        needs_update = True
                    
                    if needs_update:
                        if dry:
                            self.stdout.write(self.style.NOTICE(f"[DRY] Update: {code}"))
                        else:
                            with transaction.atomic():
                                for field, value in updates.items():
                                    setattr(existing, field, value)
                                existing.save()
                                self.stdout.write(self.style.SUCCESS(f"Updated: {code}"))
                        updated_count += 1
                    else:
                        unchanged_count += 1
                else:
                    # New record
                    if dry:
                        self.stdout.write(self.style.NOTICE(f"[DRY] Create: {code}"))
                    else:
                        with transaction.atomic():
                            fy = FiscalYear.objects.create(
                                code=code,
                                label=label,
                                start=start,
                                is_active=is_active
                            )
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