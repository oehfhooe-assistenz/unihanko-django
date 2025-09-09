from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class FinancesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'finances'
    verbose_name = _('Finances')
