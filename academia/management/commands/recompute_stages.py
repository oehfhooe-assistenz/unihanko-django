# File: academia/management/commands/recompute_stages.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.core.management.base import BaseCommand
from academia.models import InboxRequest, inboxrequest_stage

class Command(BaseCommand):
    help = 'Recompute stage field for all InboxRequest objects from HankoSign signatures'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without saving',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        count = 0
        unchanged = 0
        
        for ir in InboxRequest.objects.all():
            old_stage = ir.stage
            new_stage = inboxrequest_stage(ir)
            
            if old_stage != new_stage:
                if dry_run:
                    self.stdout.write(
                        self.style.WARNING(
                            f"[DRY RUN] {ir.reference_code}: {old_stage} → {new_stage}"
                        )
                    )
                else:
                    ir.stage = new_stage
                    ir.save(update_fields=['stage'])
                    self.stdout.write(
                        f"Updated {ir.reference_code}: {old_stage} → {new_stage}"
                    )
                count += 1
            else:
                unchanged += 1
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'\n[DRY RUN] Would update {count} records, {unchanged} already correct'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nSuccessfully updated {count} records, {unchanged} already correct'
                )
            )