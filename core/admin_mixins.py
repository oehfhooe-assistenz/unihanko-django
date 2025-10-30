# core/admin_mixins.py
from django.contrib.auth.models import Group
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from concurrency.exceptions import RecordModifiedError
from django.contrib import admin

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

class FriendlyConcurrencyMixin:
    """
    Show a clearer message on concurrency conflicts.
    We *bypass* ConcurrentModelAdmin.save_model/delete_model
    to avoid its built-in catch-and-toast.
    """

    def save_model(self, request, obj, form, change):
        try:
            # Skip ConcurrentModelAdmin.save_model to avoid its catch.
            admin.ModelAdmin.save_model(self, request, obj, form, change)
        except RecordModifiedError:
            self.message_user(
                request,
                _("Someone else updated this record while you were editing. "
                  "Your changes were NOT saved. Reload, review, then submit again."),
                level=messages.ERROR,
            )
            return HttpResponseRedirect(
                reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change", args=[obj.pk])
            )

    def delete_model(self, request, obj):
        try:
            admin.ModelAdmin.delete_model(self, request, obj)
        except RecordModifiedError:
            self.message_user(
                request,
                _("This record changed just now and could not be deleted. Reload and try again."),
                level=messages.ERROR,
            )
            return HttpResponseRedirect(
                reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change", args=[obj.pk])
            )