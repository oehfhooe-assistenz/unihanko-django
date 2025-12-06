"""
Master orchestrator for UniHanko system bootstrap.

Executes all bootstrap commands in correct dependency order:
1. OrgInfo (organization master data)
2. ACL permissions (groups & permissions)
3. HankoSign actions (workflow definitions)
4. Roles (organizational positions)
5. Transition reasons (role change reasons)
6. Holiday calendar (base calendar rules)
7. Fiscal years (financial periods)
8. Semesters (academic periods)
9. Terms (assembly legislative periods)
10. Help pages (contextual help system)

Usage:
  python manage.py bootstrap_unihanko --dry-run
  python manage.py bootstrap_unihanko
"""
# File: core/management/commands/bootstrap_unihanko.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.core.management.base import BaseCommand
from django.core.management import call_command
from io import StringIO


class Command(BaseCommand):
    help = "Bootstrap all UniHanko system data (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show planned changes without applying them",
        )

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        
        self.stdout.write(self.style.SUCCESS("=" * 70))
        self.stdout.write(self.style.SUCCESS("  UNIHANKO v1 BOOTSTRAP"))
        self.stdout.write(self.style.SUCCESS("=" * 70))
        
        if dry:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be applied\n"))
        
        # Define bootstrap sequence with proper dependency order
        commands = [
            ("bootstrap_orginfo", "Organization Master Data"),
            ("bootstrap_acls", "ACL Permissions"),
            ("bootstrap_actions", "HankoSign Actions"),
            ("bootstrap_roles", "Organizational Roles"),
            ("bootstrap_reasons", "Role Transition Reasons"),
            ("bootstrap_holidays", "Holiday Calendar"),
            ("bootstrap_fiscalyears", "Fiscal Years"),
            ("bootstrap_semesters", "Academic Semesters"),
            ("bootstrap_terms", "Assembly Terms"),
            ("bootstrap_helppages", "Help Pages"),
            ("bootstrap_people", "People"),
            ("bootstrap_assignments", "Assignments (PersonRole)"),
        ]
        
        results = []
        
        for cmd, label in commands:
            self.stdout.write(f"\n{'─' * 70}")
            self.stdout.write(self.style.NOTICE(f"▸ {label}"))
            self.stdout.write(f"{'─' * 70}")
            
            try:
                # Capture output
                out = StringIO()
                err = StringIO()
                
                # CRITICAL: Pass dry_run flag to sub-command
                call_command(cmd, dry_run=dry, stdout=out, stderr=err)
                
                output = out.getvalue()
                errors = err.getvalue()
                
                # Show output
                if output:
                    self.stdout.write(output)
                if errors:
                    self.stderr.write(errors)
                
                results.append((label, "✓", None))
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ Failed: {e}"))
                results.append((label, "✗", str(e)))
        
        # Summary
        self.stdout.write(f"\n{'=' * 70}")
        self.stdout.write(self.style.SUCCESS("  BOOTSTRAP SUMMARY"))
        self.stdout.write(f"{'=' * 70}\n")
        
        for label, status, error in results:
            if status == "✓":
                self.stdout.write(self.style.SUCCESS(f"{status} {label}"))
            else:
                self.stdout.write(self.style.ERROR(f"{status} {label}: {error}"))
        
        self.stdout.write("")
        
        success_count = sum(1 for _, s, _ in results if s == "✓")
        total = len(results)
        
        if success_count == total:
            if dry:
                self.stdout.write(
                    self.style.WARNING(f"✓ Dry run complete! All {total} bootstrap commands validated successfully.")
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(f"✓ All {total} bootstrap commands completed successfully!")
                )
        else:
            self.stdout.write(
                self.style.ERROR(f"✗ {total - success_count}/{total} commands failed")
            )
            return 1  # Exit code for failure