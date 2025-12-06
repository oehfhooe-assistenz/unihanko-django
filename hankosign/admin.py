# File: hankosign/admin.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.contrib import admin
from django import forms
from core.admin_mixins import HistoryGuardMixin, safe_admin_action, with_help_widget
from django.utils.translation import gettext_lazy as _
from core.utils.bool_admin_status import boolean_status_span, row_state_attr_for_boolean
from .models import Action, Policy, Signatory, Signature
from simple_history.admin import SimpleHistoryAdmin
from organisation.models import OrgInfo
from django.utils.text import slugify
from django.utils import timezone
from core.pdf import render_pdf_response
from django_object_actions import DjangoObjectActions
from core.admin_mixins import log_deletions
from django_admin_inline_paginator_plus.admin import StackedInlinePaginated


class SignatureInline(StackedInlinePaginated):
    model = Signature
    extra = 0
    per_page = 10
    pagination_key = "signature"
    can_delete = False
    readonly_fields = ("at", "verb", "stage", "content_type", "object_id", "signature_id", "note")
    fields = ("at", "verb", "stage", "content_type", "object_id", "signature_id", "note")
    ordering = ("-at",)

    def has_add_permission(self, request, obj):
        return False


@log_deletions
@with_help_widget
@admin.register(Action)
class ActionAdmin(SimpleHistoryAdmin, HistoryGuardMixin, admin.ModelAdmin):
    list_display = ("human_label", "verb", "stage", "scope", "is_repeatable", "require_distinct_signer", "action_code", "updated_at")
    list_filter = ("verb", "stage", "scope", "is_repeatable", "require_distinct_signer")
    search_fields = ("human_label",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (_("Definition"), {"fields": ("verb", "stage", "scope", "human_label", "comment")}),
        (_("Behavior"), {"fields": ("is_repeatable", "require_distinct_signer")}),
        (_("System"), {"fields": ("created_at", "updated_at")}),
    )

    # --- policy -------------------------------------------------------------
    def has_delete_permission(self, request, obj=None):
        return False
    
    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj:
            fields.extend(["verb", "stage", "scope"])  # Can't change action identity
        return fields


class PolicyAdminForm(forms.ModelForm):
    class Meta:
        model = Policy
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        has_fk = bool(cleaned.get("action"))
        has_m2m = bool(self.instance.pk and self.instance.actions.exists()) or bool(
            self.data.getlist("actions")  # handles create form
        )
        if not has_fk and not has_m2m:
            raise forms.ValidationError(_("Pick at least one Action (legacy FK or the list)."))
        if has_fk and has_m2m:
            raise forms.ValidationError(_("Use either the legacy FK *or* the list, not both."))
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        # pass M2M ids to the model so .clean() can see them on first save
        obj.set_pending_actions(self.data.getlist('actions'))
        if commit:
            obj.save()
            self.save_m2m()  # still calls the normal M2M writer; model.save() handles pending too
        return obj

@log_deletions
@with_help_widget
@admin.register(Policy)
class PolicyAdmin(SimpleHistoryAdmin, HistoryGuardMixin, admin.ModelAdmin):
    form = PolicyAdminForm
    list_display = ("role", "actions_display", "actions_count" , "updated_at")
    list_filter = ("actions__verb", "actions__stage", "actions__scope",)
    search_fields = ("role__name", "action__human_label", "actions__human_label")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("role", "action")
    filter_horizontal = ("actions",)
    fieldsets = (
        (_("Grant"), {"fields": ("role", "action", "actions",)}),
        (_("Notes"), {"fields": ("notes",)}),
        (_("System"), {"fields": ("created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related("actions").select_related("action", "role").distinct()

    @admin.display(description=_("Actions (effective)"))
    def actions_display(self, obj):
        xs = list(obj.actions.values_list("human_label", flat=True))
        return ", ".join(xs) if xs else (obj.action.human_label if obj.action_id else "—")

    @admin.display(description=_("Actions (M2M)"))
    def actions_count(self, obj):
        return obj.actions.count()
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj:
            fields.extend(["role", "action"])  # Can keep actions M2M editable
        return fields

@log_deletions
@with_help_widget
@admin.register(Signatory)
class SignatoryAdmin(SimpleHistoryAdmin, DjangoObjectActions, HistoryGuardMixin, admin.ModelAdmin):
    list_display = ("display_name", "user_display", "person_role", "verified_text", "updated_at", "active_text")
    list_filter = ("is_active", "is_verified", "person_role__role")
    search_fields = ("person_role__person__last_name", "person_role__person__first_name", "person_role__person__user__username")
    readonly_fields = ("created_at", "updated_at", "base_key", "user_display")
    autocomplete_fields = ("person_role",)
    inlines = [SignatureInline]
    fieldsets = (
        (_("Scope"), {"fields": ("person_role", "user_display", "name_override")}),
        (_("Status"), {"fields": ("is_active", "is_verified", "pdf_specimen")}),
        (_("System"), {"fields": ("base_key", "created_at", "updated_at")}),
    )
    change_actions = ("print_specimen",)
    @admin.display(description=_("Active"))
    def active_text(self, obj):
        # pure badge component; no inline colors
        return boolean_status_span(
            bool(obj.is_active),
            true_label=_("Active"),
            false_label=_("Inactive"),
            true_code="ok",
            false_code="off",
        )

    @admin.display(description=_("Verified"))
    def verified_text(self, obj):
        return _("OK") if obj.is_verified else _("NOT OK")

    def get_changelist_row_attrs(self, request, obj):
        # left border, etc., comes from your global CSS/JS using data-state attr
        return row_state_attr_for_boolean(bool(getattr(obj, "is_active", False)))

    @admin.display(description=_("User"))
    def user_display(self, obj):
        u = obj.user
        return getattr(u, "username", "—")
    
    # --- policy -------------------------------------------------------------
    def has_delete_permission(self, request, obj=None):
        return False
    
    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj:  # Existing object
            fields.extend(["person_role"])
        return fields
    

    @safe_admin_action
    def print_specimen(self, request, obj):
        """Print blank signature specimen form (no HankoSign tracking)."""
        
        org = OrgInfo.get_solo()
        date_str = timezone.localdate().isoformat()
        lname = slugify(obj.person_role.person.last_name)[:20]
        
        ctx = {
            "signatory": obj,
            "person": obj.person_role.person,
            "role": obj.person_role.role,
            "person_role": obj.person_role,
            "org": org,
            "date": date_str,
        }
        
        return render_pdf_response(
            "hankosign/specimen_pdf.html",
            ctx,
            request,
            f"SPECIMEN_{lname}_{date_str}.pdf"
        )

    print_specimen.label = "🖨️ " + _("Print Specimen Form")
    print_specimen.attrs = {
        "class": "btn btn-block btn-secondary",
        "style": "margin-bottom: 1rem;",
    }

@log_deletions
@with_help_widget
@admin.register(Signature)
class SignatureAdmin(admin.ModelAdmin):
    # Keep visible but lean; we can hide it from the sidebar if you prefer.
    list_display = ("at", "signatory", "verb", "stage", "content_type", "object_id", "signature_id")
    list_filter = ("verb", "stage", "content_type")
    search_fields = ("signature_id", "object_id", "signatory__name_override", "signatory__person_role__person__last_name")
    readonly_fields = ("signatory", "content_type", "object_id", "action", "verb", "stage", "scope_ct", "at", "note", "payload", "signature_id")
    fieldsets = (
        (_("Target"), {"fields": ("content_type", "object_id")}),
        (_("Action"), {"fields": ("action", "verb", "stage", "scope_ct")}),
        (_("Signer"), {"fields": ("signatory",)}),
        (_("Result"), {"fields": ("signature_id", "at", "note", "payload")}),
    )

    def get_model_perms(self, request):
        """Hide from sidebar for non-superusers (audit log access only)."""
        if request.user.is_superuser:
            return super().get_model_perms(request)
        return {}
    
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
