# File: academia_audit/apps.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AcademiaAuditConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'academia_audit'
    verbose_name = _('Academia Audit')
