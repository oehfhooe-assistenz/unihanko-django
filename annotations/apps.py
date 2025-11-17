from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AnnotationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'annotations'
    verbose_name = _("Annotations")