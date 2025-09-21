# core/admin_mixins.py
from django.contrib.auth.models import Group

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
