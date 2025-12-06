"""
Bootstrap HelpPage entries for all relevant ContentTypes (idempotent).

Creates placeholder help pages for models in your app, excluding Django internals.
Use --active to create pages as active by default.

Usage:
  python manage.py bootstrap_helppages --dry-run
  python manage.py bootstrap_helppages
  python manage.py bootstrap_helppages --active
"""
# File: helppages/management/commands/bootstrap_helppages.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from helppages.models import HelpPage


class Command(BaseCommand):
    help = "Create placeholder HelpPage entries for all ContentTypes (idempotent)"
    
    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without actually creating",
        )
        parser.add_argument(
            "--active",
            action="store_true",
            help="Create new help pages as active (default: inactive)",
        )
    
    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        active = opts["active"]
        
        created_count = 0
        existed_count = 0
        skipped_count = 0
        
        # Exclude Django/internal apps
        excluded_apps = [
            'contenttypes',
            'sessions', 
            'admin',
            'auth',
            'simple_history',  # Historical tables
            'concurrency',     # Versioning
        ]
        
        cts = ContentType.objects.exclude(
            app_label__in=excluded_apps
        ).order_by('app_label', 'model')
        
        for ct in cts:
            model_class = ct.model_class()
            
            # Skip if model class not available
            if not model_class:
                skipped_count += 1
                continue
            
            # Skip historical models (usually end with 'historical')
            if ct.model.startswith('historical'):
                skipped_count += 1
                continue
            
            # Check if help page exists
            exists = HelpPage.objects.filter(content_type=ct).exists()
            
            if exists:
                existed_count += 1
                continue
            
            # Create new help page
            if dry:
                self.stdout.write(
                    self.style.NOTICE(
                        f"[DRY] Create: {ct.app_label}.{ct.model} (active={active})"
                    )
                )
            else:
                HelpPage.objects.create(
                    content_type=ct,
                    title_de=f"Hilfe: {model_class._meta.verbose_name_plural}",
                    title_en=f"Help: {model_class._meta.verbose_name_plural}",
                    content_de='-',
                    content_en='-',
                    legend_de='',
                    legend_en='',
                    is_active=active,
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Created: {ct.app_label}.{ct.model}")
                )
            
            created_count += 1
        
        # Summary
        summary = []
        if created_count:
            summary.append(f"{created_count} created")
        if existed_count:
            summary.append(f"{existed_count} already exist")
        if skipped_count:
            summary.append(f"{skipped_count} skipped")
        
        if dry:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDry run complete. {', '.join(summary)}. No changes applied."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✓ Bootstrap complete! {', '.join(summary)}."
                )
            )