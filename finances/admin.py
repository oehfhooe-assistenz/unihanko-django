from django.contrib import admin, messages
from django import forms
from django.utils.translation import gettext_lazy as _
from django_object_actions import DjangoObjectActions
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from simple_history.admin import SimpleHistoryAdmin

from .models import FiscalYear, default_start, auto_end_from_start, stored_code_from_dates
from core.pdf import render_pdf_response


# =============== Import–Export ===============
class FiscalYearResource(resources.ModelResource):
    class Meta:
        model = FiscalYear
        fields = ("id", "code", "label", "start", "end", "is_active", "created_at", "updated_at")
        export_order = ("id", "code", "label", "start", "end", "is_active", "created_at", "updated_at")


# =============== Admin form ===============
class FiscalYearForm(forms.ModelForm):
    class Meta:
        model = FiscalYear
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["end"].help_text = _("Leave blank to auto-fill (1 year − 1 day).")
        self.fields["code"].help_text = _("Leave blank to auto-generate (WJyy_yy).")


# =============== Admin ===============
@admin.register(FiscalYear)
class FiscalYearAdmin(DjangoObjectActions, ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [FiscalYearResource]
    form = FiscalYearForm

    list_display = ("display_code", "start", "end", "is_active", "updated_at")
    list_filter = ("is_active", "start", "end")
    search_fields = ("code", "label")
    ordering = ("-start",)
    date_hierarchy = "start"
    actions = ("export_selected_pdf", "make_active")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        (_("Basics"), {"fields": (("start", "end"), "code", "label", "is_active")}),
        (_("Timestamps"), {"fields": (("created_at", "updated_at"),)}),
    )

    # Prefill “Add” with current FY; user can change start and leave end blank.
    def get_changeform_initial_data(self, request):
        start = default_start()
        end = auto_end_from_start(start)
        return {"start": start, "end": end, "code": stored_code_from_dates(start, end)}

    # No hard delete (policy consistent with People)
    def has_delete_permission(self, request, obj=None):
        return False

    # === PDF actions (single + bulk) ===
    change_actions = ("print_pdf",)

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
        FiscalYear.objects.update(is_active=False)
        updated = queryset.update(is_active=True)
        self.message_user(
            request,
            _("Activated %(n)d fiscal year(s).") % {"n": updated},
            level=messages.SUCCESS,
        )
