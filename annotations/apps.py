# File: annotations/apps.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AnnotationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'annotations'
    verbose_name = _("Annotations")