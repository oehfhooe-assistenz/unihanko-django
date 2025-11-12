# core/admin_mixins.py
from django.contrib.auth.models import Group
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

FEATURE_IMPORT_GROUP = "feature:import"
FEATURE_EXPORT_GROUP = "feature:export"     # or use one combined group

class ImportExportGuardMixin:
    """
    Mixin to hide Import/Export buttons unless the user is in the feature group(s).
    Works with ImportExportModelAdmin. Superusers always allowed.
    """

    import_feature_group = FEATURE_IMPORT_GROUP
    export_feature_group = FEATURE_EXPORT_GROUP

    def _user_in_group(self, request, group_name: str) -> bool:
        if not group_name:
            return False
        return request.user.groups.filter(name=group_name).exists()

    def has_import_permission(self, request, *args, **kwargs):
        # Keep any default logic from parent class (e.g. ImportExportModelAdmin)
        parent = getattr(super(), "has_import_permission", lambda *_: True)(request, *args, **kwargs)
        if not parent:
            return False
        u = request.user
        if not u.is_authenticated:
            return False
        if u.is_superuser:
            return True
        return self._user_in_group(request, self.import_feature_group)

    def has_export_permission(self, request, *args, **kwargs):
        parent = getattr(super(), "has_export_permission", lambda *_: True)(request, *args, **kwargs)
        if not parent:
            return False
        u = request.user
        if not u.is_authenticated:
            return False
        if u.is_superuser:
            return True
        return self._user_in_group(request, self.export_feature_group)

from functools import wraps
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.core.exceptions import PermissionDenied
import logging

logger = logging.getLogger('unihanko.admin')  # We'll configure this logger in settings

def safe_admin_action(func):
    """
    Decorator to add consistent error handling to admin object actions.
    
    - Catches PermissionDenied and shows user-friendly error
    - Catches all other exceptions, logs them, and shows generic error
    - Returns user to the change page on error
    """
    @wraps(func)
    def wrapper(self, request, obj):
        try:
            return func(self, request, obj)
        except PermissionDenied as e:
            # Expected authorization errors
            self.message_user(request, str(e), level=messages.ERROR)
            return HttpResponseRedirect(request.path)
        except Exception as e:
            # Unexpected errors - log for debugging
            self.message_user(
                request,
                f"An error occurred: {e}",
                level=messages.ERROR
            )
            logger.exception(
                f"Error in {self.__class__.__name__}.{func.__name__} "
                f"for object {obj.pk}: {e}"
            )
            return HttpResponseRedirect(request.path)
    return wrapper


class HelpPageMixin:
    """Mixin to add help widget to admin changelist."""
    
    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['show_help_widget'] = True
        return super().changelist_view(request, extra_context=extra_context)
    
    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        extra_context = extra_context or {}
        extra_context['show_help_widget'] = True
        return super().changeform_view(request, object_id, form_url, extra_context=extra_context)
    

class ManagerOnlyHistoryMixin:
    """Show history link only to managers/superusers"""
    
    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        
        # Check if user can see history
        show_history = (
            request.user.is_superuser or 
            request.user.groups.filter(name__icontains='manager').exists()
        )
        
        extra_context['show_history_link'] = show_history
        
        return super().change_view(request, object_id, form_url, extra_context)