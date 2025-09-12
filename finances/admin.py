from django.contrib import admin, messages
from django import forms
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django_object_actions import DjangoObjectActions
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from simple_history.admin import SimpleHistoryAdmin
from django.db import transaction, IntegrityError

from .models import FiscalYear, default_start, auto_end_from_start, stored_code_from_dates
from core.pdf import render_pdf_response


# =============== Import–Export ===============
class FiscalYearResource(resources.ModelResource):
    class Meta:
        model = FiscalYear
        fields = ("id", "code", "label", "start", "end", "is_active", "is_locked", "created_at", "updated_at")
        export_order = ("id", "code", "label", "start", "end", "is_active", "is_locked", "created_at", "updated_at")


# =============== Admin form ===============
class FiscalYearForm(forms.ModelForm):
    class Meta:
        model = FiscalYear
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "end" in self.fields:
            self.fields["end"].help_text = _("Leave blank to auto-fill (1 year − 1 day).")
        if "code" in self.fields:
            self.fields["code"].help_text = _("Leave blank to auto-generate (WJyy_yy).")


# =============== Admin ===============
@admin.register(FiscalYear)
class FiscalYearAdmin(DjangoObjectActions, ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [FiscalYearResource]
    form = FiscalYearForm

    # --- helpers ------------------------------------------------------------
    def _is_manager(self, request) -> bool:
        return request.user.groups.filter(name="module:finances:manager").exists()

    # --- list / filters / search -------------------------------------------
    list_display = ("display_code", "start", "end", "status_badges", "updated_at")
    list_filter = ("is_active", "is_locked", "start", "end")
    search_fields = ("code", "label")
    ordering = ("-start",)
    date_hierarchy = "start"
    list_per_page = 50

    # bulk actions
    actions = ("export_selected_pdf", "make_active")

    # readonly timestamps always
    readonly_fields = ("created_at", "updated_at", "locked_state")

    fieldsets = (
        (_("Basics"), {"fields": (("start", "end"), "code", "label", "is_active", "locked_state")}),
        (_("Timestamps"), {"fields": (("created_at", "updated_at"),)}),
    )

    @admin.display(description=_("Locked"))
    def locked_state(self, obj):
        if not obj:
            return "—"
        if obj.is_locked:
            return format_html('<span class="badge" style="background:#6b7280;color:#fff;">{}</span>', _("Locked"))
        return format_html('<span class="badge" style="background:#10b981;color:#fff;">{}</span>', _("Open"))

    @admin.display(description=_("Status"))
    def status_badges(self, obj):
        parts = []
        if obj.is_active:
            parts.append('<span class="badge" style="background:#2563eb;color:#fff;margin-right:.25rem;">{}</span>'.format(_("Active")))
        if obj.is_locked:
            parts.append('<span class="badge" style="background:#6b7280;color:#fff;">{}</span>'.format(_("Locked")))
        else:
            parts.append('<span class="badge" style="background:#f59e0b;color:#fff;">{}</span>'.format(_("Open")))
        return format_html(" ".join(parts))

    # Prefill “Add” with current FY; user can change start and leave end blank.
    def get_changeform_initial_data(self, request):
        start = default_start()
        end = auto_end_from_start(start)
        return {"start": start, "end": end, "code": stored_code_from_dates(start, end)}

    # Make key fields read-only in the UI when locked (any user)
    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj and obj.is_locked:
            ro += ["start", "end", "code", "label", "is_active"]
        return ro

    # Hide actions the user isn't allowed to use
    def get_actions(self, request):
        actions = super().get_actions(request)
        if not self._is_manager(request):
            actions.pop("make_active", None)
        return actions

    # No hard delete (policy consistent with People)
    def has_delete_permission(self, request, obj=None):
        return False

    # === PDF actions (single + bulk) ===
    change_actions = ("print_pdf", "lock_year", "unlock_year")

    def print_pdf(self, request, obj):
        ctx = {"fy": obj}
        return render_pdf_response("finances/fiscalyear_pdf.html", ctx, request, f"{obj.display_code()}.pdf")
    print_pdf.label = _("Print PDF")
    print_pdf.attrs = {"class": "btn btn-block btn-outline-secondary btn-sm"}

    @admin.action(description=_("Export selected to PDF"))
    def export_selected_pdf(self, request, queryset):
        rows = queryset.order_by("-start")
        return render_pdf_response("finances/fiscalyears_list_pdf.html", {"rows": rows}, request, "fiscal_years.pdf")

    @admin.action(description=_("Set selected as active (and clear others)"))
    def make_active(self, request, queryset):
        if not self._is_manager(request):
            self.message_user(request, _("You don’t have permission to set active."), level=messages.WARNING)
            return

        # Block locked targets and enforce a single selection
        locked = queryset.filter(is_locked=True)
        if locked.exists():
            self.message_user(
                request,
                _("You cannot set a locked fiscal year as active. Deselect locked rows first."),
                level=messages.warning,
            )
            return

        count = queryset.count()
        if count != 1:
            self.message_user(
                request,
                _("Select exactly one fiscal year to set active (you selected %(n)d).") % {"n": count},
                level=messages.WARNING,
            )
            return

        target = queryset.first()
        if target.is_active:
            self.message_user(
                request,
                _("%(code)s is already the active fiscal year.") % {"code": target.display_code()},
                level=messages.INFO,
            )
            return

        try:
            with transaction.atomic():
                FiscalYear.objects.exclude(pk=target.pk).update(is_active=False)
                target.is_active = True
                target.save(update_fields=["is_active"])
        except IntegrityError:
            self.message_user(
                request,
                _("Could not set active due to a database constraint (another year may have been activated concurrently)."),
                level=messages.ERROR,
            )
            return

        self.message_user(
            request,
            _("Activated %(code)s as the current fiscal year.") % {"code": target.display_code()},
            level=messages.SUCCESS,
        )

    # === Object actions: Lock / Unlock (managers only) ===
    def get_change_actions(self, request, object_id, form_url):
        actions = super().get_change_actions(request, object_id, form_url)
        if not self._is_manager(request):
            # only allow Print PDF for editors
            return [a for a in actions if a == "print_pdf"]
        obj = self.get_object(request, object_id)
        if obj:
            if obj.is_locked:
                # hide Lock, keep Unlock + PDF
                return [a for a in actions if a in ("unlock_year", "print_pdf")]
            else:
                # show Lock + PDF
                return [a for a in actions if a in ("lock_year", "print_pdf")]
        return actions

    def lock_year(self, request, obj):
        if not self._is_manager(request):
            self.message_user(request, _("You don’t have permission to lock years."), level=messages.WARNING)
            return
        if obj.is_locked:
            self.message_user(request, _("Already locked."), level=messages.INFO)
            return
        obj.is_locked = True
        obj.save(update_fields=["is_locked"])
        self.message_user(request, _("Fiscal year locked."), level=messages.SUCCESS)
    lock_year.label = _("Lock year")
    lock_year.attrs = {"class": "btn btn-block btn-outline-warning btn-sm"}

    def unlock_year(self, request, obj):
        if not self._is_manager(request):
            self.message_user(request, _("You don’t have permission to unlock years."), level=messages.WARNING)
            return
        if not obj.is_locked:
            self.message_user(request, _("Already open."), level=messages.INFO)
            return
        obj.is_locked = False
        obj.save(update_fields=["is_locked"])
        self.message_user(request, _("Fiscal year unlocked."), level=messages.SUCCESS)
    unlock_year.label = _("Unlock year")
    unlock_year.attrs = {"class": "btn btn-block btn-outline-success btn-sm"}
