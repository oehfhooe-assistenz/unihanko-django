# employees/admin.py
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _, get_language
from django.db import IntegrityError, transaction

from django_object_actions import DjangoObjectActions
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from simple_history.admin import SimpleHistoryAdmin

from core.admin_mixins import ImportExportGuardMixin
from core.pdf import render_pdf_response
from organisation.models import OrgInfo

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
        # Keep inline manageable; you can tweak/remove this.
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
        # Show hours:minutes with sign, e.g. +03:15 or −01:30
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

    # PDF roster export
    @admin.action(description=_("Print selected as Employee roster PDF"))
    def export_selected_pdf(self, request, queryset):
        rows = queryset.select_related("person_role__person", "person_role__role").order_by(
            "person_role__person__last_name", "person_role__person__first_name"
        )
        ctx = {"rows": rows, "org": OrgInfo.get_solo()}
        return render_pdf_response("employee/employee_list_pdf.html", ctx, request, "employees_selected.pdf")

    # Object action: single employee summary PDF
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
            obj.Kind.DV: "#2563eb",   # blue
            obj.Kind.ZV: "#10b981",   # green
            obj.Kind.AA: "#f59e0b",   # amber
            obj.Kind.KM: "#ef4444",   # red
            obj.Kind.ZZ: "#6b7280",   # gray
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

    # --- Object actions: PDFs ---
    change_actions = ("print_receipt", "print_leave_request")

    def get_change_actions(self, request, object_id, form_url):
        actions = list(super().get_change_actions(request, object_id, form_url))
        obj = self.get_object(request, object_id)
        if not obj:
            return actions
        # Only show the specific AA form for leave requests
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
        # AA only
        ctx = {"doc": obj, "org": OrgInfo.get_solo()}
        # Fancy filename: e.g. Urlaubsantrag 2025-10-14–2025-10-15
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

from django.urls import path, reverse
from django.http import JsonResponse

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

    @admin.display(description=_("Calendar"))
    def calendar_preview(self, obj):
        if not obj or not obj.pk:
            return _("— save first to see the calendar —")
        url = reverse("admin:employees_timesheet_calendar", args=[obj.pk])
        initial = f"{obj.year}-{obj.month:02d}-01"
        return format_html(
            '<div id="ts-calendar" '
            'data-json-url="{}" '
            'data-initial="{}" '
            'style="min-height:420px;border:1px solid #374151;border-radius:6px;padding:8px;"></div>',
            url, initial
        )
    

    def get_urls(self):
        urls = super().get_urls()
        my = [
            path("<int:object_id>/calendar.json",
                self.admin_site.admin_view(self.calendar_json),
                name="employees_timesheet_calendar"),
        ]
        return my + urls
    

    def calendar_json(self, request, object_id):
        ts = self.get_object(request, object_id)
        if not ts:
            return JsonResponse([], safe=False)

        events = []
        colors = {
            "WORK":   "#22c55e",
            "LEAVE":  "#f59e0b",
            "SICK":   "#ef4444",
            "PUBHOL": "#64748b",
            "OTHER":  "#93c5fd",
        }

        # entries → events
        for e in ts.entries.all():
            title = e.get_kind_display()
            if e.minutes:
                title += f" · {e.minutes}m"
            events.append({
                "title": title,
                "start": e.date.isoformat(),
                "allDay": True,
                "color": colors.get(e.kind, "#93c5fd"),
            })

        # holidays → background events
        hols = ts._active_holidays()  # your helper
        for d in sorted(hols):
            if d.year == ts.year and d.month == ts.month:
                events.append({
                    "title": "Public holiday",
                    "start": d.isoformat(),
                    "allDay": True,
                    "display": "background",
                    "backgroundColor": "#e5e7eb",
                })

        return JsonResponse(events, safe=False)

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

    # in TimesheetAdmin
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

    # --- PDF: single + bulk ---
    change_actions = ("submit_timesheet", "withdraw_submission", "approve_wiref", "approve_chair", "print_pdf")

    def get_change_actions(self, request, object_id, form_url):
        actions = list(super().get_change_actions(request, object_id, form_url))
        obj = self.get_object(request, object_id)
        if not obj:
            return actions

        # Default visibility by state
        def drop(name):
            if name in actions:
                actions.remove(name)

        if obj.approved_at_chair:
            # fully done → just print
            for n in ("submit_timesheet", "withdraw_submission", "approve_wiref", "approve_chair"):
                drop(n)
        elif obj.approved_at_wiref:
            # WiRef approved → chair can approve; allow withdraw to managers only
            drop("submit_timesheet")
            if not self._is_manager(request):
                drop("withdraw_submission")
                # leave "approve_chair" visible only if manager
                drop("approve_chair")
        elif obj.submitted_at:
            # submitted → WiRef may approve; allow withdraw/approve for managers only
            drop("submit_timesheet")
            if not self._is_manager(request):
                drop("withdraw_submission")
                drop("approve_wiref")
        else:
            # draft → only submit
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
        # Optional: only allow toggling active via edit form; avoid bulk surprises
        return actions

    def has_delete_permission(self, request, obj=None):
        return False


# =========================
# Keep TimeEntry out of the side menu
# =========================

@admin.register(TimeEntry)
class TimeEntryAdmin(ImportExportGuardMixin, ImportExportModelAdmin):
    """
    Registered for import/export convenience and lookups,
    but hidden from the sidebar.
    """
    resource_classes = [TimeEntryResource]
    list_display = ("timesheet", "date", "minutes", "kind", "short_comment", "updated_at")
    list_filter = ("kind", "date")
    search_fields = ("timesheet__employee__person_role__person__last_name", "comment")
    autocomplete_fields = ("timesheet",)
    readonly_fields = ("created_at", "updated_at")

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
        # Hide from app index/menu; still accessible directly
        return {}
