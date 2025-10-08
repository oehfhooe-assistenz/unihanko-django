from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _, get_language
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from datetime import datetime as _dt

from django_object_actions import DjangoObjectActions
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from simple_history.admin import SimpleHistoryAdmin

from core.admin_mixins import ImportExportGuardMixin
from core.pdf import render_pdf_response
from organisation.models import OrgInfo

from django.urls import path, reverse
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.utils.dateparse import parse_date
import json

from django.utils.decorators import method_decorator
from django.middleware.csrf import get_token
from django.forms.models import model_to_dict

# NEW: helpers for the server-rendered calendar
from calendar import monthrange
from datetime import date as _date, timedelta
from collections import Counter
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from django.utils.formats import date_format

from .models import (
    Employee,
    EmploymentDocument,
    TimeSheet,
    TimeEntry,
    HolidayCalendar,
)

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
            "submitted_at",
            "approved_at_wiref",
            "approved_at_chair",
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

class ManagerGateMixin:
    """Gate certain UI actions to managers only."""
    manager_group_name = "module:employees:manager"

    def _is_manager(self, request) -> bool:
        return request.user.groups.filter(name=self.manager_group_name).exists()


# =========================
# Inlines
# =========================

class TimeEntryInline(admin.TabularInline):
    model = TimeEntry
    extra = 0
    fields = ("date", "minutes", "kind", "comment")
    readonly_fields = ()
    can_delete = True
    show_change_link = False
    ordering = ("date",)

    def get_max_num(self, request, obj=None, **kwargs):
        return 200


class EmploymentDocumentInline(admin.StackedInline):
    model = EmploymentDocument
    extra = 0
    fields = ("kind", "title", "start_date", "end_date", "is_active", "pdf_file", "code")
    readonly_fields = ("code",)
    can_delete = False
    show_change_link = True


# =========================
# Employee Admin
# =========================

@admin.register(Employee)
class EmployeeAdmin(
    ManagerGateMixin, ImportExportGuardMixin, DjangoObjectActions, ImportExportModelAdmin, SimpleHistoryAdmin
):
    resource_classes = [EmployeeResource]
    list_display = (
        "person_role",
        "weekly_hours",
        "saldo_display",
        "active_badge",
        "updated_at",
    )
    list_filter = ("is_active",)
    search_fields = (
        "person_role__person__last_name",
        "person_role__person__first_name",
        "person_role__role__name",
    )
    autocomplete_fields = ("person_role",)
    readonly_fields = ("created_at", "updated_at")
    inlines = [EmploymentDocumentInline]
    actions = ("export_selected_pdf",)

    fieldsets = (
        (_("Assignment"), {"fields": ("person_role", "is_active")}),
        (_("Work terms"), {"fields": ("weekly_hours", "saldo_minutes")}),
        (_("Timestamps"), {"fields": (("created_at"), ("updated_at"),)}),
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
    def active_badge(self, obj):
        if obj.is_active:
            return format_html('<span class="badge" style="background:#10b981;color:#fff;">{}</span>', _("Active"))
        return format_html('<span class="badge" style="background:#6b7280;color:#fff;">{}</span>', _("Inactive"))

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description=_("Print selected as Employee roster PDF"))
    def export_selected_pdf(self, request, queryset):
        rows = queryset.select_related("person_role__person", "person_role__role").order_by(
            "person_role__person__last_name", "person_role__person__first_name"
        )
        ctx = {"rows": rows, "org": OrgInfo.get_solo()}
        return render_pdf_response("employee/employee_list_pdf.html", ctx, request, "employees_selected.pdf")

    change_actions = ("print_pdf",)

    def print_pdf(self, request, obj):
        ctx = {"emp": obj, "org": OrgInfo.get_solo()}
        return render_pdf_response("employee/employee_pdf.html", ctx, request, f"employee_{obj.id}.pdf")

    print_pdf.label = _("🧾 Print Employee PDF")
    print_pdf.attrs = {"class": "btn btn-block btn-secondary btn-sm"}


# =========================
# EmploymentDocument Admin
# =========================

@admin.register(EmploymentDocument)
class EmploymentDocumentAdmin(
    ManagerGateMixin, ImportExportGuardMixin, DjangoObjectActions, ImportExportModelAdmin, SimpleHistoryAdmin
):
    resource_classes = [EmploymentDocumentResource]
    list_display = ("code", "employee", "kind_badge", "title", "period_display", "is_active", "updated_at")
    list_filter = ("kind", "is_active", "start_date", "end_date")
    search_fields = (
        "code",
        "title",
        "employee__person_role__person__last_name",
        "employee__person_role__person__first_name",
        "employee__person_role__role__name",
    )
    autocomplete_fields = ("employee",)
    readonly_fields = ("code", "created_at", "updated_at")

    fieldsets = (
        (_("Link"), {"fields": ("employee",)}),
        (_("Document"), {"fields": ("kind", "title", "start_date", "end_date", "is_active", "pdf_file", "details")}),
        (_("System"), {"fields": ("code", "created_at", "updated_at")}),
    )

    @admin.display(description=_("Kind"))
    def kind_badge(self, obj):
        colors = {
            obj.Kind.DV: "#2563eb",
            obj.Kind.ZV: "#10b981",
            obj.Kind.AA: "#f59e0b",
            obj.Kind.KM: "#ef4444",
            obj.Kind.ZZ: "#6b7280",
        }
        return format_html(
            '<span class="badge" style="background:{};color:#fff;">{}</span>',
            colors.get(obj.kind, "#6b7280"),
            obj.get_kind_display(),
        )

    @admin.display(description=_("Period"))
    def period_display(self, obj):
        s = obj.start_date.strftime("%Y-%m-%d") if obj.start_date else "—"
        e = obj.end_date.strftime("%Y-%m-%d") if obj.end_date else "…"
        return f"{s} → {e}"

    def has_delete_permission(self, request, obj=None):
        return False

    change_actions = ("print_receipt", "print_leave_request")

    def get_change_actions(self, request, object_id, form_url):
        actions = list(super().get_change_actions(request, object_id, form_url))
        obj = self.get_object(request, object_id)
        if not obj:
            return actions
        if obj.kind != obj.Kind.AA and "print_leave_request" in actions:
            actions.remove("print_leave_request")
        return actions

    def print_receipt(self, request, obj):
        ctx = {"doc": obj, "org": OrgInfo.get_solo()}
        return render_pdf_response(
            "employee/docs/document_receipt_pdf.html",
            ctx,
            request,
            f"{obj.kind}_{obj.code or obj.id}.pdf",
        )

    print_receipt.label = "🧾 " + _("Print document receipt")
    print_receipt.attrs = {"class": "btn btn-block btn-secondary btn-sm"}

    def print_leave_request(self, request, obj):
        ctx = {"doc": obj, "org": OrgInfo.get_solo()}
        s = obj.start_date.strftime("%Y-%m-%d") if obj.start_date else ""
        e = obj.end_date.strftime("%Y-%m-%d") if obj.end_date else ""
        title = f"Urlaubsantrag {s}–{e}" if s and e else f"Urlaubsantrag_{obj.code or obj.id}"
        return render_pdf_response("employee/docs/leave_request_pdf.html", ctx, request, f"{title}.pdf")

    print_leave_request.label = "🏖️ " + _("Print leave request PDF")
    print_leave_request.attrs = {"class": "btn btn-block btn-warning btn-sm"}


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
        if v == "draft":
            return qs.filter(submitted_at__isnull=True)
        if v == "submitted":
            return qs.filter(submitted_at__isnull=False, approved_at_wiref__isnull=True)
        if v == "approved_wiref":
            return qs.filter(approved_at_wiref__isnull=False, approved_at_chair__isnull=True)
        if v == "approved_all":
            return qs.filter(approved_at_chair__isnull=False)
        return qs


@admin.register(TimeSheet)
class TimeSheetAdmin(
    ManagerGateMixin, ImportExportGuardMixin, DjangoObjectActions, ImportExportModelAdmin, SimpleHistoryAdmin
):
    resource_classes = [TimeSheetResource]
    list_display = (
        "employee",
        "period_label",
        "status_badge",
        "minutes_summary",
        "updated_at",
    )
    list_filter = (TimeSheetStateFilter, "year", "month")
    search_fields = (
        "employee__person_role__person__last_name",
        "employee__person_role__person__first_name",
        "employee__person_role__role__name",
    )
    autocomplete_fields = ("employee",)
    readonly_fields = (
        "created_at",
        "updated_at",
        "submitted_at",
        "approved_at_wiref",
        "approved_at_chair",
        "pdf_file",
        "export_payload",
        "totals_preview",
        "calendar_preview",
    )
    inlines = [TimeEntryInline]
    actions = ("export_selected_pdf",)

    fieldsets = (
        (_("Scope"), {"fields": ("employee", ("year", "month"))}),
        (_("Calendar"), {"fields": ("calendar_preview",)}),
        (_("Workflow"), {"fields": ("submitted_at", "approved_at_wiref", "approved_at_chair")}),
        (_("Exports"), {"fields": ("pdf_file", "export_payload", "totals_preview")}),
        (_("Timestamps"), {"fields": (("created_at"), ("updated_at"))}),
    )

    # ---- server-rendered calendar preview (chips in cells, no day modal) ----
    @admin.display(description=_("Calendar"))
    def calendar_preview(self, obj):
        if not obj or not obj.pk:
            return _("— save first to see the calendar —")

        month_start = _date(obj.year, obj.month, 1)
        lead = (month_start.weekday() - 0) % 7  # Monday=0
        grid_start = month_start - timedelta(days=lead)

        # Bucket entries per day (ordered)
        entries_by_day = {}
        for e in obj.entries.all().order_by("date", "id"):
            entries_by_day.setdefault(e.date, []).append(e)

        # Active holidays in this month
        hols = {d for d in obj._active_holidays()
                if d.year == obj.year and d.month == obj.month}

        cells = []
        d = grid_start
        for _ in range(42):  # 6x7 grid
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
                "date": d,
                "in_month": (d.month == obj.month),
                "is_weekend": d.weekday() >= 5,
                "is_today": d == _date.today(),
                "items": items,               # <-- chips to render
                "kind_class": kind_class,
            })
            d += timedelta(days=1)

        from django.utils.formats import date_format
        month_label = date_format(month_start, "F Y", use_l10n=True)
        base_monday = _date(2024, 1, 1)  # a Monday
        weekday_labels = [
            date_format(base_monday + timedelta(days=i), "D", use_l10n=True)[:1]
            for i in range(7)
        ]

        ctx = {
            "month_label": month_label,
            "weekday_labels": weekday_labels,
            "cells": cells,
            "timesheet_id": obj.pk,
            "add_url_base": reverse("admin:employees_timeentry_add"),
            "ts_change_url": reverse("admin:employees_timesheet_change", args=[obj.pk]),
        }
        html = render_to_string("admin/employees/timesheet_calendar.html", ctx)
        return mark_safe(html)


    # ---- computed displays ----
    @admin.display(description=_("Period"))
    def period_label(self, obj):
        return f"{obj.year}-{obj.month:02d}"

    @admin.display(description=_("Status"))
    def status_badge(self, obj):
        if obj.approved_at_chair:
            return format_html('<span class="badge" style="background:#16a34a;color:#fff;">{}</span>', _("Final"))
        if obj.approved_at_wiref:
            return format_html('<span class="badge" style="background:#0ea5e9;color:#fff;">{}</span>', _("Approved (WiRef)"))
        if obj.submitted_at:
            return format_html('<span class="badge" style="background:#f59e0b;color:#fff;">{}</span>', _("Submitted"))
        return format_html('<span class="badge" style="background:#6b7280;color:#fff;">{}</span>', _("Draft"))

    @admin.display(description=_("Minutes"))
    def minutes_summary(self, obj):
        t = int((obj.worked_minutes or 0) + (obj.credit_minutes or 0))
        e = int(obj.expected_minutes or 0)
        d = t - e
        return f"{t} / {e} (Δ {d})"

    @admin.display(description=_("Totals preview"))
    def totals_preview(self, obj):
        t = int((obj.worked_minutes or 0) + (obj.credit_minutes or 0))
        e = int(obj.expected_minutes or 0)
        d = t - e
        return format_html(
            "<pre style='margin:.5rem 0; font-size:12px;'>"
            "total: {} min\nexpected: {} min\ndelta: {} min</pre>",
            t, e, d
        )

    def has_delete_permission(self, request, obj=None):
        return False

    change_actions = ("submit_timesheet", "withdraw_submission", "approve_wiref", "approve_chair", "print_pdf")

    def get_change_actions(self, request, object_id, form_url):
        actions = list(super().get_change_actions(request, object_id, form_url))
        obj = self.get_object(request, object_id)
        if not obj:
            return actions

        def drop(name):
            if name in actions:
                actions.remove(name)

        if obj.approved_at_chair:
            for n in ("submit_timesheet", "withdraw_submission", "approve_wiref", "approve_chair"):
                drop(n)
        elif obj.approved_at_wiref:
            drop("submit_timesheet")
            if not self._is_manager(request):
                drop("withdraw_submission")
                drop("approve_chair")
        elif obj.submitted_at:
            drop("submit_timesheet")
            if not self._is_manager(request):
                drop("withdraw_submission")
                drop("approve_wiref")
        else:
            for n in ("withdraw_submission", "approve_wiref", "approve_chair"):
                drop(n)

        return actions

    def print_pdf(self, request, obj):
        ctx = {"ts": obj, "org": OrgInfo.get_solo()}
        return render_pdf_response(
            "employee/timesheet_pdf.html",
            ctx,
            request,
            f"timesheet_{obj.employee_id}_{obj.year}-{obj.month:02d}.pdf",
        )

    print_pdf.label = "🖨️ " + _("Print Timesheet PDF")
    print_pdf.attrs = {"class": "btn btn-block btn-secondary btn-sm"}

    @admin.action(description=_("Print selected as Timesheet overview PDF"))
    def export_selected_pdf(self, request, queryset):
        rows = queryset.select_related("employee__person_role__person", "employee__person_role__role").order_by(
            "-year", "-month"
        )
        ctx = {"rows": rows, "org": OrgInfo.get_solo()}
        return render_pdf_response("employee/timesheets_list_pdf.html", ctx, request, "timesheets_selected.pdf")

    # --- workflow transitions ---
    def submit_timesheet(self, request, obj):
        if obj.submitted_at:
            messages.info(request, _("Already submitted."))
            return
        obj.submitted_at = timezone.now()
        obj.save(update_fields=["submitted_at", "updated_at"])
        messages.success(request, _("Timesheet submitted."))

    submit_timesheet.label = _("Submit")
    submit_timesheet.attrs = {"class": "btn btn-block btn-warning btn-sm"}

    def withdraw_submission(self, request, obj):
        if not self._is_manager(request):
            messages.warning(request, _("You don’t have permission to withdraw submissions."))
            return
        if obj.approved_at_wiref or obj.approved_at_chair:
            messages.warning(request, _("Cannot withdraw after approvals."))
            return
        if not obj.submitted_at:
            messages.info(request, _("This timesheet hasn’t been submitted yet."))
            return
        obj.submitted_at = None
        obj.save(update_fields=["submitted_at", "updated_at"])
        messages.success(request, _("Submission withdrawn."))

    withdraw_submission.label = _("Withdraw submission")
    withdraw_submission.attrs = {"class": "btn btn-block btn-secondary btn-sm"}

    def approve_wiref(self, request, obj):
        if not self._is_manager(request):
            messages.warning(request, _("You don’t have permission to approve (WiRef)."))
            return
        if not obj.submitted_at:
            messages.warning(request, _("Submit first before approving."))
            return
        if obj.approved_at_wiref:
            messages.info(request, _("Already approved by WiRef."))
            return
        obj.approved_at_wiref = timezone.now()
        obj.save(update_fields=["approved_at_wiref", "updated_at"])
        messages.success(request, _("Approved by WiRef."))

    approve_wiref.label = _("Approve (WiRef)")
    approve_wiref.attrs = {"class": "btn btn-block btn-success btn-sm"}

    def approve_chair(self, request, obj):
        if not self._is_manager(request):
            messages.warning(request, _("You don’t have permission to approve (Chair)."))
            return
        if not obj.approved_at_wiref:
            messages.warning(request, _("WiRef must approve before Chair approval."))
            return
        if obj.approved_at_chair:
            messages.info(request, _("Already approved by Chair."))
            return
        obj.approved_at_chair = timezone.now()
        obj.save(update_fields=["approved_at_chair", "updated_at"])
        messages.success(request, _("Approved by Chair."))

    approve_chair.label = _("Approve (Chair)")
    approve_chair.attrs = {"class": "btn btn-block btn-success btn-sm"}

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj and not request.user.is_superuser:
            ro += ["employee", "year", "month"]
        return ro


# =========================
# HolidayCalendar Admin
# =========================

@admin.register(HolidayCalendar)
class HolidayCalendarAdmin(ImportExportGuardMixin, ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [HolidayCalendarResource]
    list_display = ("name", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (_("Basics"), {"fields": ("name", "is_active")}),
        (_("Rules"), {"fields": ("rules_text",)}),
        (_("Timestamps"), {"fields": (("created_at"), ("updated_at"),)}),
    )

    def get_actions(self, request):
        actions = super().get_actions(request)
        return actions

    def has_delete_permission(self, request, obj=None):
        return False


# =========================
# Keep TimeEntry out of the side menu
# =========================

@admin.register(TimeEntry)
class TimeEntryAdmin(ImportExportGuardMixin, ImportExportModelAdmin):
    resource_classes = [TimeEntryResource]
    list_display = ("timesheet", "date", "minutes", "kind", "short_comment", "updated_at")
    list_filter = ("timesheet", "kind", "date")
    search_fields = ("timesheet__employee__person_role__person__last_name", "comment")
    autocomplete_fields = ("timesheet",)
    readonly_fields = ("created_at", "updated_at")

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