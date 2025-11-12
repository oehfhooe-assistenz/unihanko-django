# people/admin.py
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import escapejs
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
from core.admin_mixins import ImportExportGuardMixin, HelpPageMixin, safe_admin_action, ManagerOnlyHistoryMixin
from concurrency.admin import ConcurrentModelAdmin
from hankosign.utils import render_signatures_box, state_snapshot, get_action, record_signature, RID_JS, sign_once, seal_signatures_context
from django.core.exceptions import PermissionDenied
from core.utils.bool_admin_status import boolean_status_span, row_state_attr_for_boolean
from django.db.models.functions import Coalesce
from django.db.models import DateField
from django.utils.safestring import mark_safe
from django.template.loader import render_to_string
from core.utils.authz import is_people_manager
from django.db import transaction
from django.db.models import Prefetch

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
            "created_at",
            "updated_at",
        )


class RoleResource(resources.ModelResource):
    class Meta:
        model = Role
        fields = ("id", "name", "short_name", "ects_cap", "is_elected", "is_stipend_reimbursed", "kind", "default_monthly_amount", "is_system", "notes")
        export_order = ("id", "name", "short_name", "ects_cap", "is_elected", "is_stipend_reimbursed", "kind", "default_monthly_amount", "is_system", "notes")


class RoleTransitionReasonResource(resources.ModelResource):
    class Meta:
        model = RoleTransitionReason
        fields = ("id", "code", "name", "name_en", "active")
        export_order = ("id", "code", "name", "name_en", "active")


class PersonRoleResource(resources.ModelResource):
    person_id = fields.Field(attribute="person_id", column_name="person_id")
    role_id = fields.Field(attribute="role_id", column_name="role_id")
    start_reason_code = fields.Field(column_name="start_reason_code")
    end_reason_code = fields.Field(column_name="end_reason_code")
    elected_via_code = fields.Field(column_name="elected_via_code")  # ← NEW: For export

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
            "elected_via_code",  # ← CHANGED: replaced confirm_ref with this
            "start_reason_code",
            "end_reason_code",
            "notes",
        )
        export_order = fields

    # Export codes
    def dehydrate_start_reason_code(self, obj):
        return obj.start_reason.code if obj.start_reason_id else ""

    def dehydrate_end_reason_code(self, obj):
        return obj.end_reason.code if obj.end_reason_id else ""

    def dehydrate_elected_via_code(self, obj):
        """Export elected_via as session item code (e.g., HV25_27_I:or-S002)"""
        if obj.elected_via_id:
            return obj.elected_via.full_identifier
        return ""

    # Allow import by codes (optional convenience)
    def before_import_row(self, row, **kwargs):
        from .models import RoleTransitionReason
        code_s = (row.get("start_reason_code") or "").strip()
        code_e = (row.get("end_reason_code") or "").strip()
        
        # Handle start_reason code → ID
        if code_s:
            try:
                row["start_reason_id"] = RoleTransitionReason.objects.only("id").get(code=code_s).id
            except RoleTransitionReason.DoesNotExist:
                row["start_reason_id"] = ""
        
        # Handle end_reason code → ID
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
    readonly_fields = ("signatures_box",)
    fieldsets = (
        (_("Assignment Details"), {
            "classes": ("collapse",),
            "fields": (
                "role",
                ("start_date"), ("effective_start"), ("start_reason"),
                ("end_date"), ("effective_end"), ("end_reason"),
                ("confirm_date"), ("elected_via"),
                "signatures_box",
                "notes",
                "version",
            ),
        }),
    )
    autocomplete_fields = ("role", "start_reason", "end_reason")
    can_delete = False
    show_change_link = True

    @admin.display(description=_("Signatures"))
    def signatures_box(self, obj):
        if not obj or not getattr(obj, "pk", None):
            return _("— save first to see signatures —")
        return render_signatures_box(obj.person)
    
    def _parent_locked(self, request, obj=None):
        try:
            person = obj if isinstance(obj, Person) else getattr(obj, "person", None)
            if not person:
                return False
            st = state_snapshot(person)
            # managers bypass
            pa = self.admin_site._registry[Person]
            if pa._is_manager(request):
                return False
            return bool(st["locked"])
        except Exception:
            return False
        
    def has_add_permission(self, request, obj):
        if self._parent_locked(request, obj):
            return False
        return super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if self._parent_locked(request, obj):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self._parent_locked(request, obj):
            return False
        return super().has_delete_permission(request, obj)


# =========================
# Person Admin
# =========================
@admin.register(Person)
class PersonAdmin(
    SimpleHistoryAdmin,
    DjangoObjectActions,
    ImportExportModelAdmin,
    ConcurrentModelAdmin,
    HelpPageMixin,
    ImportExportGuardMixin,
    ManagerOnlyHistoryMixin
    ):
    resource_classes = [PersonResource]

    # Helper: who counts as a "manager" for people?
    def _is_manager(self, request) -> bool:
        return is_people_manager(request.user)

    list_display = (
        "last_name",
        "first_name",
        "mail_merged",
        "mat_no_display",
        "acc_check",
        "is_active",
        "active_roles",
        "updated_at",
        "active_text",
    )
    list_filter = (ActiveAssignmentFilter, "gender", "is_active",)
    search_fields = ("first_name", "last_name", "email", "student_email", "matric_no")
    autocomplete_fields = ("user",)
    readonly_fields = ("uuid", "personal_access_code", "created_at", "updated_at", "signatures_box", "mail_merged")
    inlines = [PersonRoleInline]
    actions = ("lock_selected", "unlock_selected", "export_selected_pdf")

    fieldsets = (
        (_("Identity & Status"), {
            "fields": (("first_name"), ("last_name"), "uuid", "gender", "notes", "is_active"),
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
        (_("HankoSign Workflow"), {"fields": ("signatures_box",)}),
        (_("System"), {
            "fields": (("version"), ("created_at"), ("updated_at"),),
        }),
    )

    @admin.display(description=_("MatNo"))
    def mat_no_display(self, obj):
        return obj.matric_no

    @admin.display(description=_("Django Account"))
    def acc_check(self, obj):
        accc = bool(obj.user)
        if accc:
            return "🔗"
        else:
            return "❌"

    @admin.display(description=_("Locked"))
    def active_text(self, obj):
        st = state_snapshot(obj)
        locked = bool(st.get("explicit_locked"))
        return boolean_status_span(
            value=not locked,
            true_label=_("Open"),
            false_label=_("Locked"),
            true_code="ok",
            false_code="locked",
        )


    def get_changelist_row_attrs(self, request, obj):
        st = state_snapshot(obj)  # or state_snapshot(obj.person) in PersonRole
        locked = bool(st.get("explicit_locked"))
        return row_state_attr_for_boolean(
            value=not locked,                 # True => ok
            true_code="ok",
            false_code="locked",
        )

    @admin.display(description=_("Signatures"))
    def signatures_box(self, obj):
        return render_signatures_box(obj)


    @admin.display(description=_("Active roles"))
    def active_roles(self, obj):
        # Uses prefetched data - no extra queries!
        names = [pr.role.name for pr in obj.role_assignments.all()]
        return ", ".join(names) or "—"


    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related(
            Prefetch(
                'role_assignments',
                queryset=PersonRole.objects.filter(end_date__isnull=True).select_related('role')
            )
        )

    def has_delete_permission(self, request, obj=None):
        # Policy: no hard deletes
        return False


    @admin.display(description=_("E-Mail"), ordering="email")
    def mail_merged(self, obj):
        mail = obj.email
        s_mail = obj.student_email
        html = render_to_string(
            "admin/people/_mail_cell.html",
            {
                "mail": mail,
                "s_mail": s_mail,
            },
        )
        return mark_safe(html)


    # === actions ===
    change_actions = ("print_person", "print_pac", "regenerate_access_code", "lock_person", "unlock_person",)

    def _is_locked(self, request, obj):
        if not obj:
            return False
        st = state_snapshot(obj)
        # managers can always bypass editing, but “locked” still shows in UI
        if self._is_manager(request):
            return False
        return bool(st["locked"])


    @transaction.atomic
    def _lock_one(self, request, obj) -> bool:
        st = state_snapshot(obj)
        if st.get("explicit_locked"):
            # already locked; not an error
            return False
        action = get_action("LOCK:-@people.person")
        if not action:
            raise PermissionDenied(_("Lock action is not configured."))
        record_signature(request.user, action, obj, note=_("Personnel record locked"))
        return True
    

    @transaction.atomic
    def _unlock_one(self, request, obj) -> bool:
        st = state_snapshot(obj)
        if not st.get("explicit_locked"):
            # already unlocked; not an error
            return False
        action = get_action("UNLOCK:-@people.person")
        if not action:
            raise PermissionDenied(_("Unlock action is not configured."))
        record_signature(request.user, action, obj, note=_("Personnel record unlocked"))
        return True

    
    @safe_admin_action
    def lock_person(self, request, obj):
        changed = self._lock_one(request, obj)
        self.message_user(
            request, 
            _("Locked.") if changed else _("Already locked."), 
            level=messages.SUCCESS if changed else messages.INFO
        )
    lock_person.label = _("Lock record")
    lock_person.attrs = {"class": "btn btn-block btn-secondary", "style": "margin-bottom: 1rem;"}
    #lock_person.attrs = {"class": "max-md:-mt-px max-md:first:rounded-t-default md:last:rounded-r-default md:first:rounded-l-default hover:text-primary-600 dark:hover:text-primary-500 border-base-200 md:-ml-px max-md:last:rounded-b-default border dark:border-base-700"}

    @safe_admin_action
    def unlock_person(self, request, obj):
        changed = self._unlock_one(request, obj)
        self.message_user(
            request,
            _("Unlocked.") if changed else _("Not locked."),
            level=messages.SUCCESS if changed else messages.INFO
        )
    unlock_person.label = _("Unlock record")
    unlock_person.attrs = {"class": "btn btn-block btn-warning", "style": "margin-bottom: 1rem;"}
    

    @admin.action(description=_("Lock selected"))
    def lock_selected(self, request, queryset):
        if not queryset.exists():
            self.message_user(request, _("No rows selected."), level=messages.INFO); return
        ok = already = fail = 0
        try:
            action = get_action("LOCK:-@people.person")
            if not action:
                self.message_user(request, _("Lock action is not configured."), level=messages.ERROR); return
        except Exception:
            self.message_user(request, _("Lock action is not configured."), level=messages.ERROR); return

        for obj in queryset:
            try:
                st = state_snapshot(obj)
                if st.get("explicit_locked"):
                    already += 1
                    continue
                record_signature(request.user, action, obj, note=_("Personnel record locked (bulk)"))
                ok += 1
            except Exception:
                fail += 1
                continue

        msg = []
        if ok:      msg.append(_("locked %(n)d") % {"n": ok})
        if already: msg.append(_("already locked %(n)d") % {"n": already})
        if fail:    msg.append(_("failed %(n)d") % {"n": fail})
        level = messages.SUCCESS if ok and not fail else (messages.WARNING if ok and fail else messages.INFO)
        self.message_user(request, ", ".join(msg) + ".", level=level)


    @admin.action(description=_("Unlock selected"))
    def unlock_selected(self, request, queryset):
        if not queryset.exists():
            self.message_user(request, _("No rows selected."), level=messages.INFO); return
        ok = already = fail = 0
        try:
            action = get_action("UNLOCK:-@people.person")
            if not action:
                self.message_user(request, _("Unlock action is not configured."), level=messages.ERROR); return
        except Exception:
            self.message_user(request, _("Unlock action is not configured."), level=messages.ERROR); return

        for obj in queryset:
            try:
                st = state_snapshot(obj)
                if not st.get("explicit_locked"):
                    already += 1
                    continue
                record_signature(request.user, action, obj, note=_("Personnel record unlocked (bulk)"))
                ok += 1
            except Exception:
                fail += 1
                continue

        msg = []
        if ok:      msg.append(_("unlocked %(n)d") % {"n": ok})
        if already: msg.append(_("already unlocked %(n)d") % {"n": already})
        if fail:    msg.append(_("failed %(n)d") % {"n": fail})
        level = messages.SUCCESS if ok and not fail else (messages.WARNING if ok and fail else messages.INFO)
        self.message_user(request, ", ".join(msg) + ".", level=level)

    @safe_admin_action
    def print_person(self, request, obj):
        action = get_action("RELEASE:-@people.person")
        if not action:
            self.message_user(request, _("Release action not configured."), level=messages.ERROR)
            return
        sign_once(request, action, obj, note=_("Printed personnel dossier PDF"), window_seconds=10)
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        lname = slugify(obj.last_name)[:40]
        ctx = {
            "p": obj,
            "org": OrgInfo.get_solo(),
            'signers': [
                {'label': 'i.A. ÖH FH OÖ'},
            ]
        }
        return render_pdf_response("people/person_pdf.html",
            ctx,
            request, f"HR-P_AKT_{obj.id}_{lname}_{date_str}.pdf")
    print_person.label = "🖨️ " + _("Print Personnel Record PDF")
    print_person.attrs = {"class": "btn btn-block btn-info", "style": "margin-bottom: 1rem;", "data-action": "post-object", "onclick": RID_JS}


    @safe_admin_action
    def print_pac(self, request, obj):
        if not self._is_manager(request):
            self.message_user(request, _("Managers only."), level=messages.WARNING)
            return
        action = get_action("RELEASE:-@people.person")
        if not action:
            self.message_user(request, _("Release action not configured."), level=messages.ERROR)
            return
        sign_once(request, action, obj, note=_("Printed PAC info PDF"), window_seconds=10)
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        lname = slugify(obj.last_name)[:40]
        signatures = seal_signatures_context(obj)   # seal ON this Person
        return render_pdf_response("people/person_action_code_notice_pdf.html",
            {"p": obj, "signatures": signatures},
            request, f"HR-P_PAC_INFO_{obj.id}_{lname}_{date_str}.pdf")
    print_pac.label = "🖨️ " + _("Print Personal Access Code Info PDF (ext.)")
    print_pac.attrs = {"class": "btn btn-block btn-info", "style": "margin-bottom: 1rem;", "data-action": "post-object", "onclick": RID_JS}


    @admin.action(description=_("Print selected as roster PDF"))
    def export_selected_pdf(self, request, queryset):
        action = get_action("RELEASE:-@people.person")
        if not action:
            self.message_user(request, _("Release action not configured."), level=messages.ERROR); return
        for p in queryset:
            try:
                record_signature(request.user, action, p, note=_("Included in roster PDF export"))
            except Exception:
                # Don’t hard-fail the whole export; you still get the audit trail per-success
                pass
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        rows = queryset.order_by("last_name", "first_name")
        return render_pdf_response("people/people_list_pdf.html", {"rows": rows}, request, f"HR-P_SELECT_{date_str}.pdf")


    @safe_admin_action
    @transaction.atomic
    def regenerate_access_code(self, request, obj):
        if not self._is_manager(request):
            self.message_user(request, _("You don’t have permission to regenerate access codes."), level=messages.WARNING)
            return
        action = get_action("RELEASE:-@people.person")
        if not action:
            self.message_user(request, _("Release action not configured."), level=messages.ERROR)
            return
        record_signature(request.user, action, obj, note=_("Regenerated access code"))
        new_code = obj.regenerate_access_code()
        self.message_user(request, _("New access code generated: %(code)s") % {"code": new_code}, level=messages.SUCCESS)
    _REGEN_MESSAGE = _("Regenerate the access code for this person? The old code will stop working.")
    lazy_escapejs = lazy(escapejs, str)
    regenerate_access_code.label = "🔐 " + _("Regenerate access code")
    regenerate_access_code.attrs = {
        "class": "btn btn-block btn-info",
        # Simple JS confirm; keeps UX tight without extra templates
        "onclick": format_lazy("return confirm('{0}');", lazy_escapejs(_REGEN_MESSAGE)),
        "style": "margin-bottom: 1rem;",
    }


    def get_change_actions(self, request, object_id, form_url):
        actions = list(super().get_change_actions(request, object_id, form_url))
        obj = self.get_object(request, object_id)
        def drop(n):
            if n in actions: actions.remove(n)
        if not self._is_manager(request):
            drop("regenerate_access_code")
            drop("print_pac")
            drop("lock_person")
            drop("unlock_person")
        if obj:
            st = state_snapshot(obj)
            if st["explicit_locked"]:
                drop("lock_person")
            else:
                drop("unlock_person")
        return actions


    def get_actions(self, request):
        actions = super().get_actions(request)
        if not self._is_manager(request):
            actions.pop("lock_selected", None)
            actions.pop("unlock_selected", None)
        return actions


    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj and self._is_locked(request, obj):
            # freeze everything except the action area
            for f in ("first_name","last_name","email","student_email","matric_no","gender","notes","user","is_active"):
                if f not in ro:
                    ro.append(f)
        return ro



# =========================
# Role Admin
# =========================
@admin.register(Role)
class RoleAdmin(
    SimpleHistoryAdmin,
    ImportExportModelAdmin,
    ConcurrentModelAdmin,
    HelpPageMixin,
    ImportExportGuardMixin,
    ManagerOnlyHistoryMixin
    ):
    resource_classes = [RoleResource]
    list_display = ("name", "short_name", "ects_cap", "is_elected", "is_stipend_reimbursed", "kind_text", "is_system")
    search_fields = ("name",)
    list_filter = ("is_elected","is_stipend_reimbursed", "is_system", "kind",)

    @admin.display(description=_("Role type"), ordering="kind")
    def kind_text(self, obj):
        html = render_to_string(
            "admin/people/_role_kind.html",
            {"is_system": obj.is_system, "label": obj.kind_label},
        )
        return mark_safe(html)
    
    def get_fieldsets(self, request, obj=None):
        return (
            (_("Basics"), {
                "fields": ("name", "short_name", "notes"),
            }),
            (_("Type & Flags"), {
                "fields": ("kind", "is_system", "is_elected", "is_stipend_reimbursed"),
            }),
            (_("Academic/Finance defaults"), {
                "fields": ("ects_cap", "default_monthly_amount"),
            }),
        )

    def has_delete_permission(self, request, obj=None):
        return False

    def get_model_perms(self, request):
        if is_people_manager(request.user):
            return super().get_model_perms(request)
        return {}


# =========================
# Reason Admin (dictionary)
# =========================
@admin.register(RoleTransitionReason)
class ReasonAdmin(
    ImportExportModelAdmin,
    HelpPageMixin,
    ImportExportGuardMixin
    ):
    resource_classes = [RoleTransitionReasonResource]
    list_display = ("code", "name_localized", "active")
    list_filter = ("active",)
    search_fields = ("code", "name", "name_en")

    def get_readonly_fields(self, request, obj=None):
        # Once created, keep code immutable (prevents renumbering chaos)
        if obj:
            return ("code", "name",)
        return ()

    @admin.display(description=_("Name (localized)"))
    def name_localized(self, obj):
        return obj.display_name

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
class PersonRoleAdmin(
    SimpleHistoryAdmin,
    DjangoObjectActions,
    ImportExportModelAdmin,
    ConcurrentModelAdmin,
    HelpPageMixin,
    ImportExportGuardMixin,
    ManagerOnlyHistoryMixin
    ):
    resource_classes = [PersonRoleResource]
    list_display = (
        "person",
        "role",
        "start_merged",
        "start_reason",
        "confirm_date",
        "end_merged",
        "end_reason",
        "updated_at",
        "active_text",
    )
    list_display_links = ("person",)
    list_filter = (ActiveFilter, "role", "start_reason", "end_reason", "start_date", "end_date", "confirm_date")
    search_fields = ("person__last_name", "person__first_name", "role__name", "notes")
    autocomplete_fields = ("person", "role", "start_reason", "end_reason", "elected_via")
    readonly_fields = ("signatures_box", "election_reference", "created_at", "updated_at",)
    actions = ["offboard_today"]

    fieldsets = (
        (_("Assignment"), {
            "fields": (
                "person", "role",
                "start_date", "end_date",
                "effective_start", "effective_end",
            ),
        }),
        (_("Reasons"), {
            "fields": ("start_reason", "end_reason"),
        }),
        (_("Confirmation (heads only)"), {
            "fields": ("confirm_date", "elected_via", "election_reference",),
        }),
        (_("Notes"), {
            "fields": ("notes",),
        }),
        (_("HankoSign Workflow"), {
            "fields": ("signatures_box",),
        }),
        (_("System"), {
            "fields": ("version", "created_at", "updated_at"),   # if you want it visible
        }),
    )

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

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            start_display=Coalesce("effective_start", "start_date", output_field=DateField()),
            end_display=Coalesce("effective_end", "end_date", output_field=DateField()),
        )

    def has_delete_permission(self, request, obj=None):
        return False


    def _is_locked(self, request, obj):
        if not obj:
            return False
        from hankosign.utils import state_snapshot
        st = state_snapshot(obj.person)
        if is_people_manager(request.user):
            return False
        return bool(st["locked"])


    @admin.display(description=_("Active"))
    def active_text(self, obj):
        # True when end_date is None
        return boolean_status_span(
            obj.is_active,
            true_label=_("Active"),
            false_label=_("Ended"),
            true_code="ok",
            false_code="off",
        )


    @admin.display(description=_("Start"), ordering="start_display")
    def start_merged(self, obj):
        d = obj.effective_start or obj.start_date
        html = render_to_string(
            "admin/people/_date_cell.html",
            {
                "date": d,
                "is_effective": bool(obj.effective_start),
                "label": _("start date"),
            },
        )
        return mark_safe(html)
    

    @admin.display(description=_("End"), ordering="end_display")
    def end_merged(self, obj):
        d = obj.effective_end or obj.end_date
        html = render_to_string(
            "admin/people/_date_cell.html",
            {
                "date": d,
                "is_effective": bool(obj.effective_end),
                "label": _("end date"),
            },
        )
        return mark_safe(html)
    

    @admin.display(description=_("Election reference"))
    def election_reference(self, obj):
        """Display the session item code for elected assignments"""
        if not obj or not obj.pk:
            return "—"
        if obj.elected_via:
            return mark_safe(
                f'<a href="{reverse("admin:assembly_sessionitem_change", args=[obj.elected_via.pk])}" target="_blank">'
                f'{obj.elected_via.full_identifier}</a>'
            )
        return "—"


    def get_changelist_row_attrs(self, request, obj):
        # Show assignment state (not parent lock)
        return row_state_attr_for_boolean(
            value=obj.is_active,
            true_code="ok",
            false_code="off",
        )


    @admin.display(description=_("Signatures"))
    def signatures_box(self, obj):
        if not obj:
            return _("— save first to see signatures —")
        from hankosign.utils import render_signatures_box
        return render_signatures_box(obj.person)


    @admin.display(description=_("Notes"))
    def short_notes(self, obj):
        return (obj.notes[:60] + "…") if obj.notes and len(obj.notes) > 60 else (obj.notes or "—")


    @transaction.atomic
    @admin.action(description=_("Offboard selected (end today, set default reason if empty)"))
    def offboard_today(self, request, queryset):
        # If you seed O01 = "Austritt" (fallback X99), this will be used as a default when end_reason is missing
        default_end = ( RoleTransitionReason.objects.filter(code="O01", active=True).first()
            or RoleTransitionReason.objects.filter(code="X99", active=True).first()
        )
        if not default_end:
            self.message_user(
                request,
                _("Cannot offboard: default end reason O01 is missing. Seed reasons first."),
                level=messages.ERROR,
            )
            return
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


    def _deny_and_back(self, request, obj):
        self.message_user(request, _("Managers only."), level=messages.WARNING)
        return HttpResponseRedirect(reverse("admin:people_personrole_change", args=[obj.pk]))

    @safe_admin_action
    def print_appointment_regular(self, request, obj):
        if not is_people_manager(request.user):
            return self._deny_and_back(request, obj)
        action = get_action("RELEASE:-@people.person")
        if not action:
            self.message_user(request, _("Release action not configured."), level=messages.ERROR)
            return
        sign_once(request, action, obj.person, note=_("Printed %(what)s") % {"what": "appointment (non-confirmation)"}, window_seconds=10)
        rsname = slugify(obj.role.short_name)[:10]
        lname = slugify(obj.person.last_name)[:20]
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        return self._render_cert(
            request, obj,
            "people/certs/appointment_regular.html",
            f"B_{rsname}_{lname}-{date_str}.pdf"
        )
    print_appointment_regular.label = "🧾 " + _("Print certifcate (non-conf.) PDF")
    print_appointment_regular.attrs = {"class": "btn btn-block btn-warning", "style": "margin-bottom: 1rem;", "data-action": "post-object", "onclick": RID_JS}


    @safe_admin_action
    def print_appointment_ad_interim(self, request, obj):
        if not is_people_manager(request.user):
            return self._deny_and_back(request, obj)
        action = get_action("RELEASE:-@people.person")
        if not action:
            self.message_user(request, _("Release action not configured."), level=messages.ERROR)
            return
        sign_once(request, action, obj.person, note=_("Printed %(what)s") % {"what": "appointment (ad interim)"}, window_seconds=10)
        rsname = slugify(obj.role.short_name)[:10]
        lname = slugify(obj.person.last_name)[:20]
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        return self._render_cert(
            request, obj,
            "people/certs/appointment_ad_interim.html",
            f"B_interim_{rsname}_{lname}-{date_str}.pdf"
        )
    print_appointment_ad_interim.label = "💥 " + _("Print certificate (ad interim) PDF")
    print_appointment_ad_interim.attrs = {"class": "btn btn-block btn-warning", "style": "margin-bottom: 1rem;", "data-action": "post-object", "onclick": RID_JS}


    @safe_admin_action
    def print_confirmation(self, request, obj):
        if not is_people_manager(request.user):
            return self._deny_and_back(request, obj)
        action = get_action("RELEASE:-@people.person")
        if not action:
            self.message_user(request, _("Release action not configured."), level=messages.ERROR)
            return
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
        sign_once(request, action, obj.person, note=_("Printed %(what)s") % {"what": "appointment (post-confirmation)"}, window_seconds=10)
        rsname = slugify(obj.role.short_name)[:10]
        lname = slugify(obj.person.last_name)[:20]
        ref_code = obj.elected_via.item_code if obj.elected_via else ''
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        return self._render_cert(
            request, obj,
            "people/certs/appointment_confirmation.html",
            f"B_Beschluss_{ref_code}_{rsname}_{lname}-{date_str}.pdf"
        )
    print_confirmation.label = "☑️ " + _("Print certificate (post-conf.) PDF")
    print_confirmation.attrs = {"class": "btn btn-block btn-warning", "style": "margin-bottom: 1rem;", "data-action": "post-object", "onclick": RID_JS}

    @safe_admin_action
    def print_resignation(self, request, obj):
        if not is_people_manager(request.user):
            return self._deny_and_back(request, obj)
        action = get_action("RELEASE:-@people.person")
        if not action:
            self.message_user(request, _("Release action not configured."), level=messages.ERROR)
            return
        sign_once(request, action, obj.person, note=_("Printed %(what)s") % {"what": "resignation"}, window_seconds=10)
        rsname = slugify(obj.role.short_name)[:10]
        lname = slugify(obj.person.last_name)[:20]
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        return self._render_cert(
            request, obj,
            "people/certs/resignation.html",
            f"R_{rsname}_{lname}-{date_str}.pdf"
        )
    print_resignation.label = "🏁 " + _("Print resignation PDF")
    print_resignation.attrs = {"class": "btn btn-block btn-warning", "style": "margin-bottom: 1rem;", "data-action": "post-object", "onclick": RID_JS}


    # --- Visibility gates (buttons appear only when True) ---
    def get_change_actions(self, request, object_id, form_url):
        actions = list(super().get_change_actions(request, object_id, form_url))
        obj = self.get_object(request, object_id)

        def drop(name):
            if name in actions:
                actions.remove(name)

        # Managers only: printing certificates
        is_mgr = is_people_manager(request.user)
        if not is_mgr:
            drop("print_appointment_regular")
            drop("print_appointment_ad_interim")
            drop("print_confirmation")
            drop("print_resignation")
            return actions  # bail early; nothing else matters for editors

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


    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj and self._is_locked(request, obj):
            for f in ("person","role","start_date","end_date","effective_start","effective_end",
                    "start_reason","end_reason","confirm_date","elected_via","notes"):
                if f not in ro: ro.append(f)
        return ro
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "person" and not is_people_manager(request.user):
            # Build a list of unlocked Person IDs (Python-side check via state_snapshot)
            people = Person.objects.only("id")  # keep it light
            allowed_ids = []
            for p in people:
                try:
                    if not state_snapshot(p).get("locked"):
                        allowed_ids.append(p.id)
                except Exception:
                    # If snapshot fails, be conservative: exclude
                    continue
            kwargs["queryset"] = Person.objects.filter(pk__in=allowed_ids)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        # Final server-side safety net
        if not is_people_manager(request.user):
            st = state_snapshot(obj.person)
            if st.get("locked"):
                from django.core.exceptions import PermissionDenied
                raise PermissionDenied(_("This person is locked; you can’t add or modify assignments."))
        super().save_model(request, obj, form, change)