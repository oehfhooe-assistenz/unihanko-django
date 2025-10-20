from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.shortcuts import redirect

from django_object_actions import DjangoObjectActions
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from simple_history.admin import SimpleHistoryAdmin

from core.admin_mixins import ImportExportGuardMixin
from core.pdf import render_pdf_response
from organisation.models import OrgInfo

from django.urls import reverse
from django.http import HttpResponse

# NEW: helpers for the server-rendered calendar
from datetime import date as _date, timedelta
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from django.utils.formats import date_format

from concurrency.admin import ConcurrentModelAdmin
from django import forms
from django.contrib.admin.widgets import AdminTimeWidget
from hankosign.utils import render_signatures_box

from .models import (
    Employee,
    EmploymentDocument,
    TimeSheet,
    TimeEntry,
    HolidayCalendar,
    EmployeeLeaveYear,
)

from django.core.exceptions import PermissionDenied
from hankosign.utils import record_signature, get_action, has_sig, sig_time, state_snapshot

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

class ManagerGateMixin:
    """Gate certain UI actions to managers only."""
    manager_group_name = "module:employees:manager"

    def _is_manager(self, request) -> bool:
        return request.user.groups.filter(name=self.manager_group_name).exists()


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

class TimeEntryInline(admin.TabularInline):

    model = TimeEntry
    form = TimeEntryAdminForm
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

class EmployeeLeaveYearInline(admin.TabularInline):
    model = EmployeeLeaveYear
    extra = 0
    can_delete = False
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
    inlines = [EmploymentDocumentInline, EmployeeLeaveYearInline]
    actions = ("export_selected_pdf",)

    fieldsets = (
        (_("Assignment"), {"fields": ("person_role", "is_active")}),
        (_("Work terms"), {"fields": ("weekly_hours", "saldo_minutes")}),
        (_("PTO terms"), {"fields": ("annual_leave_days_base", "annual_leave_days_extra", "leave_reset_override")}),
        (_("Miscellaneous"), {"fields": ("notes",)}),
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

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj and not request.user.is_superuser:
            ro += ["person_role", ]
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

@admin.register(EmploymentDocument)
class EmploymentDocumentAdmin(
    ConcurrentModelAdmin, ManagerGateMixin, ImportExportGuardMixin, DjangoObjectActions, ImportExportModelAdmin, SimpleHistoryAdmin
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
    readonly_fields = ("code", "created_at", "updated_at",)

    fieldsets = (
        (_("Link"), {"fields": ("employee",)}),
        (_("Document"), {"fields": ("kind", "title", "start_date", "end_date", "is_active", "pdf_file", "details")}),
        (_("System"), {"fields": ("code", "version", "created_at", "updated_at")}),
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

from django.contrib.contenttypes.models import ContentType
from django.db.models import Exists, OuterRef
from hankosign.models import Signature

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
        sub = Signature.objects.filter(
            content_type=ct,
            object_id=OuterRef("pk"),
            verb="SUBMIT",
            stage="ASS",
        )
        wi = Signature.objects.filter(
            content_type=ct,
            object_id=OuterRef("pk"),
            verb="APPROVE",
            stage="WIREF",
        )
        ch = Signature.objects.filter(
            content_type=ct,
            object_id=OuterRef("pk"),
            verb="APPROVE",
            stage="CHAIR",
        )

        qs = qs.annotate(
            _has_submit=Exists(sub),
            _has_wiref=Exists(wi),
            _has_chair=Exists(ch),
        )

        if v == "draft":
            return qs.filter(_has_submit=False)
        if v == "submitted":
            return qs.filter(_has_submit=True, _has_wiref=False, _has_chair=False)
        if v == "approved_wiref":
            return qs.filter(_has_wiref=True, _has_chair=False)
        if v == "approved_all":
            return qs.filter(_has_chair=True)
        return qs


@admin.register(TimeSheet)
class TimeSheetAdmin(
    ConcurrentModelAdmin, ManagerGateMixin, ImportExportGuardMixin, DjangoObjectActions, ImportExportModelAdmin, SimpleHistoryAdmin
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
        "pdf_file",
        "export_payload",
        "totals_preview",
        "work_calendar_preview",
        "leave_calendar_preview",
        "pto_infobox",
        "work_infobox",
        "signatures_box",
    )
    inlines = []
    actions = ("export_selected_pdf",)

    fieldsets = (
        (_("Scope"), {"fields": ("employee", ("year", "month"))}),
        (_("Work Calendar"), {"fields": ("work_calendar_preview", "work_infobox")}),
        (_("Leave Calendar"), {"fields": ("leave_calendar_preview", "pto_infobox",)}),
        (_("HankoSign Workflow"), {"fields": ("signatures_box",),}),
        (_("Exports"), {"fields": ("pdf_file", "export_payload", "totals_preview")}),
        (_("Timestamps"), {"fields": (("version"), ("created_at"), ("updated_at"))}),
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

        emp = obj.employee
        anchor = _date(obj.year, obj.month, min(15, 28))
        label_year = EmployeeLeaveYear.pto_label_year_for(emp, anchor)
        EmployeeLeaveYear.ensure_for(emp, label_year)

        month_start = _date(obj.year, obj.month, 1)
        lead = (month_start.weekday() - 0) % 7  # Monday=0
        grid_start = month_start - timedelta(days=lead)

        # Bucket entries per day, but only show selected kinds
        entries_by_day = {}
        qs = obj.entries.all().order_by("date", "id")
        for e in qs:
            if e.kind in show_kinds:
                entries_by_day.setdefault(e.date, []).append(e)

        hols = {d for d in obj._active_holidays()
                if d.year == obj.year and d.month == obj.month}

        cells = []
        d = grid_start
        for _ in range(42):
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
                "is_holiday": d in hols,
                "items": items,
                "kind_class": kind_class,
            })
            d += timedelta(days=1)

        month_label = date_format(month_start, "F Y", use_l10n=True)
        base_monday = _date(2024, 1, 1)  # a Monday
        weekday_labels = [
            date_format(base_monday + timedelta(days=i), "D", use_l10n=True)[:1]
            for i in range(7)
        ]
        ctx = {
            "cal_type": cal_type,
            "title": title,
            "month_label": month_label,
            "weekday_labels": weekday_labels,
            "cells": cells,
            "timesheet_id": obj.pk,
            "is_locked": is_locked,
            # IMPORTANT: pass allow_kinds to constrain the modal form choices
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
    

    # temporary update, I would like to do this with bootstrap's table-cols or "universal" ribbons instead of monolithic per-module-badges
    @admin.display(description=_("Status"))
    def status_badge(self, obj):
        st = state_snapshot(obj)
        approved = st["approved"]
        if st["final"] or "CHAIR" in approved:
            return format_html('<span class="badge" style="background:#16a34a;color:#fff;">{}</span>', _("Final"))
        if "WIREF" in approved:
            return format_html('<span class="badge" style="background:#0ea5e9;color:#fff;">{}</span>', _("Approved (WiRef)"))
        if st["submitted"]:
            return format_html('<span class="badge" style="background:#f59e0b;color:#fff;">{}</span>', _("Submitted"))
        return format_html('<span class="badge" style="background:#6b7280;color:#fff;">{}</span>', _("Draft"))


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
        from django.utils.safestring import mark_safe
        from django.template.loader import render_to_string
        from datetime import timedelta

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
        return format_html(
            "<pre style='margin:.5rem 0; font-size:12px;'>"
            "total: {} min\nexpected: {} min\ndelta: {} min</pre>",
            t, e, d
        )


    @admin.display(description=_("Signatures"))
    def signatures_box(self, obj):
        return render_signatures_box(obj)


    def has_delete_permission(self, request, obj=None):
        return False


    change_actions = ("submit_timesheet", "withdraw_timesheet", "approve_wiref", "approve_chair", "reject_wiref", "reject_chair")

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
        chair_ok = "CHAIR" in approved or st["final"]
        wiref_ok = "WIREF" in approved
        submitted = st["submitted"]

        if chair_ok:
            for n in ("submit_timesheet","withdraw_timesheet","approve_wiref","approve_chair","reject_wiref","reject_chair"):
                drop(n)
            return actions

        if wiref_ok and not chair_ok:
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



    def print_pdf(self, request, obj):
        ctx = {"ts": obj, "org": OrgInfo.get_solo()}
        return render_pdf_response(
            "employee/timesheet_pdf.html",
            ctx,
            request,
            f"timesheet_{obj.employee_id}_{obj.year}-{obj.month:02d}.pdf",
        )

    print_pdf.label = "🖨️ " + _("Print Timesheet PDF")
    print_pdf.attrs = {"class": "btn btn-block btn-secondary btn-sm","style": "margin-bottom: 1rem;",}


    @admin.action(description=_("Print selected as Timesheet overview PDF"))
    def export_selected_pdf(self, request, queryset):
        rows = queryset.select_related("employee__person_role__person", "employee__person_role__role").order_by(
            "-year", "-month"
        )
        ctx = {"rows": rows, "org": OrgInfo.get_solo()}
        return render_pdf_response("employee/timesheets_list_pdf.html", ctx, request, "timesheets_selected.pdf")


    # --- workflow transitions ---
    from django.core.exceptions import PermissionDenied

    # SUBMIT by ASS
    def submit_timesheet(self, request, obj):
        st = state_snapshot(obj)
        if st["submitted"]:
            messages.info(request, _("Already submitted."))
            return

        action = get_action("SUBMIT:ASS@employees.timesheet")
        if not action:
            messages.error(request, _("Submission action is not configured."))
            return

        try:
            record_signature(
                request.user, action, obj,
                note=_("Timesheet %(period)s submitted") % {"period": f"{obj.year}-{obj.month:02d}"}
            )
        except PermissionDenied as e:
            messages.error(request, str(e))
            return

        messages.success(request, _("Timesheet submitted."))

    submit_timesheet.label = _("Submit")
    submit_timesheet.attrs = {"class": "btn btn-block btn-warning btn-sm", "style": "margin-bottom: 1rem;",}


    # WITHDRAW by ASS (only if no approvals yet)
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

        try:
            record_signature(
                request.user, action, obj,
                note=_("Timesheet %(period)s withdrawn") % {"period": f"{obj.year}-{obj.month:02d}"}
            )
        except PermissionDenied as e:
            messages.error(request, str(e))
            return

        messages.success(request, _("Submission withdrawn."))

    withdraw_timesheet.label = _("Withdraw submission")
    withdraw_timesheet.attrs = {"class": "btn btn-block btn-secondary btn-sm", "style": "margin-bottom: 1rem;",}


    # APPROVE by WIREF
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

        try:
            record_signature(
                request.user, action, obj,
                note=_("Timesheet %(period)s approved") % {"period": f"{obj.year}-{obj.month:02d}"}
            )
        except PermissionDenied as e:
            messages.error(request, str(e))
            return

        messages.success(request, _("Approved by WiRef."))

    approve_wiref.label = _("Approve (WiRef)")
    approve_wiref.attrs = {"class": "btn btn-block btn-success btn-sm", "style": "margin-bottom: 1rem;",}


    # APPROVE by CHAIR
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

        try:
            record_signature(
                request.user, action, obj,
                note=_("Timesheet %(period)s approved") % {"period": f"{obj.year}-{obj.month:02d}"}
            )
        except PermissionDenied as e:
            messages.error(request, str(e))
            return

        messages.success(request, _("Approved by Chair."))

    approve_chair.label = _("Approve (Chair)")
    approve_chair.attrs = {"class": "btn btn-block btn-success btn-sm", "style": "margin-bottom: 1rem;",}

    # REJECT by WIREF
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

        try:
            record_signature(
                request.user, action, obj,
                note=_("Timesheet %(period)s rejected") % {"period": f"{obj.year}-{obj.month:02d}"}
            )
        except PermissionDenied as e:
            messages.error(request, str(e))
            return

        messages.success(request, _("Rejected by WiRef."))

    reject_wiref.label = _("Reject (WiRef)")
    reject_wiref.attrs = {"class": "btn btn-block btn-danger btn-sm", "style": "margin-bottom: 1rem;",}


    # REJECT by CHAIR
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

        try:
            record_signature(
                request.user, action, obj,
                note=_("Timesheet %(period)s rejected") % {"period": f"{obj.year}-{obj.month:02d}"}
            )
        except PermissionDenied as e:
            messages.error(request, str(e))
            return

        messages.success(request, _("Rejected by Chair."))

    reject_chair.label = _("Reject (Chair)")
    reject_chair.attrs = {"class": "btn btn-block btn-danger btn-sm", "style": "margin-bottom: 1rem;",}


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
class TimeEntryAdmin(ConcurrentModelAdmin, ImportExportGuardMixin, ImportExportModelAdmin):
    resource_classes = [TimeEntryResource]
    form = TimeEntryAdminForm
    list_display = ("timesheet", "date", "minutes", "kind", "short_comment", "updated_at")
    list_filter = ("timesheet", "kind", "date")
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
    

