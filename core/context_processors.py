# File: core/context_processors.py
# Version: 1.0.1
# Author: vas
# Modified: 2025-12-08

from django.conf import settings

def version_info(request):
    """Make version info available in all templates."""
    return {
        'UNIHANKO_VERSION': settings.UNIHANKO_VERSION,
        'UNIHANKO_CODENAME': settings.UNIHANKO_CODENAME,
        'UNIHANKO_VERSION_FULL': settings.UNIHANKO_VERSION_FULL,
        'ENVIRONMENT': getattr(settings, 'ENVIRONMENT', 'development'),
    }