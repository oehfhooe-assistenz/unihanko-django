# File: portal/apps.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-27

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PortalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "portal"
    verbose_name = _("Public Portal")
