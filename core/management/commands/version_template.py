"""
Django management command to add/update version headers in HTML templates.

Adds standardized HTML comment headers with version, author, and modification date.
Supports dry-run mode to preview changes before applying.

Usage:
    # Add version header with author
    python manage.py version_template templates/portal/home.html --author vas
    
    # Dry run (preview only)
    python manage.py version_template templates/portal/home.html --dry-run
    
    # Update existing header (auto-increments version)
    python manage.py version_template templates/portal/home.html
    
    # Batch update all templates in directory
    python manage.py version_template templates/portal/ --author vas
    
    # Set custom initial version
    python manage.py version_template templates/portal/home.html --set-version 2.5.0
"""

# File: core/management/commands/version_template.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

import os
import re
from pathlib import Path
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Add or update version headers in Django templates'

    def add_arguments(self, parser):
        parser.add_argument(
            'path',
            type=str,
            help='Path to template file or directory (relative to project root)',
        )
        parser.add_argument(
            '--author',
            type=str,
            default='UniHanko Dev',
            help='Author name/initials (default: UniHanko Dev)',
        )
        parser.add_argument(
            '--set-version',
            type=str,
            help='Specific version to set (default: auto-increment or 1.0.0)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without modifying files',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force re-version even if template has recent version header',
        )

    def handle(self, *args, **options):
        self.author = options['author']
        self.version = options['set_version']
        self.dry_run = options['dry_run']
        self.force = options['force']
        
        path = Path(settings.BASE_DIR) / options['path']
        
        if not path.exists():
            self.stdout.write(self.style.ERROR(f'Path not found: {path}'))
            return

        if self.dry_run:
            self.stdout.write(self.style.WARNING('🔍 DRY RUN MODE - No files will be modified\n'))

        if path.is_file():
            self.process_file(path)
        elif path.is_dir():
            template_files = list(path.rglob('*.html'))
            if not template_files:
                self.stdout.write(self.style.WARNING(f'No .html files found in: {path}'))
                return
            
            self.stdout.write(f'Found {len(template_files)} template files\n')
            for template_file in template_files:
                self.process_file(template_file)
        else:
            self.stdout.write(self.style.ERROR(f'Invalid path: {path}'))

    def process_file(self, file_path):
        """Process a single template file."""
        rel_path = file_path.relative_to(settings.BASE_DIR)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check for existing version header
        existing_header = self.extract_existing_header(content)
        
        if existing_header and not self.force:
            action = 'UPDATE'
            new_version = self.increment_version(existing_header['version'])
            template_name = existing_header['template']
            old_author = existing_header.get('author', self.author)
            
            # Keep existing author if not explicitly changed
            if self.author == 'UniHanko Dev' and old_author != 'UniHanko Dev':
                author_to_use = old_author
            else:
                author_to_use = self.author
        else:
            action = 'ADD'
            new_version = self.version or '1.0.0'
            template_name = file_path.name
            author_to_use = self.author

        # Override version if explicitly provided
        if self.version:
            new_version = self.version

        # Generate new header
        new_header = self.generate_header(
            template_name=template_name,
            version=new_version,
            author=author_to_use
        )

        # Replace or add header
        if existing_header:
            new_content = self.replace_header(content, new_header)
        else:
            new_content = self.add_header(content, new_header)

        # Show changes
        self.show_diff(file_path, rel_path, action, existing_header, new_header)

        # Write changes (unless dry run)
        if not self.dry_run:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            self.stdout.write(self.style.SUCCESS(f'  ✓ File updated\n'))
        else:
            self.stdout.write(self.style.WARNING(f'  ⊘ Dry run - no changes made\n'))

    def extract_existing_header(self, content):
        """Extract existing version header from template."""
        # Match HTML comment block with Template/Version/Author/Modified
        # Don't require it at start of file (^ removed) since Django tags come first
        pattern = r'<!--\s*\nTemplate:\s*.+?\nVersion:\s*.+?\n.*?\n-->'
        match = re.search(pattern, content, re.DOTALL)
        
        if not match:
            return None

        header_text = match.group(0)
        
        # Extract fields
        template_match = re.search(r'Template:\s*(.+?)(?:\n|$)', header_text)
        version_match = re.search(r'Version:\s*(.+?)(?:\n|$)', header_text)
        author_match = re.search(r'Author:\s*(.+?)(?:\n|$)', header_text)
        modified_match = re.search(r'Modified:\s*(.+?)(?:\n|$)', header_text)

        if template_match and version_match:
            return {
                'template': template_match.group(1).strip(),
                'version': version_match.group(1).strip(),
                'author': author_match.group(1).strip() if author_match else None,
                'modified': modified_match.group(1).strip() if modified_match else None,
            }
        
        return None

    def increment_version(self, current_version):
        """Increment patch version number."""
        try:
            parts = current_version.split('.')
            if len(parts) == 3:
                major, minor, patch = parts
                new_patch = int(patch) + 1
                return f'{major}.{minor}.{new_patch}'
            else:
                return '1.0.1'
        except (ValueError, IndexError):
            return '1.0.1'

    def generate_header(self, template_name, version, author):
        """Generate version header HTML comment."""
        today = datetime.now().strftime('%Y-%m-%d')
        
        header = f'''<!--
Template: {template_name}
Version: {version}
Author: {author}
Modified: {today}
-->'''
        return header

    def replace_header(self, content, new_header):
        """Replace existing header with new one."""
        # Match the version header comment block anywhere in file
        pattern = r'<!--\s*\nTemplate:\s*.+?\nVersion:\s*.+?\n.*?\n-->'
        return re.sub(pattern, new_header, content, count=1, flags=re.DOTALL)

    def add_header(self, content, new_header):
        """Add header to template without one."""
        # Skip Django template tags/extends at top
        lines = content.split('\n')
        insert_position = 0
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Skip comments, empty lines, and Django tags at top
            if stripped.startswith('{#') or not stripped or stripped.startswith('{% extends') or stripped.startswith('{% load'):
                insert_position = i + 1
            else:
                break
        
        # Insert header at appropriate position
        if insert_position == 0:
            return new_header + '\n' + content
        else:
            return '\n'.join(lines[:insert_position] + [new_header, ''] + lines[insert_position:])

    def show_diff(self, file_path, rel_path, action, old_header, new_header_text):
        """Display changes to be made."""
        self.stdout.write(self.style.MIGRATE_HEADING(f'📄 {rel_path}'))
        self.stdout.write(f'  Action: {action} version header')
        
        if old_header:
            self.stdout.write(f'  Old: v{old_header["version"]} by {old_header.get("author", "?")} ({old_header.get("modified", "?")})')
        
        # Extract new version from header
        new_version_match = re.search(r'Version:\s*(.+)', new_header_text)
        new_author_match = re.search(r'Author:\s*(.+)', new_header_text)
        new_date_match = re.search(r'Modified:\s*(.+)', new_header_text)
        
        if new_version_match:
            new_version = new_version_match.group(1).strip()
            new_author = new_author_match.group(1).strip() if new_author_match else '?'
            new_date = new_date_match.group(1).strip() if new_date_match else '?'
            self.stdout.write(self.style.SUCCESS(f'  New: v{new_version} by {new_author} ({new_date})'))
        
        # Show preview of header
        if self.dry_run:
            self.stdout.write('\n  Preview:')
            for line in new_header_text.split('\n'):
                self.stdout.write(f'    {line}')
            self.stdout.write('')

    def validate_version_format(self, version):
        """Validate version string format (semantic versioning)."""
        pattern = r'^\d+\.\d+\.\d+$'
        if not re.match(pattern, version):
            self.stdout.write(self.style.WARNING(
                f'⚠ Version "{version}" does not follow semantic versioning (X.Y.Z)'
            ))