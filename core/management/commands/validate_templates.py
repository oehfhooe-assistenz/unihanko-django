"""
Django management command to validate templates for common issues.

Version 2.1 - Enhanced validation with combined tag detection, ignore markers,
and full reporting.

Usage:
    python manage.py validate_templates
    python manage.py validate_templates --portal-only
    python manage.py validate_templates --extract-text
    python manage.py validate_templates --output-report validation_report.md
"""

# File: core/management/commands/validate_templates.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

import os
import re
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Validate Django templates for common issues'

    def add_arguments(self, parser):
        parser.add_argument(
            '--portal-only',
            action='store_true',
            help='Only validate Portal app templates',
        )
        parser.add_argument(
            '--extract-text',
            action='store_true',
            help='Extract text from Portal templates for content review',
        )
        parser.add_argument(
            '--output',
            type=str,
            default='portal_text_extraction.md',
            help='Output file for text extraction (default: portal_text_extraction.md)',
        )
        parser.add_argument(
            '--output-report',
            type=str,
            help='Output full validation report to markdown file',
        )

    def handle(self, *args, **options):
        self.portal_only = options['portal_only']
        self.extract_text = options['extract_text']
        self.output_file = options['output']
        self.output_report = options['output_report']

        # Find templates directory
        templates_dir = Path(settings.BASE_DIR) / 'templates'
        if not templates_dir.exists():
            self.stdout.write(self.style.ERROR(f'Templates directory not found: {templates_dir}'))
            return

        # Collect all template files
        template_files = []
        if self.portal_only:
            portal_dir = templates_dir / 'portal'
            if portal_dir.exists():
                template_files = list(portal_dir.rglob('*.html'))
        else:
            template_files = list(templates_dir.rglob('*.html'))

        if self.extract_text:
            self.extract_portal_text(template_files)
        else:
            self.validate_templates(template_files)

    def validate_templates(self, template_files):
        """Validate templates and report issues."""
        issues = {
            'HIGH': [],
            'MEDIUM': [],
            'LOW': []
        }
        
        stats = {
            'total_files': len(template_files),
            'ignored_files': 0,
            'missing_i18n': 0,
            'missing_static': 0,
            'hardcoded_urls': 0,
            'hardcoded_static': 0,
            'untranslated_strings': 0,
        }

        for template_path in template_files:
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()

            rel_path = template_path.relative_to(template_path.parents[len(template_path.parents) - 3])
            
            # Check for VALIDATOR_IGNORE marker
            if self._is_ignored(content):
                stats['ignored_files'] += 1
                continue

            # HIGH PRIORITY: Missing load tags
            self._check_missing_load_tags(content, rel_path, issues, stats)

            # MEDIUM PRIORITY: Hardcoded URLs and static paths
            self._check_hardcoded_paths(content, rel_path, issues, stats)

            # LOW PRIORITY: Untranslated strings (skip admin templates)
            if 'admin' not in str(rel_path):
                self._check_untranslated_strings(content, rel_path, issues, stats)

        # Output results
        self._print_summary(stats, issues)
        
        # Write to markdown if requested
        if self.output_report:
            self._write_report_to_file(stats, issues)

    def _is_ignored(self, content):
        """Check if template has VALIDATOR_IGNORE marker."""
        return '{# VALIDATOR_IGNORE' in content or '{#VALIDATOR_IGNORE' in content

    def _check_missing_load_tags(self, content, rel_path, issues, stats):
        """Check for missing {% load %} tags."""
        # Check if i18n or static appear in ANY {% load %} statement
        load_lines = [line for line in content.split('\n') if '{% load' in line or '{%load' in line]
        
        has_i18n_load = any('i18n' in line for line in load_lines)
        has_static_load = any('static' in line for line in load_lines)
        
        uses_trans = bool(re.search(r'\{%\s*trans\s+', content))
        uses_static = bool(re.search(r'\{%\s*static\s+', content))

        if uses_trans and not has_i18n_load:
            issues['HIGH'].append({
                'file': str(rel_path),
                'line': None,
                'issue': 'Uses {% trans %} but missing {% load i18n %}',
                'severity': 'HIGH'
            })
            stats['missing_i18n'] += 1

        if uses_static and not has_static_load:
            issues['HIGH'].append({
                'file': str(rel_path),
                'line': None,
                'issue': 'Uses {% static %} but missing {% load static %}',
                'severity': 'HIGH'
            })
            stats['missing_static'] += 1

    def _check_hardcoded_paths(self, content, rel_path, issues, stats):
        """Check for hardcoded URLs and static paths."""
        lines = content.split('\n')

        for i, line in enumerate(lines, 1):
            # Skip lines that already use {% url %} or {% static %}
            if '{%' in line:
                continue

            # Check for hardcoded URLs (excluding static/media/external)
            url_pattern = r'href=["\']/((?!http|#|{)[^"\']+)["\']'
            for match in re.finditer(url_pattern, line):
                url = match.group(1)
                # Skip static/, media/, and admin/ paths
                if not url.startswith(('static/', 'media/', 'admin/')):
                    issues['MEDIUM'].append({
                        'file': str(rel_path),
                        'line': i,
                        'issue': f'Hardcoded URL: /{url} (should use {{% url %}})',
                        'severity': 'MEDIUM'
                    })
                    stats['hardcoded_urls'] += 1

            # Check for hardcoded static paths
            static_pattern = r'(src|href)=["\']/(static/[^"\']+)["\']'
            for match in re.finditer(static_pattern, line):
                path = match.group(2)
                issues['MEDIUM'].append({
                    'file': str(rel_path),
                    'line': i,
                    'issue': f'Hardcoded static path: /{path} (should use {{% static %}})',
                    'severity': 'MEDIUM'
                })
                stats['hardcoded_static'] += 1

    def _check_untranslated_strings(self, content, rel_path, issues, stats):
        """Check for possibly untranslated user-facing strings."""
        lines = content.split('\n')

        # Pattern 1: Single-line tags (buttons, labels, headings)
        single_line_patterns = [
            (r'<button[^>]*>([^<{]+)</button>', 'button text'),
            (r'<label[^>]*>([^<{]+)</label>', 'label text'),
            (r'<h[1-6][^>]*>([^<{]+)</h[1-6]>', 'heading text'),
        ]

        for i, line in enumerate(lines, 1):
            # Skip lines with ANY template syntax
            if '{{' in line or '{%' in line:
                continue
                
            for pattern, desc in single_line_patterns:
                matches = re.finditer(pattern, line)
                for match in matches:
                    text = match.group(1).strip()
                    
                    # Skip emails and URLs (never need translation)
                    if re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', text):
                        continue
                    if re.match(r'^https?://', text):
                        continue
                    
                    # Only flag if it's substantial text (2+ words OR 12+ characters)
                    if len(text) >= 12 or len(text.split()) >= 2:
                        display_text = text[:50] + '...' if len(text) > 50 else text
                        issues['LOW'].append({
                            'file': str(rel_path),
                            'line': i,
                            'issue': f'Possible untranslated text: "{display_text}"',
                            'severity': 'LOW'
                        })
                        stats['untranslated_strings'] += 1

        # Pattern 2: Multi-line paragraphs (process full content with DOTALL)
        paragraph_pattern = r'<p[^>]*>(.*?)</p>'
        for match in re.finditer(paragraph_pattern, content, re.DOTALL):
            full_text = match.group(1)
            
            # Skip if contains ANY Django template syntax (variables or tags)
            if '{{' in full_text or '{%' in full_text:
                continue
            
            # Extract just the text content, removing HTML and whitespace
            text = re.sub(r'<[^>]+>', '', full_text)  # Remove HTML tags
            text = re.sub(r'\s+', ' ', text).strip()  # Normalize whitespace
            
            # Skip emails and URLs (never need translation)
            if re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', text):  # Email pattern
                continue
            if re.match(r'^https?://', text):  # URL pattern
                continue
            
            # Only flag substantial text
            if len(text) >= 12 or len(text.split()) >= 2:
                # Find line number where this paragraph starts
                text_before_match = content[:match.start()]
                line_num = text_before_match.count('\n') + 1
                
                display_text = text[:50] + '...' if len(text) > 50 else text
                issues['LOW'].append({
                    'file': str(rel_path),
                    'line': line_num,
                    'issue': f'Possible untranslated text: "{display_text}"',
                    'severity': 'LOW'
                })
                stats['untranslated_strings'] += 1

    def _print_summary(self, stats, issues):
        """Print validation summary to console."""
        total_issues = sum(len(issues[severity]) for severity in ['HIGH', 'MEDIUM', 'LOW'])
        
        self.stdout.write('=' * 80)
        self.stdout.write('VALIDATION SUMMARY')
        self.stdout.write('=' * 80)
        self.stdout.write(f"Total files scanned: {stats['total_files']}")
        if stats['ignored_files'] > 0:
            self.stdout.write(f"Files ignored (VALIDATOR_IGNORE): {stats['ignored_files']}")
        self.stdout.write(f"Total issues found: {total_issues}")
        self.stdout.write(f"  - Missing i18n load: {stats['missing_i18n']}")
        self.stdout.write(f"  - Missing static load: {stats['missing_static']}")
        self.stdout.write(f"  - Hardcoded URLs: {stats['hardcoded_urls']}")
        self.stdout.write(f"  - Hardcoded static paths: {stats['hardcoded_static']}")
        self.stdout.write(f"  - Possibly untranslated: {stats['untranslated_strings']}")
        self.stdout.write('')

        # Print issues grouped by severity (console truncated to 20 per group)
        self.stdout.write('=' * 80)
        self.stdout.write('ISSUES FOUND')
        self.stdout.write('=' * 80)
        self.stdout.write('')

        for severity in ['HIGH', 'MEDIUM', 'LOW']:
            severity_issues = issues[severity]
            if severity_issues:
                count = len(severity_issues)
                self.stdout.write(f"{severity} PRIORITY ({count} issues):")
                self.stdout.write('-' * 80)
                
                # Show first 20, then indicate there are more
                for issue in severity_issues[:20]:
                    self.stdout.write(f"\nFile: {issue['file']}")
                    if issue['line']:
                        self.stdout.write(f"Line: {issue['line']}")
                    self.stdout.write(f"Issue: {issue['issue']}")
                
                if count > 20:
                    self.stdout.write(f"\n... and {count - 20} more {severity} issues")
                
                self.stdout.write('')

        if total_issues > 0:
            self.stdout.write(self.style.WARNING(f'⚠ Found {total_issues} issues to review.'))
        else:
            self.stdout.write(self.style.SUCCESS('✓ No issues found!'))
        
        if stats['ignored_files'] > 0:
            self.stdout.write(self.style.NOTICE(
                f'\nℹ {stats["ignored_files"]} files skipped due to VALIDATOR_IGNORE marker'
            ))
        
        if self.output_report:
            self.stdout.write(self.style.SUCCESS(f'\n✓ Full report written to: {self.output_report}'))

    def _write_report_to_file(self, stats, issues):
        """Write full validation report to markdown file."""
        total_issues = sum(len(issues[severity]) for severity in ['HIGH', 'MEDIUM', 'LOW'])
        
        with open(self.output_report, 'w', encoding='utf-8') as f:
            f.write('# UniHanko Template Validation Report\n\n')
            f.write('## Summary\n\n')
            f.write(f'- **Total files scanned:** {stats["total_files"]}\n')
            if stats['ignored_files'] > 0:
                f.write(f'- **Files ignored:** {stats["ignored_files"]} (VALIDATOR_IGNORE marker)\n')
            f.write(f'- **Total issues found:** {total_issues}\n\n')
            
            f.write('### Issue Breakdown\n\n')
            f.write(f'- Missing i18n load: {stats["missing_i18n"]}\n')
            f.write(f'- Missing static load: {stats["missing_static"]}\n')
            f.write(f'- Hardcoded URLs: {stats["hardcoded_urls"]}\n')
            f.write(f'- Hardcoded static paths: {stats["hardcoded_static"]}\n')
            f.write(f'- Possibly untranslated: {stats["untranslated_strings"]}\n\n')
            
            # Write all issues (no truncation)
            for severity in ['HIGH', 'MEDIUM', 'LOW']:
                severity_issues = issues[severity]
                if severity_issues:
                    f.write(f'## {severity} Priority Issues ({len(severity_issues)})\n\n')
                    
                    for issue in severity_issues:
                        f.write(f'### {issue["file"]}\n\n')
                        if issue['line']:
                            f.write(f'**Line:** {issue["line"]}\n\n')
                        f.write(f'**Issue:** {issue["issue"]}\n\n')
                        f.write('---\n\n')
            
            if total_issues == 0:
                f.write('## ✓ No Issues Found\n\n')
                f.write('All templates passed validation!\n')
            
            # Add tip about VALIDATOR_IGNORE
            f.write('\n## Tips\n\n')
            f.write('To mark a template as intentionally exempt from validation, add this comment at the top:\n\n')
            f.write('```html\n{# VALIDATOR_IGNORE: reason_here #}\n```\n\n')
            f.write('The validator will skip this file and note it in the report.\n')

    def extract_portal_text(self, template_files):
        """Extract text from Portal templates for content review."""
        portal_files = [f for f in template_files if 'portal' in str(f)]
        
        if not portal_files:
            self.stdout.write(self.style.WARNING('No Portal templates found.'))
            return

        extracted_data = {}

        for template_path in portal_files:
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()

            rel_path = template_path.relative_to(template_path.parents[len(template_path.parents) - 3])
            
            extractions = {
                'translated': [],
                'help_text': [],
                'placeholder': [],
                'button': []
            }

            lines = content.split('\n')

            # Extract {% trans "..." %} strings
            for i, line in enumerate(lines, 1):
                trans_matches = re.finditer(r'\{%\s*trans\s+["\']([^"\']+)["\']\s*%\}', line)
                for match in trans_matches:
                    extractions['translated'].append((i, match.group(1)))

            # Extract help_text attributes
            for i, line in enumerate(lines, 1):
                help_matches = re.finditer(r'help_text=["\']([^"\']+)["\']', line)
                for match in help_matches:
                    extractions['help_text'].append((i, match.group(1)))

            # Extract placeholder attributes
            for i, line in enumerate(lines, 1):
                placeholder_matches = re.finditer(r'placeholder=["\']([^"\']+)["\']', line)
                for match in placeholder_matches:
                    extractions['placeholder'].append((i, match.group(1)))

            # Extract button content
            for i, line in enumerate(lines, 1):
                button_matches = re.finditer(r'<button[^>]*>([^<{]+)</button>', line)
                for match in button_matches:
                    text = match.group(1).strip()
                    if text:
                        extractions['button'].append((i, text))

            if any(extractions.values()):
                extracted_data[str(rel_path)] = extractions

        # Write to markdown file
        with open(self.output_file, 'w', encoding='utf-8') as f:
            f.write('# Portal Template Text Extraction\n\n')
            f.write('*For content review and "cringe AI text" identification*\n\n')
            
            for file_path, data in sorted(extracted_data.items()):
                f.write(f'## {file_path}\n\n')
                
                for category, items in data.items():
                    if items:
                        f.write(f'### {category.upper()}\n\n')
                        for line_num, text in items:
                            f.write(f'- Line {line_num}: `{text}`\n')
                        f.write('\n')
                
                f.write('---\n\n')

        self.stdout.write(self.style.SUCCESS(f'✓ Text extraction written to: {self.output_file}'))
        self.stdout.write(f'Extracted from {len(extracted_data)} Portal templates.')