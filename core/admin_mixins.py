# File: core/admin_mixins.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.contrib.auth.models import Group
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

FEATURE_IMPORT_GROUP = "feature:import"
FEATURE_EXPORT_GROUP = "feature:export"
FEATURE_HISTORY_GROUP = "feature:history"

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
from django.core.exceptions import PermissionDenied
import logging

admin_logger = logging.getLogger('unihanko.admin')

def safe_admin_action(func):
    """
    Decorator to add consistent error handling to admin object actions.
    
    - Catches PermissionDenied and shows user-friendly error
    - Catches all other exceptions, logs them, and shows generic error
    - Auto-redirects to change page if action returns None (prevents loops)
    """
    @wraps(func)
    def wrapper(self, request, obj):
        try:
            result = func(self, request, obj)
            # Auto-redirect if action doesn't explicitly return a response
            if result is None:
                opts = self.model._meta
                change_url = reverse(
                    f'admin:{opts.app_label}_{opts.model_name}_change',
                    args=[obj.pk]
                )
                return HttpResponseRedirect(change_url)
            return result
        except PermissionDenied as e:
            self.message_user(request, str(e), level=messages.ERROR)
            opts = self.model._meta
            change_url = reverse(
                f'admin:{opts.app_label}_{opts.model_name}_change',
                args=[obj.pk]
            )
            return HttpResponseRedirect(change_url)
        except Exception as e:
            self.message_user(
                request,
                f"An error occurred: {e}",
                level=messages.ERROR
            )
            admin_logger.exception(
                f"Error in {self.__class__.__name__}.{func.__name__} "
                f"for object {obj.pk}: {e}"
            )
            opts = self.model._meta
            change_url = reverse(
                f'admin:{opts.app_label}_{opts.model_name}_change',
                args=[obj.pk]
            )
            return HttpResponseRedirect(change_url)
    return wrapper
    

def with_help_widget(admin_class):
    """Decorator to add help widget context to admin views."""
    original_changelist = admin_class.changelist_view
    original_changeform = admin_class.changeform_view
    
    @wraps(original_changelist)
    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['show_help_widget'] = True
        return original_changelist(self, request, extra_context=extra_context)
    
    @wraps(original_changeform)
    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        extra_context = extra_context or {}
        extra_context['show_help_widget'] = True
        return original_changeform(self, request, object_id, form_url, extra_context=extra_context)
    
    admin_class.changelist_view = changelist_view
    admin_class.changeform_view = changeform_view
    
    return admin_class


def log_deletions(admin_class):
    """Decorator to add deletion logging to any ModelAdmin"""
    
    original_delete_model = admin_class.delete_model
    original_delete_queryset = admin_class.delete_queryset
    
    @wraps(original_delete_model)
    def delete_model_with_logging(self, request, obj):
        admin_logger.warning(
            f"User '{request.user.username}' deleted {obj._meta.verbose_name} "
            f"#{obj.pk}: {str(obj)[:100]}"
        )
        return original_delete_model(self, request, obj)
    
    @wraps(original_delete_queryset)
    def delete_queryset_with_logging(self, request, queryset):
        model_name = queryset.model._meta.verbose_name_plural
        count = queryset.count()
        admin_logger.warning(
            f"User '{request.user.username}' bulk deleted {count} {model_name}"
        )
        return original_delete_queryset(self, request, queryset)
    
    admin_class.delete_model = delete_model_with_logging
    admin_class.delete_queryset = delete_queryset_with_logging
    
    return admin_class
    

class HistoryGuardMixin:
    """
    Mixin to hide history button unless user is in feature:history group.
    Superusers always allowed.
    """
    
    history_feature_group = FEATURE_HISTORY_GROUP
    
    def _user_in_group(self, request, group_name: str) -> bool:
        if not group_name:
            return False
        return request.user.groups.filter(name=group_name).exists()
    
    def has_view_history_permission(self, request, obj=None):
        parent = super().has_view_history_permission(request, obj)
        if not parent:
            return False
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        return self._user_in_group(request, self.history_feature_group)