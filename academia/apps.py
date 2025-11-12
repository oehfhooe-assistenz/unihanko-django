from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AcademiaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'academia'
    verbose_name = _('Academia Inbox')
