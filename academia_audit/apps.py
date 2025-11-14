from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AcademiaAuditConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'academia_audit'
    verbose_name = _('Academia Audit')
