"""
Django management command to add/update version headers in Python files.

Adds standardized comment headers with file path, version, author, and modification date.
Supports dry-run mode and detects existing file path comments.

SAFETY FEATURES:
- Only searches/modifies the first 20 lines of files
- Automatically SKIPS all migration files (*/migrations/*)
- Prevents accidentally matching patterns in code deeper in files

Usage:
    # Add version header with author
    python manage.py version_python core/models.py --author vas
    
    # Dry run (preview only)
    python manage.py version_python core/models.py --dry-run
    
    # Update existing header (auto-increments version)
    python manage.py version_python core/models.py
    
    # Batch update all Python files in directory (migrations auto-excluded)
    python manage.py version_python core/ --author vas
    
    # Set custom initial version
    python manage.py version_python core/models.py --set-version 2.5.0
"""

# File: core/management/commands/version_python.py
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
    help = 'Add or update version headers in Python files'

    def add_arguments(self, parser):
        parser.add_argument(
            'path',
            type=str,
            help='Path to Python file or directory (relative to project root)',
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
            help='Force re-version even if file has recent version header',
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
            if path.suffix == '.py':
                self.process_file(path)
            else:
                self.stdout.write(self.style.WARNING(f'Skipping non-Python file: {path}'))
        elif path.is_dir():
            py_files = list(path.rglob('*.py'))
            
            # Filter out migration files
            py_files = [f for f in py_files if '/migrations/' not in str(f).replace('\\', '/')]
            
            if not py_files:
                self.stdout.write(self.style.WARNING(f'No .py files found in: {path} (migrations excluded)'))
                return
            
            self.stdout.write(f'Found {len(py_files)} Python files (excluding migrations)\n')
            for py_file in py_files:
                self.process_file(py_file)
        else:
            self.stdout.write(self.style.ERROR(f'Invalid path: {path}'))

    def process_file(self, file_path):
        """Process a single Python file."""
        # SAFETY: Skip migration files entirely
        if '/migrations/' in str(file_path).replace('\\', '/'):
            self.stdout.write(self.style.WARNING(f'⊘ Skipping migration file: {file_path.name}'))
            return
        
        rel_path = file_path.relative_to(settings.BASE_DIR)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check for existing version header
        existing_header = self.extract_existing_header(content)
        
        # Determine file path comment (use existing or generate from relative path)
        existing_file_comment = self.extract_file_comment(content)
        file_path_str = existing_file_comment or str(rel_path).replace('\\', '/')
        
        if existing_header and not self.force:
            action = 'UPDATE'
            new_version = self.increment_version(existing_header['version'])
            old_author = existing_header.get('author', self.author)
            
            # Keep existing author if not explicitly changed
            if self.author == 'UniHanko Dev' and old_author != 'UniHanko Dev':
                author_to_use = old_author
            else:
                author_to_use = self.author
        else:
            action = 'ADD'
            new_version = self.version or '1.0.0'
            author_to_use = self.author

        # Override version if explicitly provided
        if self.version:
            new_version = self.version

        # Generate new header
        new_header = self.generate_header(
            file_path=file_path_str,
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
        """Extract existing version header from Python file.
        
        SAFETY: Only searches first 20 lines to avoid accidentally matching
        patterns in code/comments/strings deeper in the file.
        """
        lines = content.split('\n')
        top_section = '\n'.join(lines[:20])  # Only search first 20 lines
        
        # Match comment block with File/Version/Author/Modified
        pattern = r'# File:\s*(.+?)\n# Version:\s*(.+?)\n# Author:\s*(.+?)\n# Modified:\s*(.+?)(?:\n|$)'
        match = re.search(pattern, top_section)
        
        if not match:
            return None

        return {
            'file': match.group(1).strip(),
            'version': match.group(2).strip(),
            'author': match.group(3).strip(),
            'modified': match.group(4).strip(),
        }

    def extract_file_comment(self, content):
        """Extract existing file path comment like '# models/file.py'."""
        lines = content.split('\n')
        
        # Look in first 10 lines for a file path comment
        for line in lines[:10]:
            stripped = line.strip()
            # Match: # path/to/file.py (but not # File: or # Version: etc.)
            if stripped.startswith('#') and '/' in stripped and ':' not in stripped:
                # Remove leading # and whitespace
                path_comment = stripped.lstrip('#').strip()
                # Basic validation - looks like a file path
                if path_comment.endswith('.py') and not path_comment.startswith('!'):
                    return path_comment
        
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

    def generate_header(self, file_path, version, author):
        """Generate version header comment block."""
        today = datetime.now().strftime('%Y-%m-%d')
        
        header = f'''# File: {file_path}
# Version: {version}
# Author: {author}
# Modified: {today}'''
        return header

    def replace_header(self, content, new_header):
        """Replace existing header with new one.
        
        SAFETY: Only replaces in first 20 lines to avoid accidentally modifying
        code/comments/strings deeper in the file.
        """
        lines = content.split('\n')
        top_section = lines[:20]
        rest_of_file = lines[20:]
        
        # Match and replace only in top section
        top_text = '\n'.join(top_section)
        pattern = r'# File:\s*.+?\n# Version:\s*.+?\n# Author:\s*.+?\n# Modified:\s*.+?(?:\n|$)'
        new_top = re.sub(pattern, new_header + '\n', top_text, count=1)
        
        # Reconstruct file
        return new_top + '\n' + '\n'.join(rest_of_file)

    def add_header(self, content, new_header):
        """Add header to Python file without one."""
        lines = content.split('\n')
        insert_position = 0
        
        # Skip shebang, encoding declarations, and module docstrings
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip shebang
            if line.startswith('#!'):
                insert_position = i + 1
                i += 1
                continue
            
            # Skip encoding declarations
            if line.startswith('#') and ('coding' in line or 'encoding' in line):
                insert_position = i + 1
                i += 1
                continue
            
            # Skip module docstring
            if line.startswith('"""') or line.startswith("'''"):
                # Find end of docstring
                quote = '"""' if line.startswith('"""') else "'''"
                if line.count(quote) >= 2:
                    # Single-line docstring
                    insert_position = i + 1
                    i += 1
                else:
                    # Multi-line docstring
                    i += 1
                    while i < len(lines):
                        if quote in lines[i]:
                            insert_position = i + 1
                            break
                        i += 1
                    i += 1
                continue
            
            # Skip existing file path comment (# path/to/file.py)
            if line.startswith('#') and '/' in line and ':' not in line and line.endswith('.py'):
                insert_position = i + 1
                i += 1
                continue
            
            # Skip empty lines at top
            if not line:
                insert_position = i + 1
                i += 1
                continue
            
            # Found first real content
            break
        
        # Insert header at appropriate position
        if insert_position == 0:
            return new_header + '\n\n' + content
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