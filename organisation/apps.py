from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

class OrganisationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "organisation"
    verbose_name = _("Organisation")
