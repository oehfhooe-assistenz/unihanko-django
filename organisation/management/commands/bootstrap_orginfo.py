"""
Bootstrap OrgInfo singleton with basic organization data (idempotent).

Only sets names and addresses. Bank details, signatories, and disclaimers
must be configured manually via admin.

Usage:
  python manage.py bootstrap_orginfo --dry-run
  python manage.py bootstrap_orginfo
  python manage.py bootstrap_orginfo --file config/orginfo.yaml
"""
# File: organisation/management/commands/bootstrap_orginfo.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from pathlib import Path
import yaml
from django.core.management.base import BaseCommand, CommandError
from organisation.models import OrgInfo


class Command(BaseCommand):
    help = "Bootstrap OrgInfo singleton with basic organization data (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument("--file", "-f", default="config/fixtures/orginfo.yaml")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        path = Path(opts["file"])
        dry = opts["dry_run"]
        
        if not path.exists():
            raise CommandError(f"YAML file not found: {path}")
        
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        
        if not data:
            self.stdout.write(self.style.WARNING("No organization data defined."))
            return
        
        # Get or create singleton
        org = OrgInfo.get_solo()
        
        # Fields we'll update from YAML
        fields_to_update = [
            'org_name_long_de',
            'org_name_short_de',
            'org_name_long_en',
            'org_name_short_en',
            'uni_name_long_de',
            'uni_name_short_de',
            'uni_name_long_en',
            'uni_name_short_en',
            'org_address',
        ]
        
        # Track changes
        changes = {}
        for field in fields_to_update:
            yaml_value = data.get(field, "")
            current_value = getattr(org, field, "")
            
            if yaml_value != current_value:
                changes[field] = {
                    'old': current_value or "(empty)",
                    'new': yaml_value
                }
        
        if not changes:
            self.stdout.write(self.style.SUCCESS("✓ OrgInfo already up to date"))
            return
        
        # Show changes
        if dry:
            self.stdout.write(self.style.NOTICE("[DRY] Would update OrgInfo:"))
            for field, vals in changes.items():
                self.stdout.write(f"  {field}: {vals['old']} → {vals['new']}")
            self.stdout.write(
                self.style.WARNING(
                    f"\nDry run complete. {len(changes)} fields would be updated."
                )
            )
        else:
            # Apply changes
            for field in fields_to_update:
                setattr(org, field, data.get(field, ""))
            
            org.full_clean()
            org.save()
            
            self.stdout.write(self.style.SUCCESS(f"✓ Updated OrgInfo ({len(changes)} fields changed)"))
            for field in changes.keys():
                self.stdout.write(f"  ✓ {field}")