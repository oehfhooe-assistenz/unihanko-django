# File: core/management/commands/maintenance.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-12-04

from django.core.management.base import BaseCommand, CommandError
import os
import tempfile


class Command(BaseCommand):
    help = 'Enable, disable, or check maintenance mode'
    
    # Use OS-appropriate temp directory (works on Windows, Linux, Mac)
    FLAG_FILE = os.path.join(tempfile.gettempdir(), 'maintenance.flag')
    
    def add_arguments(self, parser):
        parser.add_argument(
            'action',
            type=str,
            choices=['on', 'off', 'status'],
            help='Action to perform: on (enable), off (disable), or status (check)'
        )
    
    def handle(self, *args, **options):
        action = options['action']
        
        if action == 'on':
            self.enable_maintenance()
        elif action == 'off':
            self.disable_maintenance()
        elif action == 'status':
            self.check_status()
    
    def enable_maintenance(self):
        """Enable maintenance mode by creating flag file."""
        try:
            # Create the flag file
            open(self.FLAG_FILE, 'a').close()
            
            self.stdout.write(
                self.style.SUCCESS('✓ Maintenance mode ENABLED')
            )
            self.stdout.write(
                self.style.WARNING('  → Non-superusers will see the maintenance page')
            )
            self.stdout.write(
                self.style.WARNING('  → Superusers can still access the site')
            )
        except Exception as e:
            raise CommandError(f'Failed to enable maintenance mode: {e}')
    
    def disable_maintenance(self):
        """Disable maintenance mode by removing flag file."""
        try:
            if os.path.exists(self.FLAG_FILE):
                os.remove(self.FLAG_FILE)
                self.stdout.write(
                    self.style.SUCCESS('✓ Maintenance mode DISABLED')
                )
                self.stdout.write('  → Site is now accessible to everyone')
            else:
                self.stdout.write(
                    self.style.WARNING('  Maintenance mode was already disabled')
                )
        except Exception as e:
            raise CommandError(f'Failed to disable maintenance mode: {e}')
    
    def check_status(self):
        """Check if maintenance mode is currently enabled."""
        if os.path.exists(self.FLAG_FILE):
            self.stdout.write(
                self.style.WARNING('⚠ Maintenance mode is ENABLED')
            )
            self.stdout.write(
                f'  Flag file: {self.FLAG_FILE}'
            )
            
            # Show file modification time
            try:
                import datetime
                mtime = os.path.getmtime(self.FLAG_FILE)
                enabled_at = datetime.datetime.fromtimestamp(mtime)
                self.stdout.write(
                    f'  Enabled at: {enabled_at.strftime("%Y-%m-%d %H:%M:%S")}'
                )
            except Exception:
                pass
        else:
            self.stdout.write(
                self.style.SUCCESS('✓ Maintenance mode is DISABLED')
            )
            self.stdout.write('  → Site is operating normally')