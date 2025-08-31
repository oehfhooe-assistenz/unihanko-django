# people/admin.py
import json
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from django_object_actions import DjangoObjectActions
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from simple_history.admin import SimpleHistoryAdmin

from .models import Person, Role, PersonRole, RoleTransitionReason
from core.pdf import render_pdf_response


# =========================
# Import–Export resources
# =========================
class PersonResource(resources.ModelResource):
    class Meta:
        model = Person
        fields = ("id", "last_name", "first_name", "email", "archived_at", "created_at", "updated_at")
        export_order = ("id", "last_name", "first_name", "email", "archived_at", "created_at", "updated_at")


class RoleResource(resources.ModelResource):
    class Meta:
        model = Role
        fields = ("id", "name", "ects_cap", "is_elected", "notes")
        export_order = ("id", "name", "ects_cap", "is_elected", "notes")


class RoleTransitionReasonResource(resources.ModelResource):
    class Meta:
        model = RoleTransitionReason
        fields = ("id", "code", "name", "active")
        export_order = ("id", "code", "name", "active")


class PersonRoleResource(resources.ModelResource):
    # Export/import by raw FK ids (simple & reliable), plus a friendly reason_code column
    person_id = fields.Field(attribute="person_id", column_name="person_id")
    role_id = fields.Field(attribute="role_id", column_name="role_id")
    reason_code = fields.Field(column_name="reason_code")

    class Meta:
        model = PersonRole
        fields = (
            "id",
            "person_id",
            "role_id",
            "start_date",
            "end_date",
            "effective_start",
            "effective_end",
            "reason_code",
            "notes",
        )
        export_order = fields

    # show reason code when exporting
    def dehydrate_reason_code(self, obj):
        return obj.reason.code if obj.reason_id else ""

    # allow import by reason_code (optional convenience)
    def before_import_row(self, row, **kwargs):
        code = (row.get("reason_code") or "").strip()
        if code:
            try:
                row["reason_id"] = RoleTransitionReason.objects.only("id").get(code=code).id
            except RoleTransitionReason.DoesNotExist:
                # leave reason blank if unknown code
                row["reason_id"] = ""


# =========================
# Custom list filters
# =========================
class ActiveAssignmentFilter(admin.SimpleListFilter):
    """For Person list: has at least one active assignment (end_date is null)."""
    title = _("Has active assignment")
    parameter_name = "active_assign"

    def lookups(self, request, model_admin):
        return (("yes", _("Yes")), ("no", _("No")))

    def queryset(self, request, qs):
        if self.value() == "yes":
            return qs.filter(role_assignments__end_date__isnull=True).distinct()
        if self.value() == "no":
            return qs.exclude(role_assignments__end_date__isnull=True).distinct()
        return qs


class ActiveFilter(admin.SimpleListFilter):
    """For PersonRole list: active/ended."""
    title = _("Active")
    parameter_name = "active"

    def lookups(self, request, model_admin):
        return (("1", _("Active")), ("0", _("Ended")))

    def queryset(self, request, qs):
        if self.value() == "1":
            return qs.filter(end_date__isnull=True)
        if self.value() == "0":
            return qs.filter(end_date__isnull=False)
        return qs


# =========================
# Inlines
# =========================
class PersonRoleInline(admin.TabularInline):
    model = PersonRole
    extra = 1
    fields = (
        "role",
        "start_date",
        "end_date",
        "effective_start",
        "effective_end",
        "reason",
        "notes",
    )
    autocomplete_fields = ("role", "reason")
    can_delete = False
    show_change_link = True


# =========================
# Person Admin
# =========================
@admin.register(Person)
class PersonAdmin(DjangoObjectActions, ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [PersonResource]
    list_display = ("last_name", "first_name", "email", "archived_badge", "active_roles")
    search_fields = ("first_name", "last_name", "email")
    list_filter = (ActiveAssignmentFilter,)
    inlines = [PersonRoleInline]
    actions = ("archive_selected", "unarchive_selected", "export_selected_pdf")

    # Keep the list clean: hide archived by default
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(archived_at__isnull=True)

    @admin.display(description=_("Archived"))
    def archived_badge(self, obj):
        if not obj.archived_at:
            return "—"
        return format_html(
            '<span style="padding:2px 8px;border-radius:10px;background:#6b7280;color:#fff;font-size:11px;">{}</span>',
            _("Archived"),
        )

    @admin.display(description=_("Active roles"))
    def active_roles(self, obj):
        names = (
            obj.role_assignments.filter(end_date__isnull=True)
            .select_related("role")
            .values_list("role__name", flat=True)
        )
        return ", ".join(names) or "—"

    def has_delete_permission(self, request, obj=None):
        # Policy: no hard deletes
        return False

    @admin.action(description=_("Archive selected"))
    def archive_selected(self, request, queryset):
        updated = queryset.update(archived_at=timezone.now())
        self.message_user(
            request,
            _("Archived %(count)d people.") % {"count": updated},
            level=messages.SUCCESS,
        )

    @admin.action(description=_("Unarchive selected"))
    def unarchive_selected(self, request, queryset):
        updated = queryset.update(archived_at=None)
        self.message_user(
            request,
            _("Unarchived %(count)d people.") % {"count": updated},
            level=messages.SUCCESS,
        )

    # === PDF actions (single + bulk) ===
    change_actions = ("print_pdf",)

    def print_pdf(self, request, obj):
        return render_pdf_response("people/person_pdf.html", {"p": obj}, request, f"person_{obj.id}.pdf")

    print_pdf.label = _("Print PDF")
    print_pdf.attrs = {"class": "btn btn-block btn-outline-secondary btn-sm"}

    @admin.action(description=_("Export selected to PDF"))
    def export_selected_pdf(self, request, queryset):
        rows = queryset.order_by("last_name", "first_name")
        return render_pdf_response("people/people_list_pdf.html", {"rows": rows}, request, "people_selected.pdf")


# =========================
# Role Admin
# =========================
@admin.register(Role)
class RoleAdmin(ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [RoleResource]
    list_display = ("name", "ects_cap", "is_elected")
    search_fields = ("name",)
    list_filter = ("is_elected",)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_model_perms(self, request):
        if request.user.groups.filter(name="module:personnel:manager").exists():
            return super().get_model_perms(request)
        return {}


# =========================
# Reason Admin (dictionary)
# =========================
@admin.register(RoleTransitionReason)
class ReasonAdmin(ImportExportModelAdmin):
    resource_classes = [RoleTransitionReasonResource]
    list_display = ("code", "name", "active")
    list_filter = ("active",)
    search_fields = ("code", "name")

    def get_model_perms(self, request):
        if request.user.groups.filter(name="module:personnel:manager").exists():
            return super().get_model_perms(request)
        # Editors can still have 'view' permission (for autocomplete), but we hide the sidebar entry
        return {}

    def has_delete_permission(self, request, obj=None):
        # Safer to disable hard deletes for dictionary rows, too
        return False


# =========================
# PersonRole Admin
# =========================
@admin.register(PersonRole)
class PersonRoleAdmin(ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [PersonRoleResource]
    list_display = (
        "person",
        "role",
        "start_date",
        "end_date",
        "effective_start",
        "effective_end",
        "reason",
        "short_notes",
    )
    list_filter = (ActiveFilter, "role", "reason", "start_date", "end_date")
    search_fields = ("person__last_name", "person__first_name", "role__name", "notes")
    autocomplete_fields = ("person", "role", "reason")
    actions = ["offboard_today"]

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description=_("Notes"))
    def short_notes(self, obj):
        return (obj.notes[:60] + "…") if obj.notes and len(obj.notes) > 60 else (obj.notes or "—")

    @admin.action(description=_("Offboard selected (end today, set default reason if empty)"))
    def offboard_today(self, request, queryset):
        # If you seed R_01 = "Austritt", this will be used as a default when reason is missing
        default_reason = RoleTransitionReason.objects.filter(code="R_01", active=True).first()
        q = queryset.filter(end_date__isnull=True)
        updated = 0
        today = timezone.localdate()
        for pr in q:
            pr.end_date = today
            if default_reason and not pr.reason_id:
                pr.reason = default_reason
            pr.save(update_fields=["end_date", "reason"])
            updated += 1
        self.message_user(
            request,
            _("Ended %(n)d active assignment(s).") % {"n": updated},
            messages.SUCCESS,
        )
