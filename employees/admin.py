# File: employees/admin.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.contrib import admin, messages
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.shortcuts import redirect
from django_object_actions import DjangoObjectActions
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from simple_history.admin import SimpleHistoryAdmin
from core.admin_mixins import ImportExportGuardMixin, safe_admin_action, HistoryGuardMixin, with_help_widget
from core.pdf import render_pdf_response
from organisation.models import OrgInfo
from decimal import Decimal, ROUND_HALF_UP
from django.urls import reverse
from django.http import HttpResponse
from datetime import date as _date, timedelta
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from django.utils.formats import date_format
from concurrency.admin import ConcurrentModelAdmin
from django import forms
from django.contrib.admin.widgets import AdminTimeWidget
from core.utils.authz import is_employees_manager
from django.db import transaction
from .models import (
    Employee,
    EmploymentDocument,
    TimeSheet,
    TimeEntry,
    HolidayCalendar,
    EmployeeLeaveYear,
)
from hankosign.utils import record_signature, get_action, state_snapshot, render_signatures_box, RID_JS, sign_once, seal_signatures_context, object_status_span
from core.utils.bool_admin_status import boolean_status_span, row_state_attr_for_boolean
from django.contrib.contenttypes.models import ContentType
from django.db.models import Exists, OuterRef, Subquery, F, Q, BooleanField, ExpressionWrapper
from hankosign.models import Signature
from annotations.admin import AnnotationInline
from annotations.views import create_system_annotation
from core.admin_mixins import log_deletions
from django_admin_inline_paginator_plus.admin import StackedInlinePaginated

# =========================
# Import–Export resources
# =========================

class EmployeeResource(resources.ModelResource):
    class Meta:
        model = Employee
        fields = (
            "id",
            "person_role",
            "weekly_hours",
            "saldo_minutes",
            "is_active",
            "created_at",
            "updated_at",
        )
        export_order = fields


class EmploymentDocumentResource(resources.ModelResource):
    class Meta:
        model = EmploymentDocument
        fields = (
            "id",
            "employee",
            "kind",
            "code",
            "title",
            "start_date",
            "end_date",
            "is_active",
            "created_at",
            "updated_at",
        )
        export_order = fields


class TimeSheetResource(resources.ModelResource):
    class Meta:
        model = TimeSheet
        fields = (
            "id",
            "employee",
            "year",
            "month",
            "expected_minutes",
            "worked_minutes",
            "credit_minutes",
            "closing_saldo_minutes",
            "created_at",
            "updated_at",
        )
        export_order = fields


class TimeEntryResource(resources.ModelResource):
    class Meta:
        model = TimeEntry
        fields = (
            "id",
            "timesheet",
            "date",
            "minutes",
            "kind",
            "comment",
            "created_at",
            "updated_at",
        )
        export_order = fields


class HolidayCalendarResource(resources.ModelResource):
    class Meta:
        model = HolidayCalendar
        fields = ("id", "name", "is_active", "rules_text", "created_at", "updated_at")
        export_order = fields


# =========================
# Helpers / mixins
# =========================

class ManagerEditableGateMixin:
    """Gate certain UI actions to managers only."""

    def _is_manager(self, request) -> bool:
        return is_employees_manager(request.user)


# =========================
# Inlines
# =========================

class TimeEntryAdminForm(forms.ModelForm):
    class Meta:
        model = TimeEntry
        fields = "__all__"
        widgets = {
            "timesheet": forms.HiddenInput(),
            "start_time": AdminTimeWidget(format="%H:%M"),
            "end_time": AdminTimeWidget(format="%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        k = TimeEntry.Kind
        if "kind" in self.fields:
            self.fields["kind"].choices = [
                (v, label) for v, label in self.fields["kind"].choices if v != k.PUBLIC_HOLIDAY
            ]
        # Accept HH:MM and HH:MM:SS only if those fields are present
        for name in ("start_time", "end_time"):
            if name in self.fields:
                self.fields[name].input_formats = ["%H:%M", "%H:%M:%S"]
        
    # Optional: normalize seconds to :00 at form level too
    def clean_start_time(self):
        t = self.cleaned_data.get("start_time")
        return t.replace(second=0, microsecond=0) if t else t

    def clean_end_time(self):
        t = self.cleaned_data.get("end_time")
        return t.replace(second=0, microsecond=0) if t else t

class TimeEntryInline(StackedInlinePaginated):
    model = TimeEntry
    form = TimeEntryAdminForm
    per_page = 10
    pagination_key = "time-entry"
    extra = 0
    fields = ("version","date", "kind", "start_time", "end_time", "minutes", "comment",)
    readonly_fields = ()
    can_delete = True
    show_change_link = False
    ordering = ("date",)

    def get_max_num(self, request, obj=None, **kwargs):
        return 200
    
    def has_add_permission(self, request, obj):
        if obj and getattr(self.admin_site._registry[type(obj)], "_is_locked", None):
            if self.admin_site._registry[type(obj)]._is_locked(request, obj):
                return False
        return super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj and getattr(self.admin_site._registry[type(obj)], "_is_locked", None):
            if self.admin_site._registry[type(obj)]._is_locked(request, obj):
                return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and getattr(self.admin_site._registry[type(obj)], "_is_locked", None):
            if self.admin_site._registry[type(obj)]._is_locked(request, obj):
                return False
        return super().has_delete_permission(request, obj)
    

class EmploymentDocumentInline(StackedInlinePaginated):
    model = EmploymentDocument
    per_page = 3
    pagination_key = "employment-document"
    extra = 0
    fields = ("kind", "title", "start_date", "end_date", "is_active", "pdf_file", "code")
    readonly_fields = ("code",)
    can_delete = False
    show_change_link = True


# =========================
# Employee Admin
# =========================

class EmployeeLeaveYearInline(StackedInlinePaginated):
    model = EmployeeLeaveYear
    extra = 0
    per_page = 1
    pagination_key = "employee-leave-year"
    can_delete = False
    verbose_name = _("PTO Year Breakdown")
    verbose_name_plural = _("PTO Years Breakdown")
    fields = (
        "label_year",
        "period_start",
        "period_end",
        "entitlement_minutes",
        "carry_in_minutes",
        "manual_adjust_minutes",
        "taken_minutes",
        "remaining_minutes",
    )
    readonly_fields = (
        "label_year",
        "period_start",
        "period_end",
        "entitlement_minutes",
        "carry_in_minutes",
        "taken_minutes",
        "remaining_minutes",
    )
    
    def has_add_permission(self, request, obj):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.order_by("-label_year")


@with_help_widget
@admin.register(Employee)
class EmployeeAdmin(
    SimpleHistoryAdmin,
    DjangoObjectActions,
    ImportExportModelAdmin,
    ManagerEditableGateMixin, 
    ImportExportGuardMixin,
    HistoryGuardMixin
    ):
    resource_classes = [EmployeeResource]
    list_display = (
        "person_role",
        "weekly_hours",
        "saldo_display",
        "updated_at",
        "active_text",
    )
    list_display_links = ("person_role",)
    list_filter = ("is_active", "weekly_hours",)
    search_fields = (
        "person_role__person__last_name",
        "person_role__person__first_name",
        "person_role__role__name",
    )
    autocomplete_fields = ("person_role",)
    readonly_fields = ("daily_expected", "created_at", "updated_at", "signatures_box")
    inlines = [EmployeeLeaveYearInline, EmploymentDocumentInline]

    fieldsets = (
        (_("Scope"), {"fields": ("person_role", "is_active")}),
        (_("Work terms"), {"fields": ("weekly_hours", "saldo_minutes", "daily_expected")}),
        (_("PTO terms"), {"fields": ("annual_leave_days_base", "annual_leave_days_extra", "leave_reset_override")}),
        (_("Personal data"), {"fields": ("insurance_no", "dob",)}),
        (_("Miscellaneous"), {"fields": ("notes",)}),
        (_("Workflow & HankoSign"), {"fields": ("signatures_box",)}),
        (_("System"), {"fields": ("created_at", "updated_at",)}),
    )


    @admin.display(description=_("Saldo"))
    def saldo_display(self, obj):
        mins = int(obj.saldo_minutes or 0)
        sign = "-" if mins < 0 else "+"
        mins_abs = abs(mins)
        hh = mins_abs // 60
        mm = mins_abs % 60
        return f"{sign}{hh:02d}:{mm:02d}"


    @admin.display(description=_("Active"))
    def active_text(self, obj):

        # renders plain text + data-state="ok/off"
        return boolean_status_span(
            bool(obj.is_active),
            true_label=_("Active"),
            false_label=_("Inactive"),
            true_code="ok",
            false_code="off",
        )
    
    @admin.display(description=_("Daily expected minutes"))
    def daily_expected(self, obj):
        return obj.daily_expected_minutes or None


    def get_changelist_row_attrs(self, request, obj):
        # left border, etc., comes from your global CSS/JS using data-state attr
        return row_state_attr_for_boolean(bool(getattr(obj, "is_active", False)))


    def has_delete_permission(self, request, obj=None):
        return False


    change_actions = ("print_employee",)
    @safe_admin_action
    def print_employee(self, request, obj):
        action = get_action("RELEASE:-@employees.employee")
        if not action:
            messages.error(request, _("Release action is not configured."))
            return
        sign_once(request, action, obj, note=_("Printed employee dossier PDF"), window_seconds=10)
        signatures = seal_signatures_context(obj)
        ctx = {"emp": obj, "signatures": signatures, "org": OrgInfo.get_solo()}
        return render_pdf_response("employees/employee_pdf.html", ctx, request, f"EMP_{obj.id}.pdf")
    print_employee.label = "🖨️ " + _("Print Employee PDF")
    print_employee.attrs = {
        "class": "btn btn-block btn-info",
        "style": "margin-bottom: 1rem;",
        "data-action": "post-object",
        "onclick": RID_JS,
    }


    @admin.display(description=_("Signatures"))
    def signatures_box(self, obj):
        
        return render_signatures_box(obj)


    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj and not request.user.is_superuser:
            ro += ["person_role",]
        return ro


    def get_inline_instances(self, request, obj=None):
        instances = super().get_inline_instances(request, obj)
        if not self._is_manager(request):
            # hide the PTO inline from editors
            instances = [i for i in instances if not isinstance(i, EmployeeLeaveYearInline)]
        return instances


    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Ensure the current label year exists
        today = timezone.localdate()
        ly_label = EmployeeLeaveYear.pto_label_year_for(obj, today)
        EmployeeLeaveYear.ensure_for(obj, ly_label)


# =========================
# EmploymentDocument Admin
# =========================

class EmploymentDocumentAdminForm(forms.ModelForm):
    class Meta:
        model = EmploymentDocument
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Determine kind from POST data first, else instance
        kind = (self.data.get("kind") or getattr(self.instance, "kind", None))
        if kind in (EmploymentDocument.Kind.KM, EmploymentDocument.Kind.AA):
            # mark as required so admin shows the red asterisk and client-side required
            if "start_date" in self.fields:
                self.fields["start_date"].required = True
            if "end_date" in self.fields:
                self.fields["end_date"].required = True

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("kind")
        s = cleaned.get("start_date")
        e = cleaned.get("end_date")

        if kind in (EmploymentDocument.Kind.KM, EmploymentDocument.Kind.AA):
            if not s:
                self.add_error("start_date", _("Required for this document type."))
            if not e:
                self.add_error("end_date", _("Required for this document type."))
        if s and e and e < s:
            self.add_error("end_date", _("End date cannot be before start date."))
        return cleaned

@log_deletions
@with_help_widget
@admin.register(EmploymentDocument)
class EmploymentDocumentAdmin(
    SimpleHistoryAdmin,
    DjangoObjectActions,
    ImportExportModelAdmin,
    ConcurrentModelAdmin,
    ImportExportGuardMixin,
    HistoryGuardMixin
    ):
    form = EmploymentDocumentAdminForm
    resource_classes = [EmploymentDocumentResource]
    inlines = [AnnotationInline]
    list_display = ("status_text", "code", "employee", "kind_text", "title", "period_display", "updated_at")
    list_display_links = ("code",)
    list_filter = ("kind", "is_active", "start_date", "end_date",)
    search_fields = (
        "code",
        "title",
        "employee__person_role__person__last_name",
        "employee__person_role__person__first_name",
        "employee__person_role__role__name",
    )
    autocomplete_fields = ("employee",)
    readonly_fields = ("code", "created_at", "updated_at", "signatures_box")

    fieldsets = (
        (_("Scope"), {"fields": ("employee", "code",)}),
        (_("Document"), {"fields": ("kind", "title", "start_date", "end_date", "is_active", "relevant_third_party", "pdf_file", "details")}),
        (_("Workflow & HankoSign"), {"fields": ("signatures_box",)}),
        (_("System"), {"fields": ("version", "created_at", "updated_at")}),
    )


    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related(
            "employee__person_role__person",
            "employee__person_role__role"
        )


    @admin.display(description=_("Kind"))
    def kind_text(self, obj):
        return obj.get_kind_display()


    @admin.display(description=_("Status"))
    def status_text(self, obj):
        # default stages are WIREF/CHAIR; override here if you want different tiers for docs
        return object_status_span(obj, final_stage="CHAIR", tier1_stage="WIREF")


    @admin.display(description=_("Period"))
    def period_display(self, obj):
        s = obj.start_date.strftime("%Y-%m-%d") if obj.start_date else "—"
        e = obj.end_date.strftime("%Y-%m-%d") if obj.end_date else "…"
        return f"{s} → {e}"


    @admin.display(description=_("Signatures"))
    def signatures_box(self, obj):
        return render_signatures_box(obj)


    def has_delete_permission(self, request, obj=None):
        """Allow deletion only for draft documents (not yet submitted)."""
        if not obj:
            return False  # No bulk delete from changelist
        
        # Check workflow state
        st = state_snapshot(obj)
        
        # Can delete if still in draft (not submitted)
        if st["submitted"]:
            return False  # Already in workflow, must use workflow actions
        
        # Draft documents can be deleted
        return True


    def get_readonly_fields(self, request, obj=None):
        base = list(super().get_readonly_fields(request, obj))
        is_mgr = self._is_manager(request)

        # always read-only for these once created (scope)
        scope_fields = ["employee", "kind"]

        if obj:  # edit view
            for f in scope_fields:
                if f not in base:
                    base.append(f)
            st = state_snapshot(obj)
            if st["submitted"] and not is_mgr:
                # lock the rest after submit for non-managers
                more = ["title", "start_date", "end_date", "pdf_file", "relevant_third_party", "details"]
                for f in more:
                    if f not in base:
                        base.append(f)
        return base


    change_actions = ("submit_doc", "withdraw_doc", "approve_wiref_doc", "approve_chair_doc", "reject_wiref_doc", "reject_chair_doc", "print_receipt", "print_leaverequest_receipt", "print_sicknote_receipt")
    def get_change_actions(self, request, object_id, form_url):
        actions = list(super().get_change_actions(request, object_id, form_url))
        obj = self.get_object(request, object_id)
        if not obj:
            return actions

        # ---- Print action gating FIRST (so it applies even if we return early) ----
        print_actions = {
            "print_receipt",
            "print_leaverequest_receipt",
            "print_sicknote_receipt",
        }
        allowed_by_kind = {
            obj.Kind.AA: {"print_leaverequest_receipt"},
            obj.Kind.KM: {"print_sicknote_receipt"},
            obj.Kind.ZV: {"print_receipt"},              # if ZV is flow-enabled but generic
        }.get(obj.kind, {"print_receipt"})               # default for other kinds

        actions = [a for a in actions if (a not in print_actions) or (a in allowed_by_kind)]

        # ---- If kind isn't flow-enabled, keep ONLY print actions already allowed above ----
        flow_kinds = {obj.Kind.AA, obj.Kind.KM, obj.Kind.ZV}
        if obj.kind not in flow_kinds:
            # At this point, only allowed print action(s) remain; drop everything else.
            return [a for a in actions if a in allowed_by_kind]

        # ---- Helper to drop any number of actions ----
        def drop(*names):
            for name in names:
                if name in actions:
                    actions.remove(name)

        # ---- State-based gating (unchanged logic, but now print gating already applied) ----
        st = state_snapshot(obj)
        approved = st["approved"]
        chair_ok = ("CHAIR" in approved) or st.get("final")
        wiref_ok = "WIREF" in approved
        submitted = st["submitted"]

        if chair_ok:
            drop("submit_doc", "withdraw_doc", "approve_wiref_doc", "approve_chair_doc", "reject_wiref_doc", "reject_chair_doc")
            return actions

        if wiref_ok:
            drop("submit_doc", "withdraw_doc", "approve_wiref_doc")
            return actions

        if submitted and not wiref_ok:
            drop("submit_doc", "approve_chair_doc", "reject_chair_doc")
            return actions

        # draft
        drop("withdraw_doc", "approve_wiref_doc", "approve_chair_doc", "reject_wiref_doc", "reject_chair_doc")
        return actions


    # actions
    @safe_admin_action
    def print_receipt(self, request, obj):
        action = get_action("RELEASE:-@employees.employmentdocument")
        if not action:
            messages.error(request, _("Release action is not configured."))
            return
        sign_once(request, action, obj, note=_("Printed document receipt PDF"), window_seconds=10)
        emp = (
            Employee.objects.select_related("person_role__person", "person_role__role").get(pk=obj.employee_id)
        )
        signatures = seal_signatures_context(obj)
        ctx = {
            "doc": obj,
            "org": OrgInfo.get_solo(),
            "emp": emp, "person": emp.person_role.person,
            "role": emp.person_role.role,
            "signatures": signatures,
            'signers': [
                {'label': emp.person_role.person.last_name},
                {'label': 'WiRef'},
                {'label': 'Chair'},
            ]
        }
        return render_pdf_response(
            "employees/document_receipt_pdf.html",
            ctx,
            request,
            filename=f"EDOC__{obj.code}.pdf",
        )
    print_receipt.label = "🖨️ " + _("Print document receipt PDF")
    print_receipt.attrs = {"class": "btn btn-block btn-info","style": "margin-bottom: 1rem;", "data-action": "post-object", "onclick": RID_JS}


    @safe_admin_action
    def print_leaverequest_receipt(self, request, obj):
        action = get_action("RELEASE:-@employees.employmentdocument")
        if not action:
            messages.error(request, _("Release action is not configured."))
            return
        # defensive guard (in case someone hits the URL directly)
        if obj.kind != obj.Kind.AA:
            messages.warning(request, _("Leave request is only available for AA documents."))
            return
        sign_once(request, action, obj, note=_("Printed leave request receipt PDF"), window_seconds=10)
        emp = (
            Employee.objects.select_related("person_role__person", "person_role__role").get(pk=obj.employee_id)
        )
        signatures = seal_signatures_context(obj)
        # Coalesce None -> 0 for arithmetic
        daily_minutes = emp.daily_expected_minutes or 0
        duration_days_incl = getattr(obj, "duration_weekdays_inclusive", None) or 0

        # Minutes total for the leave period
        leave_amount_minutes = int(daily_minutes) * int(duration_days_incl)

        # Hours (Decimal) with friendly rounding for PDFs
        def to_hours(minutes: int) -> Decimal:
            return (Decimal(minutes) / Decimal(60)).quantize(Decimal("0.00"), rounding=ROUND_HALF_UP)

        leave_amount_hours = to_hours(leave_amount_minutes)
        daily_expected_hours = to_hours(int(daily_minutes)) if daily_minutes else Decimal("0.00")
        ctx = {
            "doc": obj,
            "org": OrgInfo.get_solo(),
            "emp": emp,
            "person": emp.person_role.person,
            "role": emp.person_role.role,
            "leave_amount_m": leave_amount_minutes,
            "leave_amount_h": leave_amount_hours,
            "daily_expected_h": daily_expected_hours,
            "signatures": signatures,
            'signers': [
                {'label': emp.person_role.person.last_name},
                {'label': 'WiRef'},
                {'label': 'Chair'},
            ]
        }
        
        return render_pdf_response("employees/leaverequest_receipt_pdf.html", ctx, request, filename=f"EDOC_{obj.code}.pdf",)
    print_leaverequest_receipt.label = "🖨️ " + _("Print leave request receipt PDF")
    print_leaverequest_receipt.attrs = {"class": "btn btn-block btn-info","style": "margin-bottom: 1rem;", "data-action": "post-object", "onclick": RID_JS}


    @safe_admin_action
    def print_sicknote_receipt(self, request, obj):
        action = get_action("RELEASE:-@employees.employmentdocument")
        if not action:
            messages.error(request, _("Release action is not configured."))
            return
        # defensive guard (in case someone hits the URL directly)
        if obj.kind != obj.Kind.KM:
            messages.warning(request, _("Sick leave request is only available for KM documents."))
            return
        sign_once(request, action, obj, note=_("Printed sick note receipt PDF"), window_seconds=10)
        emp = (
            Employee.objects.select_related("person_role__person", "person_role__role").get(pk=obj.employee_id)
        )
        signatures = seal_signatures_context(obj)
        duration_days_incl = getattr(obj, "duration_weekdays_inclusive", None) or 0
        ctx = {
            "doc": obj,
            "org": OrgInfo.get_solo(),
            "emp": emp,
            "person": emp.person_role.person,
            "role": emp.person_role.role,
            "signatures": signatures,
            'signers': [
                {'label': emp.person_role.person.last_name},
                {'label': 'WiRef'},
                {'label': 'Chair'},
            ]
        }
        return render_pdf_response("employees/sicknote_receipt_pdf.html", ctx, request, filename=f"EDOC_{obj.code}.pdf")
    print_sicknote_receipt.label = "🖨️ " + _("Print sick note receipt PDF")
    print_sicknote_receipt.attrs = {"class": "btn btn-block btn-info","style": "margin-bottom: 1rem;", "data-action": "post-object", "onclick": RID_JS}


    @transaction.atomic
    @safe_admin_action
    def submit_doc(self, request, obj):
        st = state_snapshot(obj)
        if st["submitted"]:
            messages.info(request, _("Already submitted."))
            return
        action = get_action("SUBMIT:ASS@employees.employmentdocument")
        if not action:
            messages.error(request, _("Submission action is not configured."))
            return
        record_signature(request, action, obj, note=_("Document %(code)s submitted") % {"code": f"{obj.code}"})
        create_system_annotation(obj, "SUBMIT", user=request.user)
        messages.success(request, _("Submitted."))
    submit_doc.label = _("Submit")
    submit_doc.attrs = {"class": "btn btn-block btn-warning","style": "margin-bottom: 1rem;",}


    @transaction.atomic
    @safe_admin_action
    def withdraw_doc(self, request, obj):
        st = state_snapshot(obj)
        if not st["submitted"]:
            messages.info(request, _("Not submitted."))
            return
        if "WIREF" in st["approved"] or "CHAIR" in st["approved"]:
            messages.warning(request, _("Cannot withdraw after approvals."))
            return
        action = get_action("WITHDRAW:ASS@employees.employmentdocument")
        if not action:
            messages.error(request, _("Withdraw action is not configured."))
            return
        record_signature(request, action, obj, note=_("Document %(code)s withdrawn") % {"code": f"{obj.code}"})
        create_system_annotation(obj, "WITHDRAW", user=request.user)
        messages.success(request, _("Withdrawn."))
    withdraw_doc.label = _("Withdraw submission")
    withdraw_doc.attrs = {"class": "btn btn-block btn-secondary","style": "margin-bottom: 1rem;",}


    @transaction.atomic
    @safe_admin_action
    def approve_wiref_doc(self, request, obj):
        st = state_snapshot(obj)
        if not st["submitted"]:
            messages.warning(request, _("Submit first."))
            return
        if "WIREF" in st["approved"]:
            messages.info(request, _("Already approved (WiRef)."))
            return
        action = get_action("APPROVE:WIREF@employees.employmentdocument")
        if not action:
            messages.error(request, _("WiRef approval action is not configured."))
            return
        record_signature(request, action, obj, note=_("Document %(code)s approved (WiRef)") % {"code": f"{obj.code}"})
        create_system_annotation(obj, "APPROVE", user=request.user)
        messages.success(request, _("Approved (WiRef)."))
    approve_wiref_doc.label = _("Approve (WiRef)")
    approve_wiref_doc.attrs = {"class": "btn btn-block btn-success","style": "margin-bottom: 1rem;",}


    @transaction.atomic
    @safe_admin_action
    def approve_chair_doc(self, request, obj):
        st = state_snapshot(obj)
        if not st["submitted"]:
            messages.warning(request, _("Submit first."))
            return
        if "CHAIR" in st["approved"]:
            messages.info(request, _("Already approved (Chair)."))
            return
        action = get_action("APPROVE:CHAIR@employees.employmentdocument")
        if not action:
            messages.error(request, _("Chair approval action is not configured."))
            return
        record_signature(request, action, obj, note=_("Document %(code)s approved (Chair)") % {"code": f"{obj.code}"})
        create_system_annotation(obj, "APPROVE", user=request.user)
        messages.success(request, _("Approved (Chair)."))
    approve_chair_doc.label = _("Approve (Chair)")
    approve_chair_doc.attrs = {"class": "btn btn-block btn-success","style": "margin-bottom: 1rem;",}


    @transaction.atomic
    @safe_admin_action
    def reject_wiref_doc(self, request, obj):
        st = state_snapshot(obj)
        if not st["submitted"]:
            messages.warning(request, _("Nothing to reject (not submitted)."))
            return
        if "CHAIR" in st["approved"]:
            messages.warning(request, _("Already final; cannot reject."))
            return
        action = get_action("REJECT:WIREF@employees.employmentdocument")
        if not action:
            messages.error(request, _("WiRef rejection action is not configured."))
            return
        record_signature(request, action, obj, note=_("Document %(code)s rejected (WiRef)") % {"code": f"{obj.code}"})
        create_system_annotation(obj, "REJECT", user=request.user)
        messages.success(request, _("Rejected (WiRef)."))
    reject_wiref_doc.label = _("Reject (WiRef)")
    reject_wiref_doc.attrs = {"class": "btn btn-block btn-danger","style": "margin-bottom: 1rem;",}


    @transaction.atomic
    @safe_admin_action
    def reject_chair_doc(self, request, obj):
        st = state_snapshot(obj)
        if not st["submitted"]:
            messages.warning(request, _("Nothing to reject (not submitted)."))
            return
        if "CHAIR" in st["approved"]:
            messages.warning(request, _("Already final; cannot reject."))
            return
        action = get_action("REJECT:CHAIR@employees.employmentdocument")
        if not action:
            messages.error(request, _("Chair rejection action is not configured."))
            return
        record_signature(request, action, obj, note=_("Document %(code)s rejected (Chair)") % {"code": f"{obj.code}"})
        create_system_annotation(obj, "REJECT", user=request.user)
        messages.success(request, _("Rejected (Chair)."))
    reject_chair_doc.label = _("Reject (Chair)")
    reject_chair_doc.attrs = {"class": "btn btn-block btn-danger","style": "margin-bottom: 1rem;",}


# =========================
# Timesheet Admin
# =========================


class TimeSheetStateFilter(admin.SimpleListFilter):
    title = _("State")
    parameter_name = "state"

    def lookups(self, request, model_admin):
        return (
            ("draft", _("Draft")),
            ("submitted", _("Submitted")),
            ("approved_wiref", _("Approved (WiRef)")),
            ("approved_all", _("Approved (Final)")),
        )

    def queryset(self, request, qs):
        v = self.value()
        if not v:
            return qs

        ct = ContentType.objects.get_for_model(TimeSheet)

        # Latest SUBMIT and WITHDRAW times (per object)
        last_submit_at = Subquery(
            Signature.objects.filter(
                content_type=ct,
                object_id=OuterRef("pk"),
                verb="SUBMIT",
                stage="ASS",
            ).order_by("-at", "-id").values("at")[:1]
        )
        last_withdraw_at = Subquery(
            Signature.objects.filter(
                content_type=ct,
                object_id=OuterRef("pk"),
                verb="WITHDRAW",
                stage="ASS",
            ).order_by("-at", "-id").values("at")[:1]
        )

        # Approvals existence
        has_wiref = Exists(Signature.objects.filter(
            content_type=ct, object_id=OuterRef("pk"),
            verb="APPROVE", stage="WIREF"
        ))
        has_chair = Exists(Signature.objects.filter(
            content_type=ct, object_id=OuterRef("pk"),
            verb="APPROVE", stage="CHAIR"
        ))

        qs = qs.annotate(
            _last_submit_at=last_submit_at,
            _last_withdraw_at=last_withdraw_at,
            _has_wiref=has_wiref,
            _has_chair=has_chair,
        ).annotate(
            # Submitted iff there is a SUBMIT and (no WITHDRAW or SUBMIT > WITHDRAW)
            _is_submitted=ExpressionWrapper(
                Q(_last_submit_at__isnull=False) & (
                    Q(_last_withdraw_at__isnull=True) | Q(_last_submit_at__gt=F("_last_withdraw_at"))
                ),
                output_field=BooleanField(),
            ),
        )

        if v == "draft":
            # not submitted and no approvals
            return qs.filter(_is_submitted=False, _has_wiref=False, _has_chair=False)

        if v == "submitted":
            # submitted, but no approvals yet
            return qs.filter(_is_submitted=True, _has_wiref=False, _has_chair=False)

        if v == "approved_wiref":
            # wiref approved, but not final
            return qs.filter(_has_wiref=True, _has_chair=False)

        if v == "approved_all":
            # final chair approval present
            return qs.filter(_has_chair=True)

        return qs

@log_deletions
@with_help_widget
@admin.register(TimeSheet)
class TimeSheetAdmin(
    SimpleHistoryAdmin,
    DjangoObjectActions,
    ImportExportModelAdmin,
    ConcurrentModelAdmin,
    ManagerEditableGateMixin,
    ImportExportGuardMixin,
    HistoryGuardMixin
    ):
    resource_classes = [TimeSheetResource]
    list_display = (
        "status_text",        
        "employee",
        "period_label",
        "minutes_summary",
        "updated_at",
    )
    list_display_links = ("employee",)
    list_filter = (TimeSheetStateFilter, "year", "month",)
    search_fields = (
        "employee__person_role__person__last_name",
        "employee__person_role__person__first_name",
        "employee__person_role__role__name",
    )
    autocomplete_fields = ("employee",)
    readonly_fields = (
        "created_at",
        "updated_at",
        "pdf_file",
        "totals_preview",
        "work_calendar_preview",
        "leave_calendar_preview",
        "pto_infobox",
        "work_infobox",
        "signatures_box",
    )
    inlines = [AnnotationInline]

    fieldsets = (
        (_("Scope"), {"fields": ("employee", "year", "month", "totals_preview",)}),
        (_("Work Calendar"), {"fields": ("work_calendar_preview", "work_infobox")}),
        (_("Leave Calendar"), {"fields": ("leave_calendar_preview", "pto_infobox",)}),
        (_("Workflow & HankoSign"), {"fields": ("pdf_file", "signatures_box",),}),
        (_("System"), {"fields": ("version", "created_at", "updated_at")}),
    )

    @admin.display(description=_("Work Calendar"))
    def work_calendar_preview(self, obj):
        return self._render_calendar(obj, allow_kinds="work", show_kinds={"WORK", "OTHER"}, title=_("Work Calendar"), cal_type="wrk")

    
    @admin.display(description=_("Leave Calendar"))
    def leave_calendar_preview(self, obj):
        return self._render_calendar(obj, allow_kinds="leave", show_kinds={"LEAVE", "SICK"}, title=_("Leave Calendar"), cal_type="pto")

    # ---- server-rendered calendar preview (chips in cells, no day modal) ----
    def _render_calendar(self, obj, *, allow_kinds: str, show_kinds: set[str], title: str, cal_type: str):
        from django.utils.translation import gettext_lazy as _t
        if not obj or not obj.pk:
            return _t("— save first to see the calendar —")

        request = getattr(self, "_req", None)   # <— pick up request
        is_locked = self._is_locked(request, obj)

        # ensure PTO year exists (unchanged)
        emp = obj.employee
        anchor = _date(obj.year, obj.month, min(15, 28))
        label_year = EmployeeLeaveYear.pto_label_year_for(emp, anchor)
        EmployeeLeaveYear.ensure_for(emp, label_year)

        # month bounds
        month_start = _date(obj.year, obj.month, 1)
        if obj.month == 12:
            next_month_start = _date(obj.year + 1, 1, 1)
        else:
            next_month_start = _date(obj.year, obj.month + 1, 1)
        
        # Bucket entries per day, filtered by kind (unchanged)
        entries_by_day = {}
        qs = obj.entries.all().order_by("date", "id")
        for e in qs:
            if e.kind in show_kinds:
                entries_by_day.setdefault(e.date, []).append(e)

        # active holidays in this month
        hols = {d for d in obj._active_holidays()
                if d.year == obj.year and d.month == obj.month}

         # --- build ONLY weekday cells (Mon–Fri) with leading spacers ---
        cells: list[dict] = []

        # 1) find the first weekday *inside this month*
        first_weekday_date = month_start
        while first_weekday_date < next_month_start and first_weekday_date.weekday() >= 5:
            # skip Sat(5)/Sun(6)
            first_weekday_date += timedelta(days=1)

        # 2) how many leading spacers? (Mon=0..Fri=4)
        if first_weekday_date >= next_month_start:
            start_col = 0  # degenerate month (all weekend) – shouldn't happen, but safe
        else:
            start_col = first_weekday_date.weekday()  # 0..6, but here guaranteed 0..4

        for _ in range(start_col):
            cells.append({"spacer": True})

        # 3) add all Mon–Fri days as cells
        weekday_count = 0
        d = first_weekday_date
        while d < next_month_start:
            if d.weekday() < 5:  # Mon..Fri
                evs = entries_by_day.get(d, [])
                items = [{
                    "id": e.id,
                    "kind": e.kind,
                    "kind_display": e.get_kind_display(),
                    "minutes": int(e.minutes or 0),
                    "comment": e.comment or "",
                } for e in evs]

                kind_class = "empty"
                if d in hols:
                    kind_class = "holiday"
                elif evs:
                    from collections import Counter
                    top = Counter([e.kind for e in evs]).most_common(1)[0][0]
                    kind_class = {
                        "WORK": "work",
                        "LEAVE": "leave",
                        "SICK": "sick",
                        "OTHER": "other",
                        "PUBHOL": "holiday",
                    }.get(top, "other")

                cells.append({
                    "spacer": False,
                    "date": d,
                    "in_month": True,
                    "is_today": d == _date.today(),
                    "is_holiday": d in hols,
                    "items": items,
                    "kind_class": kind_class,
                })
                weekday_count += 1
            d += timedelta(days=1)

        # 4) trailing spacers so the last row fills to 5 columns
        remainder = (start_col + weekday_count) % 5
        if remainder:
            for _ in range(5 - remainder):
                cells.append({"spacer": True})

        # Labels: Mon–Fri only (compact, locale-agnostic)
        weekday_labels = ["M", "T", "W", "T", "F"]

        month_label = date_format(month_start, "F Y", use_l10n=True)

        ctx = {
            "cal_type": cal_type,
            "title": title,
            "month_label": month_label,
            "weekday_labels": weekday_labels,
            "cells": cells,
            "timesheet_id": obj.pk,
            "is_locked": is_locked,
            "add_url_base": f'{reverse("admin:employees_timeentry_add")}?allow_kinds={allow_kinds}',
            "ts_change_url": reverse("admin:employees_timesheet_change", args=[obj.pk]),
        }
        html = render_to_string("admin/employees/timesheet_calendar.html", ctx)
        return mark_safe(html)

    
    def _is_locked(self, request, obj):
        if not obj:
            return False
        st = state_snapshot(obj)
        locked_by_status = st["locked"]   # << use the universal decision
        if request is None:
            return locked_by_status
        if self._is_manager(request):
            return False
        return locked_by_status


    # ---- computed displays ----
    @admin.display(description=_("Period"))
    def period_label(self, obj):
        return f"{obj.year}-{obj.month:02d}"
    

    @admin.display(description=_("Status"))
    def status_text(self, obj):
        return object_status_span(obj)   # emits <span class="js-state" data-state="...">Label</span>


    @admin.display(description=_("Minutes"))
    def minutes_summary(self, obj):
        t = int((obj.worked_minutes or 0) + (obj.credit_minutes or 0))
        e = int(obj.expected_minutes or 0)
        d = t - e
        return f"{t} / {e} (Δ {d})"


    @admin.display(description=_("Worktime overview"))
    def work_infobox(self, obj):
        from django.utils.translation import gettext_lazy as _t
        if not obj or not obj.pk:
            return _t("— save first to see worktime —")

        # Use the sheet’s maintained aggregates
        expected = int(obj.expected_minutes or 0)
        worked   = int(obj.worked_minutes   or 0)
        credit   = int(obj.credit_minutes   or 0)
        total    = worked + credit
        delta    = total - expected

        ctx = {
            "month_label": f"{obj.year}-{obj.month:02d}",
            "expected": expected,
            "worked": worked,
            "credit": credit,
            "total": total,
            "delta": delta,
            "delta_abs": abs(delta),
            "opening": int(obj.opening_saldo_minutes or 0),
            "closing": int(obj.closing_saldo_minutes or 0),
            "is_locked": self._is_locked(getattr(self, "_req", None), obj),
        }
        html = render_to_string("admin/employees/work_infobox.html", ctx)
        return mark_safe(html)


    @admin.display(description=_("PTO overview"))
    def pto_infobox(self, obj):
        from django.utils.translation import gettext_lazy as _t

        if not obj or not obj.pk:
            return _t("— save first to see PTO —")

        emp = obj.employee
        anchor = _date(obj.year, obj.month, min(15, 28))
        label_year = EmployeeLeaveYear.pto_label_year_for(emp, anchor)
        ly = EmployeeLeaveYear.ensure_for(emp, label_year)

        ctx = {
            "label_year": label_year,
            "period_label": f"{ly.period_start.strftime('%Y-%m-%d')} → {(ly.period_end - timedelta(days=1)).strftime('%Y-%m-%d')}",
            "daily": int(emp.daily_expected_minutes or 0),
            "ent":   int(ly.entitlement_minutes or 0),
            "carry": int(ly.carry_in_minutes or 0),
            "adj":   int(ly.manual_adjust_minutes or 0),
            "taken": int(ly.taken_minutes),
            "remain": int(ly.remaining_minutes),
            "remain_abs": abs(int(ly.remaining_minutes)),
        }
        html = render_to_string("admin/employees/pto_infobox.html", ctx)
        return mark_safe(html)


    @admin.display(description=_("Totals preview"))
    def totals_preview(self, obj):
        t = int((obj.worked_minutes or 0) + (obj.credit_minutes or 0))
        e = int(obj.expected_minutes or 0)
        d = t - e
        ctx = {"total": t, "expected": e, "delta": d}
        html = render_to_string("admin/employees/timesheet_totals.html", ctx)
        return mark_safe(html)



    @admin.display(description=_("Signatures"))
    def signatures_box(self, obj):
        return render_signatures_box(obj)


    def has_delete_permission(self, request, obj=None):
        return False


    change_actions = ("submit_timesheet", "withdraw_timesheet", "approve_wiref", "approve_chair", "reject_wiref", "reject_chair", "lock_timesheet", "unlock_timesheet", "print_timesheet",)
    def get_change_actions(self, request, object_id, form_url):
        actions = list(super().get_change_actions(request, object_id, form_url))
        obj = self.get_object(request, object_id)
        if not obj:
            return actions

        def drop(name):
            if name in actions:
                actions.remove(name)

        st = state_snapshot(obj)
        approved = st["approved"]
        explicit_locked = st["explicit_locked"]
        chair_ok = "CHAIR" in approved or st["final"]
        wiref_ok = "WIREF" in approved
        submitted = st["submitted"]

        # Lock/Unlock visibility
        if explicit_locked:
            drop("lock_timesheet")
        else:
            drop("unlock_timesheet")
        # (Optionally: only show lock if chair_ok, i.e. final milestone reached)
        if not chair_ok:
            drop("lock_timesheet")

        if chair_ok:
            for n in ("submit_timesheet","withdraw_timesheet","approve_wiref","approve_chair","reject_wiref","reject_chair"):
                drop(n)
            return actions

        if wiref_ok:
            drop("submit_timesheet")
            drop("withdraw_timesheet")
            drop("approve_wiref")
            # keep approve_chair / reject_chair
            return actions

        if submitted and not wiref_ok:
            drop("submit_timesheet")
            # keep withdraw_timesheet / approve_wiref / reject_wiref
            drop("approve_chair")
            drop("reject_chair")
            return actions

        # draft
        for n in ("withdraw_timesheet","approve_wiref","approve_chair","reject_wiref","reject_chair"):
            drop(n)
        return actions

    
    from datetime import date as _date
    @safe_admin_action
    def print_timesheet(self, request, obj):
        action = get_action("RELEASE:-@employees.timesheet")
        if not action:
            messages.error(request, _("Release action is not configured."))
            return
        sign_once(request, action, obj, note=_("Printed timesheet PDF"), window_seconds=10)
        emp = (
            Employee.objects.select_related("person_role__person", "person_role__role").get(pk=obj.employee_id)
        )
        anchor = _date(obj.year, obj.month, min(28, 15))  # mid-month anchor
        ly_label = EmployeeLeaveYear.pto_label_year_for(emp, anchor)
        ly = EmployeeLeaveYear.ensure_for(emp, ly_label)
        entries = obj.entries.order_by("date", "id")

        # Build data for the seal
        signatures = seal_signatures_context(obj)

        ctx = {
            "ts": obj,
            "org": OrgInfo.get_solo(),
            "employee": emp,
            "person": emp.person_role.person,
            "role": emp.person_role.role,
            "leave_year": ly,
            "leave_year_label": ly_label,
            "entries": entries,
            "signatures": signatures,
            'signers': [
                {'label': emp.person_role.person.last_name},
                {'label': 'WiRef'},
                {'label': 'Chair'},
            ]
        }
        return render_pdf_response(
            "employees/timesheet_pdf.html",
            ctx,
            request,
            f"JOURNAL_{emp.person_role.person.last_name}_{obj.year}-{obj.month:02d}.pdf",
        )
    print_timesheet.label = "🖨️ " + _("Print Timesheet PDF")
    print_timesheet.attrs = {"class": "btn btn-block btn-info","style": "margin-bottom: 1rem;","data-action": "post-object", "onclick": RID_JS}


    # --- workflow transitions ---
    # SUBMIT by ASS
    @transaction.atomic
    @safe_admin_action
    def submit_timesheet(self, request, obj):
        st = state_snapshot(obj)
        if st["submitted"]:
            messages.info(request, _("Already submitted."))
            return
        action = get_action("SUBMIT:ASS@employees.timesheet")
        if not action:
            messages.error(request, _("Submission action is not configured."))
            return
        record_signature(request, action, obj, note=_("Timesheet %(period)s submitted") % {"period": f"{obj.year}-{obj.month:02d}"})
        create_system_annotation(obj, "SUBMIT", user=request.user)
        messages.success(request, _("Timesheet submitted."))
    submit_timesheet.label = _("Submit")
    submit_timesheet.attrs = {"class": "btn btn-block btn-warning", "style": "margin-bottom: 1rem;",}


    # WITHDRAW by ASS (only if no approvals yet)
    @transaction.atomic
    @safe_admin_action
    def withdraw_timesheet(self, request, obj):
        st = state_snapshot(obj)
        if not st["submitted"]:
            messages.info(request, _("This timesheet hasn’t been submitted yet."))
            return
        if "WIREF" in st["approved"] or "CHAIR" in st["approved"]:
            messages.warning(request, _("Cannot withdraw after approvals."))
            return
        action = get_action("WITHDRAW:ASS@employees.timesheet")
        if not action:
            messages.error(request, _("Withdraw action is not configured."))
            return
        record_signature(request, action, obj, note=_("Timesheet %(period)s withdrawn") % {"period": f"{obj.year}-{obj.month:02d}"})
        create_system_annotation(obj, "WITHDRAW", user=request.user)
        messages.success(request, _("Submission withdrawn."))
    withdraw_timesheet.label = _("Withdraw submission")
    withdraw_timesheet.attrs = {"class": "btn btn-block btn-secondary", "style": "margin-bottom: 1rem;",}


    # APPROVE by WIREF
    @transaction.atomic
    @safe_admin_action
    def approve_wiref(self, request, obj):
        st = state_snapshot(obj)
        if not st["submitted"]:
            messages.warning(request, _("Submit first before approving."))
            return
        if "WIREF" in st["approved"]:
            messages.info(request, _("Already approved by WiRef."))
            return
        action = get_action("APPROVE:WIREF@employees.timesheet")
        if not action:
            messages.error(request, _("WiRef approval action is not configured."))
            return
        record_signature(request, action, obj, note=_("Timesheet %(period)s approved") % {"period": f"{obj.year}-{obj.month:02d}"})
        create_system_annotation(obj, "APPROVE", user=request.user)
        messages.success(request, _("Approved by WiRef."))
    approve_wiref.label = _("Approve (WiRef)")
    approve_wiref.attrs = {"class": "btn btn-block btn-success", "style": "margin-bottom: 1rem;",}


    # APPROVE by CHAIR
    @transaction.atomic
    @safe_admin_action
    def approve_chair(self, request, obj):
        st = state_snapshot(obj)
        if not st["submitted"]:
            messages.warning(request, _("Submit first before approving."))
            return
        if "CHAIR" in st["approved"]:
            messages.info(request, _("Already approved by Chair."))
            return
        action = get_action("APPROVE:CHAIR@employees.timesheet")
        if not action:
            messages.error(request, _("Chair approval action is not configured."))
            return
        record_signature(request, action, obj, note=_("Timesheet %(period)s approved") % {"period": f"{obj.year}-{obj.month:02d}"})
        create_system_annotation(obj, "APPROVE", user=request.user)
        messages.success(request, _("Approved by Chair."))
    approve_chair.label = _("Approve (Chair)")
    approve_chair.attrs = {"class": "btn btn-block btn-success", "style": "margin-bottom: 1rem;",}


    # REJECT by WIREF
    @transaction.atomic
    @safe_admin_action
    def reject_wiref(self, request, obj):
        st = state_snapshot(obj)
        if not st["submitted"]:
            messages.warning(request, _("Nothing to reject (not submitted)."))
            return
        if "CHAIR" in st["approved"]:
            messages.warning(request, _("Already final; cannot reject."))
            return
        action = get_action("REJECT:WIREF@employees.timesheet")
        if not action:
            messages.error(request, _("WiRef rejection action is not configured."))
            return
        record_signature(request, action, obj, note=_("Timesheet %(period)s rejected") % {"period": f"{obj.year}-{obj.month:02d}"})
        create_system_annotation(obj, "REJECT", user=request.user)
        messages.success(request, _("Rejected by WiRef."))
    reject_wiref.label = _("Reject (WiRef)")
    reject_wiref.attrs = {"class": "btn btn-block btn-danger", "style": "margin-bottom: 1rem;",}


    # REJECT by CHAIR
    @transaction.atomic
    @safe_admin_action
    def reject_chair(self, request, obj):
        st = state_snapshot(obj)
        if not st["submitted"]:
            messages.warning(request, _("Nothing to reject (not submitted)."))
            return
        if "CHAIR" in st["approved"]:
            messages.warning(request, _("Already final; cannot reject."))
            return
        action = get_action("REJECT:CHAIR@employees.timesheet")
        if not action:
            messages.error(request, _("Chair rejection action is not configured."))
            return
        record_signature(request, action, obj, note=_("Timesheet %(period)s rejected") % {"period": f"{obj.year}-{obj.month:02d}"})
        create_system_annotation(obj, "REJECT", user=request.user)
        messages.success(request, _("Rejected by Chair."))
    reject_chair.label = _("Reject (Chair)")
    reject_chair.attrs = {"class": "btn btn-block btn-danger", "style": "margin-bottom: 1rem;",}


    # LOCK Timesheet (CHAIR or WIREF)
    @transaction.atomic
    @safe_admin_action
    def lock_timesheet(self, request, obj):
        st = state_snapshot(obj)
        if st["explicit_locked"]:
            messages.info(request, _("Already locked."))
            return
        if not ("CHAIR" in st["approved"] or st["final"]):
            messages.warning(request, _("Locking is only available after final approval."))
            return
        action = get_action("LOCK:-@employees.timesheet")
        if not action:
            messages.error(request, _("Lock action is not configured."))
            return
        record_signature(request, action, obj, note=_("Timesheet %(period)s locked") % {"period": f"{obj.year}-{obj.month:02d}"})
        create_system_annotation(obj, "LOCK", user=request.user)
        messages.success(request, _("Locked."))
    lock_timesheet.label = _("Lock")
    lock_timesheet.attrs = {"class": "btn btn-block btn-secondary", "style": "margin-bottom: 1rem;"}


    @transaction.atomic
    @safe_admin_action
    def unlock_timesheet(self, request, obj):
        st = state_snapshot(obj)
        if not st["explicit_locked"]:
            messages.info(request, _("Not locked."))
            return
        action = get_action("UNLOCK:-@employees.timesheet")
        if not action:
            messages.error(request, _("Unlock action is not configured."))
            return
        record_signature(request, action, obj, note=_("Timesheet %(period)s unlocked") % {"period": f"{obj.year}-{obj.month:02d}"})
        create_system_annotation(obj, "UNLOCK", user=request.user)
        messages.success(request, _("Unlocked."))
    unlock_timesheet.label = _("Unlock")
    unlock_timesheet.attrs = {"class": "btn btn-block btn-warning", "style": "margin-bottom: 1rem;"}


    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj and not request.user.is_superuser:
            ro += ["employee", "year", "month"]
        return ro
    
    def render_change_form(self, request, context, *args, **kwargs):
        # Stash the request so display methods can read it
        self._req = request
        return super().render_change_form(request, context, *args, **kwargs)

    def get_inline_instances(self, request, obj=None):
        instances = super().get_inline_instances(request, obj)
        if not request.user.is_superuser:
            # hide the TimeEntry inline for non-SUs
            from .admin import TimeEntryInline  # if needed to avoid circulars; else remove this line
            instances = [i for i in instances if not isinstance(i, TimeEntryInline)]
        return instances


# =========================
# HolidayCalendar Admin
# =========================

@log_deletions
@with_help_widget
@admin.register(HolidayCalendar)
class HolidayCalendarAdmin(
    SimpleHistoryAdmin,
    ImportExportModelAdmin,
    ImportExportGuardMixin,
    ManagerEditableGateMixin,
    HistoryGuardMixin
    ):
    resource_classes = [HolidayCalendarResource]
    list_display = ("name", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (_("Basics"), {"fields": ("name", "is_active")}),
        (_("Rules"), {"fields": ("rules_text",)}),
        (_("System"), {"fields": (("created_at"), ("updated_at"),)}),
    )

    def get_actions(self, request):
        actions = super().get_actions(request)
        return actions

    def has_delete_permission(self, request, obj=None):
        return False


# =========================
# Keep TimeEntry out of the side menu
# =========================

@with_help_widget
@admin.register(TimeEntry)
class TimeEntryAdmin(
    SimpleHistoryAdmin,
    ImportExportModelAdmin,
    ConcurrentModelAdmin,
    ImportExportGuardMixin,
    HistoryGuardMixin
    ):
    resource_classes = [TimeEntryResource]
    form = TimeEntryAdminForm
    list_display = ("timesheet", "date", "minutes", "kind", "short_comment", "updated_at")
    list_filter = ("timesheet", "kind", "date",)
    search_fields = ("timesheet__employee__person_role__person__last_name", "comment")
    readonly_fields = ("created_at", "updated_at", )

    # Close Jazzmin modal / Django popup and refresh parent
    def _close_popup(self):
        return HttpResponse("""
<script>
try { window.top.location.reload(); } catch(e) {}
try { window.close(); } catch(e) {}
</script>
""")

    def response_add(self, request, obj, post_url_continue=None):
        # If opened as popup/modal, close & refresh parent
        if request.GET.get("_popup") or request.POST.get("_popup"):
            return self._close_popup()
        # If we passed a next=... param, go back to the timesheet
        nxt = request.GET.get("next") or request.POST.get("next")
        if nxt:
            return redirect(nxt)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if request.GET.get("_popup") or request.POST.get("_popup"):
            return self._close_popup()
        nxt = request.GET.get("next") or request.POST.get("next")
        if nxt:
            return redirect(nxt)
        return super().response_change(request, obj)

    def short_comment(self, obj):
        txt = obj.comment or ""
        return (txt[:60] + "…") if len(txt) > 60 else (txt or "—")
    short_comment.short_description = _("Comment")

    def get_form(self, request, obj=None, **kwargs):
        Form = super().get_form(request, obj, **kwargs)
        ts_id = request.GET.get("timesheet") or request.POST.get("timesheet")
        allow = (request.GET.get("allow_kinds") or request.POST.get("allow_kinds") or "").lower()
        kind_qs = request.GET.get("kind") or request.POST.get("kind")

        if "timesheet" in Form.base_fields and ts_id:
            f = Form.base_fields["timesheet"]
            f.initial = ts_id
            f.widget = forms.HiddenInput()
            f.disabled = False

        if "kind" in Form.base_fields:
            f = Form.base_fields["kind"]
            if allow == "work":
                f.choices = [c for c in f.choices if c[0] in ("WORK", "OTHER")]
                f.initial = "WORK"
            elif allow == "leave":
                f.choices = [c for c in f.choices if c[0] in ("LEAVE", "SICK")]
                f.initial = "LEAVE"
            if kind_qs and kind_qs in dict(f.choices):
                f.initial = kind_qs
                # if you want single-click modals, uncomment:
                # f.widget = forms.HiddenInput()
            if allow == "leave" and (kind_qs or len(f.choices) == 1):
                f.widget = forms.HiddenInput()
        
        is_leave_flow = (allow == "leave") or (obj and obj.kind in (TimeEntry.Kind.LEAVE, TimeEntry.Kind.SICK))
        if is_leave_flow:
            for name in ("minutes", "start_time", "end_time"):
                fld = Form.base_fields.get(name)
                if fld:
                    fld.required = False
                    fld.widget = forms.HiddenInput()
                    # also clear help_text to reduce clutter (optional)
                    fld.help_text = ""

        return Form

    def get_fields(self, request, obj=None):
        allow = (request.GET.get("allow_kinds") or request.POST.get("allow_kinds") or "").lower()
        # Leave/Sick flow → only the essentials
        if allow == "leave" or (obj and obj.kind in (TimeEntry.Kind.LEAVE, TimeEntry.Kind.SICK)):
            return ("timesheet", "date", "kind", "comment", "version")
        # Default (work/other) → full form
        return ("timesheet", "date", "kind", "start_time", "end_time", "minutes", "comment", "version")

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        ts = request.GET.get("timesheet")
        dt = request.GET.get("date")
        if ts:
            initial["timesheet"] = ts
        if dt:
            initial["date"] = dt
        return initial

    def get_model_perms(self, request):
        # Keep it off the sidebar
        return {}
    
    def save_model(self, request, obj, form, change):
        # if the FK is still missing, pull from GET/POST
        if not obj.timesheet_id:
            obj.timesheet_id = request.POST.get("timesheet") or request.GET.get("timesheet")
        super().save_model(request, obj, form, change)

    def _parent_locked(self, request, obj=None):
        try:
            ts = obj.timesheet if obj else None
            if not ts:
                ts_id = request.GET.get("timesheet") or request.POST.get("timesheet")
                if ts_id:
                    ts = TimeSheet.objects.filter(pk=ts_id).first()
            if not ts:
                return False
            # reuse TimeSheetAdmin’s rule (manager can bypass)
            ts_admin = self.admin_site._registry[TimeSheet]
            return ts_admin._is_locked(request, ts)
        except Exception:
            return False

    def has_add_permission(self, request):
        if self._parent_locked(request, None):
            return False
        return super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        if self._parent_locked(request, obj):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self._parent_locked(request, obj):
            return False
        return super().has_delete_permission(request, obj)


