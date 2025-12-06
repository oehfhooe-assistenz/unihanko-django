# File: people/management/commands/bootstrap_people.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-12-05

from django.core.management.base import BaseCommand
from django.db import transaction
from people.models import Person
import yaml
from pathlib import Path


class Command(BaseCommand):
    help = 'Bootstrap people from YAML file'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default='config/fixtures/people.yaml',
            help='Path to YAML file (default: config/fixtures/people.yaml)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without saving to database'
        )
    
    def handle(self, *args, **options):
        file_path = options['file']
        dry_run = options['dry_run']
        
        # Check file exists
        if not Path(file_path).exists():
            self.stdout.write(self.style.ERROR(f'File not found: {file_path}'))
            return
        
        # Load YAML
        with open(file_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        # Validate structure
        if 'records' not in data:
            self.stdout.write(self.style.ERROR('YAML file must contain "records" key'))
            return
        
        # Get dedup config (default to matric_no, email if not specified)
        dedup_fields = data.get('dedup', ['matric_no', 'email'])
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No changes will be saved'))
            self.stdout.write(f'Dedup strategy: {", ".join(dedup_fields)}\n')
        
        created_count = 0
        skipped_count = 0
        
        for idx, person_data in enumerate(data['records'], start=1):
            try:
                # Check for existing person using dedup strategy
                existing = self.find_existing(person_data, dedup_fields)
                
                if existing:
                    self.stdout.write(
                        f'  #{idx}: Skipped - {person_data.get("first_name")} {person_data.get("last_name")} '
                        f'(already exists: {existing})'
                    )
                    skipped_count += 1
                    continue
                
                # Create person (only if not dry-run)
                if not dry_run:
                    with transaction.atomic():
                        person = Person.objects.create(**person_data)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'  #{idx}: Created - {person.first_name} {person.last_name}'
                        )
                    )
                else:
                    self.stdout.write(
                        f'  #{idx}: Would create - {person_data.get("first_name")} {person_data.get("last_name")}'
                    )
                
                created_count += 1
                
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'  #{idx}: Error - {person_data.get("first_name", "?")} '
                        f'{person_data.get("last_name", "?")}: {e}'
                    )
                )
        
        # Summary
        self.stdout.write('\n' + '='*60)
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN SUMMARY'))
        else:
            self.stdout.write(self.style.SUCCESS('IMPORT COMPLETE'))
        self.stdout.write('='*60)
        self.stdout.write(f'Created: {created_count}')
        self.stdout.write(f'Skipped: {skipped_count}')
        self.stdout.write(f'Total:   {created_count + skipped_count}')
    
    def find_existing(self, person_data, dedup_fields):
        """
        Check if person already exists using dedup strategy.
        
        Supports:
        - Single field: ['matric_no']
        - Multiple fields (OR): ['matric_no', 'email']
        - Combo fields (AND): ['first_name+last_name+email']
        """
        for dedup_field in dedup_fields:
            if '+' in dedup_field:
                # Combo field (AND logic)
                fields = dedup_field.split('+')
                filter_kwargs = {}
                
                for field in fields:
                    value = person_data.get(field)
                    if value:
                        filter_kwargs[field] = value
                
                # Only search if we have all required fields
                if len(filter_kwargs) == len(fields):
                    existing = Person.objects.filter(**filter_kwargs).first()
                    if existing:
                        return existing
            else:
                # Single field
                value = person_data.get(dedup_field)
                if value:
                    existing = Person.objects.filter(**{dedup_field: value}).first()
                    if existing:
                        return existing
        
        return None