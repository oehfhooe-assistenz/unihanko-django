# people/admin.py
import json
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html, escapejs
from django.utils.translation import gettext_lazy as _
from django.utils.text import format_lazy, slugify
from django.utils.functional import lazy
from django_object_actions import DjangoObjectActions
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from simple_history.admin import SimpleHistoryAdmin
from django.http import HttpResponseRedirect
from django.urls import reverse
from organisation.models import OrgInfo
from .models import Person, Role, PersonRole, RoleTransitionReason
from core.pdf import render_pdf_response
from core.admin_mixins import ImportExportGuardMixin


# =========================
# Import–Export resources
# =========================
class PersonResource(resources.ModelResource):
    class Meta:
        model = Person
        fields = (
            "id",
            "uuid",
            "last_name",
            "first_name",
            "email",
            "student_email",
            "matric_no",
            "gender",
            "is_active",
            "archived_at",
            "created_at",
            "updated_at",
        )
        export_order = (
            "id",
            "uuid",
            "last_name",
            "first_name",
            "email",
            "student_email",
            "matric_no",
            "gender",
            "is_active",
            "archived_at",
            "created_at",
            "updated_at",
        )


class RoleResource(resources.ModelResource):
    class Meta:
        model = Role
        fields = ("id", "name", "short_name", "ects_cap", "is_elected", "is_stipend_reimbursed", "kind", "default_monthly_amount", "notes")
        export_order = ("id", "name", "short_name", "ects_cap", "is_elected", "is_stipend_reimbursed", "kind", "default_monthly_amount", "notes")


class RoleTransitionReasonResource(resources.ModelResource):
    class Meta:
        model = RoleTransitionReason
        fields = ("id", "code", "name", "active")
        export_order = ("id", "code", "name", "active")


class PersonRoleResource(resources.ModelResource):
    person_id = fields.Field(attribute="person_id", column_name="person_id")
    role_id = fields.Field(attribute="role_id", column_name="role_id")
    start_reason_code = fields.Field(column_name="start_reason_code")
    end_reason_code   = fields.Field(column_name="end_reason_code")

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
            "confirm_date",
            "confirm_ref",
            "start_reason_code",
            "end_reason_code",
            "notes",
        )
        export_order = fields

    # export codes
    def dehydrate_start_reason_code(self, obj):
        return obj.start_reason.code if obj.start_reason_id else ""

    def dehydrate_end_reason_code(self, obj):
        return obj.end_reason.code if obj.end_reason_id else ""

    # allow import by codes (optional convenience)
    def before_import_row(self, row, **kwargs):
        from .models import RoleTransitionReason
        code_s = (row.get("start_reason_code") or "").strip()
        code_e = (row.get("end_reason_code") or "").strip()
        if code_s:
            try:
                row["start_reason_id"] = RoleTransitionReason.objects.only("id").get(code=code_s).id
            except RoleTransitionReason.DoesNotExist:
                row["start_reason_id"] = ""
        if code_e:
            try:
                row["end_reason_id"] = RoleTransitionReason.objects.only("id").get(code=code_e).id
            except RoleTransitionReason.DoesNotExist:
                row["end_reason_id"] = ""


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
class PersonRoleInline(admin.StackedInline):
    model = PersonRole
    extra = 0
    fieldsets = (
        (_("Assignment Details"), {
            "classes": ("collapse",),
            "fields": (
                "role",
                ("start_date"), ("effective_start"), ("start_reason"),
                ("end_date"), ("effective_end"), ("end_reason"),
                ("confirm_date"), ("confirm_ref"),
                "notes",
            ),
        }),
    )
    autocomplete_fields = ("role", "start_reason", "end_reason")
    can_delete = False
    show_change_link = True


# =========================
# Person Admin
# =========================
@admin.register(Person)
class PersonAdmin(ImportExportGuardMixin, DjangoObjectActions, ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [PersonResource]

    # Helper: who counts as a "manager" for people?
    def _is_manager(self, request) -> bool:
        return request.user.groups.filter(name="module:personnel:manager").exists()

    list_display = (
        "last_name",
        "first_name",
        "email",
        "student_email",
        "matric_no",
        "gender",
        "is_active",
        "user",
        "archived_badge",
        "active_roles",
    )
    list_filter = (ActiveAssignmentFilter, "gender", "is_active")
    search_fields = ("first_name", "last_name", "email", "student_email", "matric_no")
    autocomplete_fields = ("user",)
    readonly_fields = ("uuid", "personal_access_code", "created_at", "updated_at")
    inlines = [PersonRoleInline]
    actions = ("archive_selected", "unarchive_selected", "export_selected_pdf")

    fieldsets = (
        (_("Identity"), {
            "fields": (("first_name"), ("last_name"), "uuid", "gender", "notes"),
        }),
        (_("Contacts"), {
            "fields": (("email"), ("student_email"),),
        }),
        (_("University"), {
            "fields": ("matric_no",),
        }),
        (_("Account link"), {
            "fields": ("user",),
        }),
        (_("Personal access code"), {
            "fields": ("personal_access_code",),
        }),
        (_("Status"), {
            "fields": (("is_active"), ("archived_at"),),
        }),
        (_("Timestamps"), {
            "fields": (("created_at"), ("updated_at"),),
        }),
    )

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

    # === actions ===
    change_actions = ("print_pdf", "print_pac_pdf", "regenerate_access_code", )

    def print_pdf(self, request, obj):
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        lname = slugify(obj.last_name)[:40]
        return render_pdf_response("people/person_pdf.html", {"p": obj, "org": OrgInfo.get_solo(),}, request, f"HR-P_AKT_{obj.id}_{lname}_{date_str}.pdf")

    print_pdf.label = "🖨️ " + _("Print Personnel Record PDF")
    print_pdf.attrs = {"class": "btn btn-block btn-secondary btn-sm", "style": "margin-top:10px; margin-bottom: 10px;",}

    def print_pac_pdf(self, request, obj):
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        lname = slugify(obj.last_name)[:40]
        return render_pdf_response("people/person_action_code_notice_pdf.html", {"p": obj}, request, f"HR-P_PAC_INFO_{obj.id}_{lname}_{date_str}.pdf")

    print_pac_pdf.label = "🖨️ " + _("Print Personal Access Code Info PDF (ext.)")
    print_pac_pdf.attrs = {"class": "btn btn-block btn-secondary btn-sm", "style": "margin-top:10px; margin-bottom: 10px;",}

    @admin.action(description=_("Print selected as roster PDF"))
    def export_selected_pdf(self, request, queryset):
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        rows = queryset.order_by("last_name", "first_name")
        return render_pdf_response("people/people_list_pdf.html", {"rows": rows}, request, f"HR-P_SELECT_{date_str}.pdf")
    
    # --- Manager-only object action -----------------------------------------
    def regenerate_access_code(self, request, obj):
        if not self._is_manager(request):
            self.message_user(request, _("You don’t have permission to regenerate access codes."), level=messages.WARNING)
            return
        new_code = obj.regenerate_access_code()
        # Only show the new code; avoid logging the old one.
        self.message_user(
            request,
            _("New access code generated: %(code)s") % {"code": new_code},
            level=messages.SUCCESS,
        )
    _REGEN_MESSAGE = _("Regenerate the access code for this person? The old code will stop working.")
    lazy_escapejs = lazy(escapejs, str)
    regenerate_access_code.label = "🔐 " + _("Regenerate access code")
    regenerate_access_code.attrs = {
        "class": "btn btn-block btn-warning btn-sm",
        # Simple JS confirm; keeps UX tight without extra templates
        "onclick": format_lazy("return confirm('{0}');", lazy_escapejs(_REGEN_MESSAGE)),
        "style": "margin-top:10px; margin-bottom: 10px;",
    }

    # Hide the button for non-managers
    def get_change_actions(self, request, object_id, form_url):
        actions = list(super().get_change_actions(request, object_id, form_url))
        if not self._is_manager(request):
            if "regenerate_access_code" in actions:
                actions.remove("regenerate_access_code")
        return actions

# =========================
# Role Admin
# =========================
@admin.register(Role)
class RoleAdmin(ImportExportGuardMixin, ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [RoleResource]
    list_display = ("name", "short_name", "ects_cap", "is_elected", "is_stipend_reimbursed", "kind")
    search_fields = ("name",)
    list_filter = ("is_elected","is_stipend_reimbursed", "kind")

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
class ReasonAdmin(ImportExportGuardMixin, ImportExportModelAdmin):
    resource_classes = [RoleTransitionReasonResource]
    list_display = ("code", "name", "active")
    list_filter = ("active",)
    search_fields = ("code", "name")

    def get_readonly_fields(self, request, obj=None):
        # Once created, keep code immutable (prevents renumbering chaos)
        if obj:
            return ("code",)
        return ()

    def get_model_perms(self, request):
        if request.user.groups.filter(name="module:personnel:manager").exists():
            return super().get_model_perms(request)
        # Editors may still have 'view' permission for autocomplete, but hide menu entry
        return {}

    def has_delete_permission(self, request, obj=None):
        # Safer to disable hard deletes for dictionary rows, too
        return False

from django.db.models import Q
from finances.models import FiscalYear

# =========================
# PersonRole Admin
# =========================
@admin.register(PersonRole)
class PersonRoleAdmin(ImportExportGuardMixin, DjangoObjectActions, ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [PersonRoleResource]
    list_display = (
        "person",
        "role",
        "start_date", "end_date",
        "effective_start", "effective_end",
        "confirm_date",
        "start_reason",
        "end_reason",
        "short_notes",
    )
    list_filter = (ActiveFilter, "role", "start_reason", "end_reason", "start_date", "end_date", "confirm_date")
    search_fields = ("person__last_name", "person__first_name", "role__name", "confirm_ref", "notes")
    autocomplete_fields = ("person", "role", "start_reason", "end_reason")
    actions = ["offboard_today"]

    change_actions = ("print_appointment_regular", "print_appointment_ad_interim", "print_confirmation", "print_resignation",)

    def get_search_results(self, request, queryset, search_term):
        qs, distinct = super().get_search_results(request, queryset, search_term)
        fy_id = request.GET.get("fy")
        if fy_id:
            try:
                fy = FiscalYear.objects.only("start", "end").get(pk=fy_id)
                # overlap with FY: (start ≤ fy.end) AND (end ≥ fy.start), nulls = open
                qs = qs.filter(
                    Q(effective_start__isnull=True) | Q(effective_start__lte=fy.end),
                    Q(effective_end__isnull=True)   | Q(effective_end__gte=fy.start),
                )
            except FiscalYear.DoesNotExist:
                pass
        return qs, distinct


    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description=_("Notes"))
    def short_notes(self, obj):
        return (obj.notes[:60] + "…") if obj.notes and len(obj.notes) > 60 else (obj.notes or "—")

    @admin.action(description=_("Offboard selected (end today, set default reason if empty)"))
    def offboard_today(self, request, queryset):
        # If you seed R_01 = "Austritt", this will be used as a default when end_reason is missing
        default_end = RoleTransitionReason.objects.filter(code="R_01", active=True).first()
        q = queryset.filter(end_date__isnull=True)
        updated = 0
        today = timezone.localdate()
        for pr in q:
            pr.end_date = today
            if default_end and not pr.end_reason_id:
                pr.end_reason = default_end
            pr.save(update_fields=["end_date", "end_reason"])
            updated += 1
        self.message_user(
            request,
            _("Ended %(n)d active assignment(s).") % {"n": updated},
            messages.SUCCESS,
        )


    def _render_cert(self, request, obj, template, filename):
        ctx = {
            "pr": obj,
            "org": OrgInfo.get_solo(),
            }
        return render_pdf_response(template, ctx, request, filename)

    def print_appointment_regular(self, request, obj):
        rsname = slugify(obj.role.short_name)[:10]
        lname = slugify(obj.person.last_name)[:20]
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        return self._render_cert(
            request, obj,
            "people/certs/appointment_regular.html",
            f"B_{rsname}_{lname}-{date_str}.pdf"
        )
    print_appointment_regular.label = "🧾 " + _("Print appointment (non-confirmation) PDF")
    print_appointment_regular.attrs = {"class": "btn btn-block btn-warning btn-sm", "style": "margin-top:10px; margin-bottom: 10px;",}

    def print_appointment_ad_interim(self, request, obj):
        rsname = slugify(obj.role.short_name)[:10]
        lname = slugify(obj.person.last_name)[:20]
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        return self._render_cert(
            request, obj,
            "people/certs/appointment_ad_interim.html",
            f"B_interim_{rsname}_{lname}-{date_str}.pdf"
        )
    print_appointment_ad_interim.label = "💥 " + _("Print appointment (ad interim) PDF")
    print_appointment_ad_interim.attrs = {"class": "btn btn-block btn-warning btn-sm", "style": "margin-top:10px; margin-bottom: 10px;",}

    def print_confirmation(self, request, obj):
        rsname = slugify(obj.role.short_name)[:10]
        lname = slugify(obj.person.last_name)[:20]
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        # role-kind guard
        if getattr(obj.role, "kind", None) != obj.role.Kind.DEPT_HEAD:
            self.message_user(
                request,
                _("Only department-head assignments can have a confirmation certificate."),
                level=messages.WARNING,
            )
            return HttpResponseRedirect(
                reverse("admin:people_personrole_change", args=[obj.pk])
            )

        # data readiness guard
        if not obj.confirm_date:
            self.message_user(
                request,
                _("Set a confirmation date (and reference, if applicable) before printing the confirmation certificate."),
                level=messages.WARNING,
            )
            return HttpResponseRedirect(
                reverse("admin:people_personrole_change", args=[obj.pk])
            )

        return self._render_cert(
            request, obj,
            "people/certs/appointment_confirmation.html",
            f"B_Beschluss_{obj.confirm_ref or ""}_{rsname}_{lname}-{date_str}.pdf"
        )

    print_confirmation.label = "☑️ " + _("Print confirmation (post-confirmation) PDF")
    print_confirmation.attrs = {"class": "btn btn-block btn-warning btn-sm", "style": "margin-top:10px; margin-bottom: 10px;",}

    def print_resignation(self, request, obj):
        rsname = slugify(obj.role.short_name)[:10]
        lname = slugify(obj.person.last_name)[:20]
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        return self._render_cert(
            request, obj,
            "people/certs/resignation.html",
            f"R_{rsname}_{lname}-{date_str}.pdf"
        )
    print_resignation.label = "🏁 " + _("Print resignation PDF")
    print_resignation.attrs = {"class": "btn btn-block btn-warning btn-sm", "style": "margin-top:10px; margin-bottom: 10px;",}

    # --- Visibility gates (buttons appear only when True) ---
    def get_change_actions(self, request, object_id, form_url):
        actions = list(super().get_change_actions(request, object_id, form_url))
        obj = self.get_object(request, object_id)

        def drop(name):
            if name in actions:
                actions.remove(name)

        # regular: clerks & other roles
        if not (obj and getattr(obj.role, "kind", None) in {obj.role.Kind.DEPT_CLERK, obj.role.Kind.OTHER}):
            drop("print_appointment_regular")

        # ad interim + confirmation: heads only
        if not (obj and getattr(obj.role, "kind", None) == obj.role.Kind.DEPT_HEAD):
            drop("print_appointment_ad_interim")
            drop("print_confirmation")

        # resignation only if ended
        if not (obj and obj.end_date):
            drop("print_resignation")

        return actions

