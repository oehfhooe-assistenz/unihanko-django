# core/management/commands/purge_admin_log.py
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.contrib.admin.models import LogEntry
from django.utils import timezone

class Command(BaseCommand):
    help = "Delete admin LogEntry rows older than N days (default 180)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=180)

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(days=opts["days"])
        deleted, _ = LogEntry.objects.filter(action_time__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} old admin log entries"))
