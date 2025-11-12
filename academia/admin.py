# academia/admin.py
from django.contrib import admin, messages
from django import forms
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.utils.text import slugify
from django.utils import timezone
from django_object_actions import DjangoObjectActions
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from simple_history.admin import SimpleHistoryAdmin
from concurrency.admin import ConcurrentModelAdmin
from django.db import transaction
from django.core.exceptions import PermissionDenied, ValidationError

from .models import Semester, InboxRequest, InboxCourse, SemesterAuditEntry, generate_semester_password
from people.models import PersonRole, Person
from organisation.models import OrgInfo
from core.pdf import render_pdf_response
from core.admin_mixins import (
    ImportExportGuardMixin,
    HelpPageMixin,
    safe_admin_action,
    ManagerOnlyHistoryMixin
)
from core.utils.authz import is_module_manager
from core.utils.bool_admin_status import boolean_status_span
from hankosign.utils import (
    render_signatures_box,
    state_snapshot,
    get_action,
    record_signature,
    has_sig,
    sign_once,
    object_status_span,
    seal_signatures_context
)
from .utils import synchronize_audit_entries, validate_ects_total


# =============== Import-Export Resources ===============

class SemesterResource(resources.ModelResource):
    class Meta:
        model = Semester
        fields = (
            'id', 'code', 'display_name', 'start_date', 'end_date',
            'is_active', 'ects_adjustment', 'created_at', 'updated_at'
        )
        export_order = fields


class InboxRequestResource(resources.ModelResource):
    class Meta:
        model = InboxRequest
        fields = (
            'id', 'reference_code', 'semester', 'person_role',
            'student_note', 'created_at', 'updated_at'
        )
        export_order = fields


class SemesterAuditEntryResource(resources.ModelResource):
    class Meta:
        model = SemesterAuditEntry
        fields = (
            'id', 'semester', 'person', 'max_ects_entitled',
            'ects_reimbursed', 'ects_bulk', 'notes', 'generated_at'
        )
        export_order = fields


# =============== Custom Forms ===============

class SemesterForm(forms.ModelForm):
    class Meta:
        model = Semester
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'access_password' in self.fields:
            self.fields['access_password'].help_text = _(
                "Auto-generated on save. Superusers can regenerate via admin action."
            )
        if 'ects_adjustment' in self.fields:
            self.fields['ects_adjustment'].help_text = _(
                "Bonus/malus ECTS (e.g., +2.0 or -2.0) applied to all roles in this semester"
            )


class InboxCourseInlineForm(forms.ModelForm):
    class Meta:
        model = InboxCourse
        fields = '__all__'

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('course_code') and not cleaned.get('course_name'):
            raise ValidationError(
                _("At least one of course code or course name is required")
            )
        return cleaned


class InboxRequestForm(forms.ModelForm):
    class Meta:
        model = InboxRequest
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'reference_code' in self.fields:
            self.fields['reference_code'].help_text = _(
                "Auto-generated on first save in format: SEMESTER-NAME-####"
            )
        if 'affidavit1_confirmed_at' in self.fields:
            self.fields['affidavit1_confirmed_at'].help_text = _(
                "Timestamp when student confirmed initial submission affidavit"
            )
        if 'affidavit2_confirmed_at' in self.fields:
            self.fields['affidavit2_confirmed_at'].help_text = _(
                "Timestamp when student uploads signed form"
            )

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk and self.instance.courses.exists():
            is_valid, max_ects, total_ects, message = validate_ects_total(self.instance)
            if not is_valid:
                self.add_error(None, ValidationError(message))
        return cleaned


class SemesterAuditEntryForm(forms.ModelForm):
    class Meta:
        model = SemesterAuditEntry
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ['max_ects_entitled', 'ects_reimbursed', 'ects_bulk']:
            if field_name in self.fields:
                self.fields[field_name].help_text = _(
                    "Calculated automatically. Modify via audit synchronization."
                )


# =============== Inline Admins ===============

class InboxCourseInline(admin.TabularInline):
    model = InboxCourse
    form = InboxCourseInlineForm
    extra = 1
    fields = ('course_code', 'course_name', 'ects_amount')

    def has_delete_permission(self, request, obj=None):
        if obj and obj.inbox_request_id:
            request_obj = InboxRequest.objects.get(pk=obj.inbox_request_id)
            st = state_snapshot(request_obj)
            if st.get('locked'):
                return False
        return super().has_delete_permission(request, obj)


# =============== Admin Classes ===============

@admin.register(Semester)
class SemesterAdmin(
    SimpleHistoryAdmin,
    DjangoObjectActions,
    ImportExportModelAdmin,
    ConcurrentModelAdmin,
    HelpPageMixin,
    ImportExportGuardMixin,
    ManagerOnlyHistoryMixin
):
    resource_classes = [SemesterResource]
    form = SemesterForm

    def _is_manager(self, request) -> bool:
        return is_module_manager(request.user, 'academia')

    list_display = (
        'status_text',
        'code',
        'display_name',
        'start_date',
        'end_date',
        'is_active_badge',
        'ects_adjustment',
        'requests_count',
        'audit_entries_count',
        'active_text',
    )

    list_filter = ('is_active', 'start_date', 'created_at')
    search_fields = ('code', 'display_name')
    ordering = ('-start_date',)

    fieldsets = (
        (_("Basic Information"), {
            'fields': ('code', 'display_name', 'start_date', 'end_date')
        }),
        (_("Public Filing"), {
            'fields': ('is_active', 'access_password')
        }),
        (_("ECTS Configuration"), {
            'fields': ('ects_adjustment',)
        }),
        (_("Audit Tracking"), {
            'fields': ('audit_generated_at', 'audit_pdf', 'audit_sent_university_at'),
            'classes': ('collapse',)
        }),
        (_("HankoSign"), {
            'fields': ('signatures_box',)
        }),
        (_("System"), {
            'fields': ('version', 'created_at', 'updated_at')
        }),
    )

    readonly_fields = (
        'access_password',
        'audit_generated_at',
        'signatures_box',
        'version',
        'created_at',
        'updated_at'
    )

    autocomplete_fields = []

    change_actions = (
        'regenerate_password',
        'lock_semester',
        'unlock_semester',
        'synchronize_audit',
        'generate_audit_pdf',
        'verify_audit',
        'send_to_university',
    )

    def get_change_actions(self, request, object_id, form_url):
        actions = list(super().get_change_actions(request, object_id, form_url))
        obj = self.get_object(request, object_id)

        if not obj or not self._is_manager(request):
            return []

        def drop(*names):
            for n in names:
                if n in actions:
                    actions.remove(n)

        st = state_snapshot(obj)

        # Only superusers can regenerate password
        if not request.user.is_superuser:
            drop('regenerate_password')

        # Lock/unlock based on state
        if st.get('explicit_locked'):
            drop('lock_semester')
            # Audit actions only when locked
        else:
            drop('unlock_semester', 'synchronize_audit', 'generate_audit_pdf', 'verify_audit', 'send_to_university')
            return actions

        # Verify only if PDF exists
        if not obj.audit_pdf:
            drop('verify_audit')

        # Send only if verified
        if not has_sig(obj, 'VERIFY', ''):
            drop('send_to_university')

        return actions

    @transaction.atomic
    @safe_admin_action
    def regenerate_password(self, request, obj):
        if not request.user.is_superuser:
            raise PermissionDenied(_("Only superusers can regenerate passwords"))
        old_password = obj.access_password
        obj.access_password = generate_semester_password()
        obj.save(update_fields=['access_password'])
        messages.success(
            request,
            _("Password regenerated: %(old)s → %(new)s") % {
                'old': old_password,
                'new': obj.access_password
            }
        )

    regenerate_password.label = _("Regenerate Password")
    regenerate_password.attrs = {
        "class": "btn btn-block btn-secondary",
        "style": "margin-bottom: 1rem;",
    }

    @transaction.atomic
    @safe_admin_action
    def lock_semester(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))
        action = get_action("LOCK:-@academia.Semester")
        if not action:
            messages.error(request, _("Lock action not configured"))
            return
        record_signature(
            request.user,
            action,
            obj,
            note=f"Semester {obj.code} locked for audit"
        )
        obj.is_active = False
        obj.save(update_fields=['is_active'])
        messages.success(request, _("Semester locked. Public filing closed."))

    lock_semester.label = _("Lock Semester")
    lock_semester.attrs = {
        "class": "btn btn-block btn-warning",
        "style": "margin-bottom: 1rem;",
    }

    @transaction.atomic
    @safe_admin_action
    def unlock_semester(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))
        action = get_action("UNLOCK:-@academia.Semester")
        if not action:
            messages.error(request, _("Unlock action not configured"))
            return
        record_signature(
            request.user,
            action,
            obj,
            note=f"Semester {obj.code} unlocked for corrections"
        )
        messages.warning(request, _("Semester unlocked. Use with caution."))

    unlock_semester.label = _("Unlock Semester")
    unlock_semester.attrs = {
        "class": "btn btn-block btn-success",
        "style": "margin-bottom: 1rem;",
    }

    @transaction.atomic
    @safe_admin_action
    def synchronize_audit(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))
        created, skipped = synchronize_audit_entries(obj)
        messages.success(
            request,
            _("Audit synchronized: %(created)d entries created, %(skipped)d existing.") % {
                'created': created,
                'skipped': skipped
            }
        )

    synchronize_audit.label = _("Synchronize Audit Entries")
    synchronize_audit.attrs = {
        "class": "btn btn-block btn-primary",
        "style": "margin-bottom: 1rem;",
    }

    @transaction.atomic
    @safe_admin_action
    def generate_audit_pdf(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))

        # Get all audit entries for this semester
        entries = obj.audit_entries.all().select_related('person', 'semester').prefetch_related('person_roles', 'inbox_requests')

        if not entries:
            messages.warning(request, _("No audit entries found. Run synchronization first."))
            return

        date_str = timezone.localtime().strftime("%Y-%m-%d")
        signatures = seal_signatures_context(obj)

        ctx = {
            'semester': obj,
            'entries': entries,
            'org': OrgInfo.get_solo(),
            'signatures': signatures,
            'generated_date': timezone.localdate(),
        }

        return render_pdf_response(
            "academia/semester_audit_pdf.html",
            ctx,
            request,
            f"ECTS-AUDIT_{obj.code}_{date_str}.pdf"
        )

    generate_audit_pdf.label = "🖨️ " + _("Generate Audit PDF")
    generate_audit_pdf.attrs = {
        "class": "btn btn-block btn-info",
        "style": "margin-bottom: 1rem;",
    }

    @transaction.atomic
    @safe_admin_action
    def verify_audit(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))
        action = get_action("VERIFY:-@academia.Semester")
        if not action:
            messages.error(request, _("Verify action not configured"))
            return
        record_signature(
            request.user,
            action,
            obj,
            note=f"Audit verified for semester {obj.code}"
        )
        # Lock all audit entries
        for entry in obj.audit_entries.all():
            lock_action = get_action("LOCK:-@academia.SemesterAuditEntry")
            if lock_action:
                record_signature(
                    request.user,
                    lock_action,
                    entry,
                    note=f"Locked via semester {obj.code} verification"
                )
        messages.success(request, _("Audit verified. All entries locked."))

    verify_audit.label = _("Verify Audit")
    verify_audit.attrs = {
        "class": "btn btn-block btn-success",
        "style": "margin-bottom: 1rem;",
    }

    @transaction.atomic
    @safe_admin_action
    def send_to_university(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))
        action = get_action("RELEASE:-@academia.Semester")
        if not action:
            messages.error(request, _("Release action not configured"))
            return
        sign_once(
            request,
            action,
            obj,
            note=f"Audit sent to university for semester {obj.code}",
            window_seconds=10
        )
        obj.audit_sent_university_at = timezone.now()
        obj.save(update_fields=['audit_sent_university_at'])
        messages.success(
            request,
            _("Audit sent timestamp recorded: %(time)s") % {
                'time': obj.audit_sent_university_at.strftime('%Y-%m-%d %H:%M')
            }
        )

    send_to_university.label = _("Send to University")
    send_to_university.attrs = {
        "class": "btn btn-block btn-success",
        "style": "margin-bottom: 1rem;",
    }

    # Display methods
    @admin.display(description=_("Status"))
    def status_text(self, obj):
        return object_status_span(obj, final_stage="")

    @admin.display(description=_("Filing"), boolean=True)
    def is_active_badge(self, obj):
        return obj.is_active

    @admin.display(description=_("Requests"))
    def requests_count(self, obj):
        count = obj.inbox_requests.count()
        return str(count)

    @admin.display(description=_("Audit"))
    def audit_entries_count(self, obj):
        count = obj.audit_entries.count()
        return str(count)

    @admin.display(description=_("Locked"))
    def active_text(self, obj):
        if not obj:
            return "—"
        st = state_snapshot(obj)
        is_locked = st.get("explicit_locked", False)
        return boolean_status_span(
            value=not is_locked,
            true_label=_("Open"),
            false_label=_("Locked"),
            true_code="ok",
            false_code="off",
        )

    @admin.display(description=_("Signatures"))
    def signatures_box(self, obj):
        return render_signatures_box(obj)


@admin.register(InboxRequest)
class InboxRequestAdmin(
    SimpleHistoryAdmin,
    DjangoObjectActions,
    ImportExportModelAdmin,
    ConcurrentModelAdmin,
    HelpPageMixin,
    ImportExportGuardMixin,
    ManagerOnlyHistoryMixin
):
    resource_classes = [InboxRequestResource]
    form = InboxRequestForm
    inlines = [InboxCourseInline]

    def _is_manager(self, request) -> bool:
        return is_module_manager(request.user, 'academia')

    list_display = (
        'status_text',
        'reference_code',
        'person_name',
        'person_role',
        'semester',
        'total_ects_display',
        'created_at',
        'active_text',
    )

    list_filter = ('semester', 'created_at')
    search_fields = (
        'reference_code',
        'person_role__person__last_name',
        'person_role__person__first_name',
        'person_role__role__name'
    )
    ordering = ('-created_at',)

    fieldsets = (
        (_("Identification"), {
            'fields': ('reference_code', 'semester', 'person_role')
        }),
        (_("Student Input"), {
            'fields': ('student_note',)
        }),
        (_("Affidavits"), {
            'fields': ('affidavit1_confirmed_at', 'affidavit2_confirmed_at')
        }),
        (_("Form Upload"), {
            'fields': ('uploaded_form', 'uploaded_form_at', 'submission_ip')
        }),
        (_("ECTS Summary"), {
            'fields': ('total_ects_readonly', 'max_ects_readonly', 'validation_status')
        }),
        (_("HankoSign"), {
            'fields': ('signatures_box',)
        }),
        (_("System"), {
            'fields': ('version', 'created_at', 'updated_at')
        }),
    )

    readonly_fields = (
        'reference_code',
        'total_ects_readonly',
        'max_ects_readonly',
        'validation_status',
        'signatures_box',
        'version',
        'created_at',
        'updated_at'
    )

    autocomplete_fields = ['person_role', 'semester']

    change_actions = (
        'verify_request',
        'approve_request',
        'reject_request',
        'print_form',
    )

    def get_change_actions(self, request, object_id, form_url):
        actions = list(super().get_change_actions(request, object_id, form_url))
        obj = self.get_object(request, object_id)

        if not obj or not self._is_manager(request):
            return []

        def drop(*names):
            for n in names:
                if n in actions:
                    actions.remove(n)

        stage = obj.stage

        if stage == 'DRAFT':
            drop('verify_request', 'approve_request', 'reject_request', 'print_form')
        elif stage == 'SUBMITTED':
            drop('approve_request', 'reject_request')
        elif stage == 'VERIFIED':
            drop('verify_request')
        elif stage in ('APPROVED', 'REJECTED', 'TRANSFERRED'):
            drop('verify_request', 'approve_request', 'reject_request')

        return actions

    @transaction.atomic
    @safe_admin_action
    def verify_request(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))
        if not obj.uploaded_form:
            raise ValidationError(_("Cannot verify: No form uploaded yet"))
        is_valid, max_ects, total_ects, message = validate_ects_total(obj)
        if not is_valid:
            messages.warning(request, _("Warning: ") + message)
        action = get_action("VERIFY:-@academia.InboxRequest")
        if not action:
            messages.error(request, _("Verify action not configured"))
            return
        record_signature(
            request.user,
            action,
            obj,
            note=f"Request {obj.reference_code} verified"
        )
        messages.success(request, _("Request verified. Ready for chair approval."))

    verify_request.label = _("Verify Request")
    verify_request.attrs = {
        "class": "btn btn-block btn-primary",
        "style": "margin-bottom: 1rem;",
    }

    @transaction.atomic
    @safe_admin_action
    def approve_request(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))
        action = get_action("APPROVE:CHAIR@academia.InboxRequest")
        if not action:
            messages.error(request, _("Approve action not configured"))
            return
        record_signature(
            request.user,
            action,
            obj,
            note=f"Request {obj.reference_code} approved by chair"
        )
        messages.success(request, _("Request approved."))

    approve_request.label = _("Approve (Chair)")
    approve_request.attrs = {
        "class": "btn btn-block btn-success",
        "style": "margin-bottom: 1rem;",
    }

    @transaction.atomic
    @safe_admin_action
    def reject_request(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))
        action = get_action("REJECT:CHAIR@academia.InboxRequest")
        if not action:
            messages.error(request, _("Reject action not configured"))
            return
        record_signature(
            request.user,
            action,
            obj,
            note=f"Request {obj.reference_code} rejected by chair"
        )
        messages.warning(request, _("Request rejected. Student should contact administration."))

    reject_request.label = _("Reject (Chair)")
    reject_request.attrs = {
        "class": "btn btn-block btn-danger",
        "style": "margin-bottom: 1rem;",
    }

    @safe_admin_action
    def print_form(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))
        action = get_action("RELEASE:-@academia.InboxRequest")
        if not action:
            messages.error(request, _("Release action not configured"))
            return
        sign_once(
            request,
            action,
            obj,
            note=f"Form printed for {obj.reference_code}",
            window_seconds=10
        )
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        signatures = seal_signatures_context(obj)
        lname = slugify(obj.person_role.person.last_name)[:20]

        ctx = {
            'request_obj': obj,
            'org': OrgInfo.get_solo(),
            'signatures': signatures,
        }

        return render_pdf_response(
            "academia/inboxrequest_form_pdf.html",
            ctx,
            request,
            f"ECTS-REQUEST_{obj.reference_code}_{lname}_{date_str}.pdf"
        )

    print_form.label = "🖨️ " + _("Print Form")
    print_form.attrs = {
        "class": "btn btn-block btn-info",
        "style": "margin-bottom: 1rem;",
    }

    # Display methods
    @admin.display(description=_("Status"))
    def status_text(self, obj):
        stage = obj.stage
        stage_to_code = {
            'DRAFT': 'draft',
            'SUBMITTED': 'submitted',
            'VERIFIED': 'pending',
            'APPROVED': 'final',
            'REJECTED': 'rejected',
            'TRANSFERRED': 'locked',
        }
        code = stage_to_code.get(stage, 'draft')
        return format_html('<span class="js-state" data-state="{}">{}</span>', code, stage)

    @admin.display(description=_("Person"))
    def person_name(self, obj):
        person = obj.person_role.person
        return f"{person.first_name} {person.last_name}"

    @admin.display(description=_("ECTS"))
    def total_ects_display(self, obj):
        return str(obj.total_ects)

    @admin.display(description=_("Total ECTS"))
    def total_ects_readonly(self, obj):
        return f"{obj.total_ects} ECTS"

    @admin.display(description=_("Max Entitled"))
    def max_ects_readonly(self, obj):
        is_valid, max_ects, total_ects, message = validate_ects_total(obj)
        return f"{max_ects} ECTS"

    @admin.display(description=_("Validation"))
    def validation_status(self, obj):
        is_valid, max_ects, total_ects, message = validate_ects_total(obj)
        return boolean_status_span(
            value=is_valid,
            true_label=_("Valid"),
            false_label=_("Exceeds"),
            true_code="ok",
            false_code="error",
        )

    @admin.display(description=_("Locked"))
    def active_text(self, obj):
        if not obj:
            return "—"
        st = state_snapshot(obj)
        is_locked = st.get("locked", False)
        if obj.semester:
            semester_st = state_snapshot(obj.semester)
            if semester_st.get("explicit_locked"):
                is_locked = True
        return boolean_status_span(
            value=not is_locked,
            true_label=_("Open"),
            false_label=_("Locked"),
            true_code="ok",
            false_code="off",
        )

    @admin.display(description=_("Signatures"))
    def signatures_box(self, obj):
        return render_signatures_box(obj)

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj:
            st = state_snapshot(obj)
            if st.get('locked') or (obj.semester and state_snapshot(obj.semester).get('explicit_locked')):
                ro.extend([
                    'semester', 'person_role', 'student_note',
                    'affidavit1_confirmed_at', 'affidavit2_confirmed_at',
                    'uploaded_form', 'uploaded_form_at', 'submission_ip'
                ])
        return ro


@admin.register(SemesterAuditEntry)
class SemesterAuditEntryAdmin(
    SimpleHistoryAdmin,
    DjangoObjectActions,
    ImportExportModelAdmin,
    ConcurrentModelAdmin,
    HelpPageMixin,
    ImportExportGuardMixin,
    ManagerOnlyHistoryMixin
):
    resource_classes = [SemesterAuditEntryResource]
    form = SemesterAuditEntryForm

    def _is_manager(self, request) -> bool:
        return is_module_manager(request.user, 'academia')

    list_display = (
        'status_text',
        'person',
        'semester',
        'roles_count',
        'max_ects_entitled',
        'ects_reimbursed',
        'ects_bulk',
        'active_text',
    )

    list_filter = ('semester', 'generated_at')
    search_fields = (
        'person__last_name',
        'person__first_name',
        'semester__code'
    )
    ordering = ('semester', 'person__last_name', 'person__first_name')

    fieldsets = (
        (_("Identification"), {
            'fields': ('semester', 'person')
        }),
        (_("ECTS Calculation"), {
            'fields': (
                'max_ects_entitled',
                'ects_reimbursed',
                'ects_bulk',
                'calculation_details_display'
            )
        }),
        (_("Relationships"), {
            'fields': ('person_roles', 'inbox_requests'),
            'classes': ('collapse',)
        }),
        (_("Notes"), {
            'fields': ('notes',)
        }),
        (_("HankoSign"), {
            'fields': ('signatures_box',)
        }),
        (_("System"), {
            'fields': ('version', 'generated_at', 'updated_at')
        }),
    )

    readonly_fields = (
        'calculation_details_display',
        'signatures_box',
        'version',
        'generated_at',
        'updated_at'
    )

    autocomplete_fields = ['semester', 'person']
    filter_horizontal = ['person_roles', 'inbox_requests']

    change_actions = (
        'lock_entry',
        'unlock_entry',
    )

    def get_change_actions(self, request, object_id, form_url):
        actions = list(super().get_change_actions(request, object_id, form_url))
        obj = self.get_object(request, object_id)

        if not obj or not self._is_manager(request):
            return []

        def drop(*names):
            for n in names:
                if n in actions:
                    actions.remove(n)

        st = state_snapshot(obj)
        if st.get('explicit_locked'):
            drop('lock_entry')
        else:
            drop('unlock_entry')

        return actions

    @transaction.atomic
    @safe_admin_action
    def lock_entry(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))
        action = get_action("LOCK:-@academia.SemesterAuditEntry")
        if not action:
            messages.error(request, _("Lock action not configured"))
            return
        record_signature(
            request.user,
            action,
            obj,
            note=f"Audit entry locked for {obj.person}"
        )
        messages.success(request, _("Audit entry locked."))

    lock_entry.label = _("Lock Entry")
    lock_entry.attrs = {
        "class": "btn btn-block btn-warning",
        "style": "margin-bottom: 1rem;",
    }

    @transaction.atomic
    @safe_admin_action
    def unlock_entry(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))
        action = get_action("UNLOCK:-@academia.SemesterAuditEntry")
        if not action:
            messages.error(request, _("Unlock action not configured"))
            return
        record_signature(
            request.user,
            action,
            obj,
            note=f"Audit entry unlocked for corrections: {obj.person}"
        )
        messages.warning(request, _("Audit entry unlocked for corrections."))

    unlock_entry.label = _("Unlock Entry")
    unlock_entry.attrs = {
        "class": "btn btn-block btn-success",
        "style": "margin-bottom: 1rem;",
    }

    # Display methods
    @admin.display(description=_("Status"))
    def status_text(self, obj):
        return object_status_span(obj, final_stage="")

    @admin.display(description=_("Roles"))
    def roles_count(self, obj):
        return str(obj.person_roles.count())

    @admin.display(description=_("Calculation Details"))
    def calculation_details_display(self, obj):
        if not obj.calculation_details:
            return _("No details available")
        details = obj.calculation_details
        lines = []
        if 'roles' in details:
            lines.append(_("Roles:"))
            for role in details['roles']:
                lines.append(
                    f"  • {role.get('role_name', '?')}: "
                    f"{role.get('nominal_ects', 0)} ECTS × "
                    f"{role.get('percentage', 0)*100:.1f}% = "
                    f"{role.get('aliquoted_ects', 0)} ECTS"
                )
        if 'bonus_malus' in details:
            bm = details['bonus_malus']
            if bm != 0:
                lines.append(f"Bonus/Malus: {bm:+.1f} ECTS")
        return "\n".join(lines)

    @admin.display(description=_("Locked"))
    def active_text(self, obj):
        if not obj:
            return "—"
        st = state_snapshot(obj)
        is_locked = st.get("explicit_locked", False)
        return boolean_status_span(
            value=not is_locked,
            true_label=_("Open"),
            false_label=_("Locked"),
            true_code="ok",
            false_code="off",
        )

    @admin.display(description=_("Signatures"))
    def signatures_box(self, obj):
        return render_signatures_box(obj)

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj:
            st = state_snapshot(obj)
            if st.get('explicit_locked'):
                ro.extend([
                    'semester', 'person', 'person_roles', 'inbox_requests',
                    'max_ects_entitled', 'ects_reimbursed', 'ects_bulk',
                    'calculation_details'
                ])
        return ro
