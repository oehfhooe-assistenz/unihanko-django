# File: people/management/commands/bootstrap_assignments.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-12-05

from django.core.management.base import BaseCommand
from django.db import transaction
from people.models import Person, Role, PersonRole, RoleTransitionReason
import yaml
from pathlib import Path


class Command(BaseCommand):
    help = 'Bootstrap assignments (PersonRole) from YAML file with FK lookups'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default='people/fixtures/assignments.yaml',
            help='Path to YAML file (default: people/fixtures/assignments.yaml)'
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
        
        # Get dedup config
        dedup_fields = data.get('dedup', ['person', 'role', 'start_date'])
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No changes will be saved'))
            self.stdout.write(f'Dedup strategy: {", ".join(dedup_fields)}\n')
        
        created_count = 0
        skipped_count = 0
        error_count = 0
        
        for idx, assignment_data in enumerate(data['records'], start=1):
            try:
                # Resolve FKs
                resolved_data = {}
                
                # Required: Person
                if 'person' in assignment_data:
                    person = self.resolve_fk(Person, assignment_data['person'])
                    if not person:
                        self.stdout.write(
                            self.style.ERROR(
                                f'  #{idx}: Error - Could not find Person with {assignment_data["person"]}'
                            )
                        )
                        error_count += 1
                        continue
                    resolved_data['person'] = person
                else:
                    self.stdout.write(self.style.ERROR(f'  #{idx}: Error - Missing required field "person"'))
                    error_count += 1
                    continue
                
                # Required: Role
                if 'role' in assignment_data:
                    role = self.resolve_fk(Role, assignment_data['role'])
                    if not role:
                        self.stdout.write(
                            self.style.ERROR(
                                f'  #{idx}: Error - Could not find Role with {assignment_data["role"]}'
                            )
                        )
                        error_count += 1
                        continue
                    resolved_data['role'] = role
                else:
                    self.stdout.write(self.style.ERROR(f'  #{idx}: Error - Missing required field "role"'))
                    error_count += 1
                    continue
                
                # Optional: start_reason
                if 'start_reason' in assignment_data:
                    start_reason = self.resolve_fk(RoleTransitionReason, assignment_data['start_reason'])
                    if not start_reason:
                        self.stdout.write(
                            self.style.WARNING(
                                f'  #{idx}: Warning - Could not find start_reason with {assignment_data["start_reason"]}, skipping'
                            )
                        )
                    else:
                        resolved_data['start_reason'] = start_reason
                
                # Optional: end_reason
                if 'end_reason' in assignment_data:
                    end_reason = self.resolve_fk(RoleTransitionReason, assignment_data['end_reason'])
                    if not end_reason:
                        self.stdout.write(
                            self.style.WARNING(
                                f'  #{idx}: Warning - Could not find end_reason with {assignment_data["end_reason"]}, skipping'
                            )
                        )
                    else:
                        resolved_data['end_reason'] = end_reason
                
                # Copy direct fields (dates, notes, etc.)
                for field in ['start_date', 'end_date', 'effective_start', 'effective_end', 
                             'confirm_date', 'notes']:
                    if field in assignment_data:
                        resolved_data[field] = assignment_data[field]
                
                # Check for existing (dedup)
                existing = self.find_existing(resolved_data, dedup_fields)
                
                if existing:
                    self.stdout.write(
                        f'  #{idx}: Skipped - {person} → {role} from {resolved_data.get("start_date")} '
                        f'(already exists)'
                    )
                    skipped_count += 1
                    continue
                
                # Create assignment (only if not dry-run)
                if not dry_run:
                    with transaction.atomic():
                        assignment = PersonRole.objects.create(**resolved_data)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'  #{idx}: Created - {person} → {role} from {resolved_data.get("start_date")}'
                        )
                    )
                else:
                    self.stdout.write(
                        f'  #{idx}: Would create - {person} → {role} from {resolved_data.get("start_date")}'
                    )
                
                created_count += 1
                
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'  #{idx}: Error - {e}')
                )
                error_count += 1
        
        # Summary
        self.stdout.write('\n' + '='*60)
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN SUMMARY'))
        else:
            self.stdout.write(self.style.SUCCESS('IMPORT COMPLETE'))
        self.stdout.write('='*60)
        self.stdout.write(f'Created: {created_count}')
        self.stdout.write(f'Skipped: {skipped_count}')
        self.stdout.write(f'Errors:  {error_count}')
        self.stdout.write(f'Total:   {created_count + skipped_count + error_count}')
    
    def resolve_fk(self, model_class, lookup_dict):
        """
        Generic FK resolver.
        
        Args:
            model_class: Django model (e.g., Person, Role)
            lookup_dict: Dict of fields to lookup (e.g., {matric_no: "s123456"})
        
        Returns:
            Model instance if found, None otherwise
        """
        if not lookup_dict:
            return None
        
        return model_class.objects.filter(**lookup_dict).first()
    
    def find_existing(self, resolved_data, dedup_fields):
        """
        Check if assignment already exists using dedup strategy.
        
        Args:
            resolved_data: Dict with resolved FK objects
            dedup_fields: List of field names to check (e.g., ['person', 'role', 'start_date'])
        
        Returns:
            PersonRole instance if found, None otherwise
        """
        filter_kwargs = {}
        
        for field in dedup_fields:
            if field in resolved_data:
                filter_kwargs[field] = resolved_data[field]
        
        if not filter_kwargs:
            return None
        
        return PersonRole.objects.filter(**filter_kwargs).first()