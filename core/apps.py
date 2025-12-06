# File: core/apps.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.apps import AppConfig

class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Core"

    def ready(self):
        """Import signals when Django starts"""
        import core.signals  # This loads and connects your signals