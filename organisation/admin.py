from django.contrib import admin
from django import forms
from django.utils.translation import gettext_lazy as _
from solo.admin import SingletonModelAdmin
from simple_history.admin import SimpleHistoryAdmin
from .models import OrgInfo
from core.admin_mixins import HelpPageMixin

class OrgInfoForm(forms.ModelForm):
    class Meta:
        model = OrgInfo
        fields = "__all__"
        widgets = {
            "org_address": forms.Textarea(attrs={"rows": 3}),
            "bank_address": forms.Textarea(attrs={"rows": 3}),
        }

class OrgInfoAdmin(HelpPageMixin, SingletonModelAdmin, SimpleHistoryAdmin):
    form = OrgInfoForm
    autocomplete_fields = (
        "org_chair",
        "org_dty_chair1",
        "org_dty_chair2",
        "org_dty_chair3",
        "org_wiref",
        "org_dty_wiref",
    )

    fieldsets = (
        (_("Organisation names"), {
            "fields": (
                ("org_name_long_de"),
                ("org_name_short_de"),
                ("org_name_long_en"),
                ("org_name_short_en"),
            )
        }),
        (_("University names"), {
            "fields": (
                ("uni_name_long_de"),
                ("uni_name_short_de"),
                ("uni_name_long_en"),
                ("uni_name_short_en"),
            )
        }),
        (_("Addresses"), {
            "fields": ("org_address",),
        }),
        (_("Banking & tax"), {
            "fields": (
                ("bank_name"),
                ("bank_address"),
                ("bank_iban"),
                ("bank_bic"),
                ("org_tax_id"),
                ("default_reference_label"),
                ),
        }),
        (_("Legal signatories"), {
            "fields": (
                ("org_chair"),
                ("org_dty_chair1"),
                ("org_dty_chair2"),
                ("org_dty_chair3"),
                ("org_wiref"),
                ("org_dty_wiref"),
            )
        }),
    )

    # --- Permissions wired to your access.yaml-assigned model perms ---------

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm("organisation.view_orginfo")

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm("organisation.change_orginfo")

    def get_model_perms(self, request):
        """
        Control whether the menu entry appears at all.
        If the user has no 'view', hide the app from the sidebar.
        """
        if not self.has_view_permission(request):
            return {}
        # Let the default machinery compute add/change/delete flags,
        # but we explicitly say there is at least 'view' for menu display.
        perms = super().get_model_perms(request)
        perms["view"] = True
        return perms

    def get_readonly_fields(self, request, obj=None):
        """
        Make every field read-only for users who only have 'view'.
        """
        ro = list(super().get_readonly_fields(request, obj))
        if not self.has_change_permission(request, obj):
            ro += [f.name for f in self.model._meta.fields]
        # de-dup while preserving order
        return list(dict.fromkeys(ro))

admin.site.register(OrgInfo, OrgInfoAdmin)
