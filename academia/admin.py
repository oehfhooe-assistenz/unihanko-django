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
from academia.models import inboxrequest_stage
from annotations.views import create_system_annotation
from annotations.admin import AnnotationInline
from .models import Semester, InboxRequest, InboxCourse, generate_semester_password
from people.models import PersonRole, Person
from organisation.models import OrgInfo
from core.pdf import render_pdf_response
from core.admin_mixins import (
    ImportExportGuardMixin,
    HelpPageMixin,
    safe_admin_action,
    ManagerOnlyHistoryMixin
)
from core.utils.bool_admin_status import boolean_status_span
from hankosign.utils import (
    render_signatures_box,
    state_snapshot,
    get_action,
    record_signature,
    sign_once,
    object_status_span,
    seal_signatures_context,
    RID_JS
)
from .utils import validate_ects_total
from core.utils.authz import is_academia_manager


# =============== Import-Export Resources ===============

class SemesterResource(resources.ModelResource):
    class Meta:
        model = Semester
        fields = (
            'id', 'code', 'display_name', 'start_date', 'end_date',
            'filing_start', 'filing_end', 'ects_adjustment', 'created_at', 'updated_at'
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


# =============== Inline Admins ===============

class InboxCourseInline(admin.StackedInline):
    model = InboxCourse
    form = InboxCourseInlineForm
    extra = 1
    fields = ('course_code', 'course_name', 'ects_amount')

    def has_delete_permission(self, request, obj=None):
        # obj is the parent InboxRequest
        if obj:
            st = state_snapshot(obj)
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
        return is_academia_manager(request.user)

    list_display = (
        'code',
        'display_name',
        'start_date',
        'end_date',
        'filing_window_display',
        'ects_adjustment',
        'requests_count',
        'active_text',
    )
    list_display_links = ('code',)
    list_filter = ('start_date', 'created_at')
    search_fields = ('code', 'display_name')
    ordering = ('-start_date',)
    inlines = [AnnotationInline]
    fieldsets = (
        (_("Basic Information"), {
            'fields': ('code', 'display_name', 'start_date', 'end_date')
        }),
        (_("Public Filing"), {
            'fields': ('filing_start', 'filing_end', 'access_password')
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
        else:
            drop('unlock_semester')

        return actions

    @admin.display(description=_("Filing Window (Web)"))
    def filing_window_display(self, obj):
        if not obj.filing_start or not obj.filing_end:
            return "—"
        now = timezone.now()
        if obj.filing_start <= now <= obj.filing_end:
            return format_html('<span style="color: #10b981; font-weight: 700;">● OPEN</span>')
        elif now < obj.filing_start:
            return format_html('<span style="color: #fbbf24;">⏱ Upcoming</span>')
        else:
            return format_html('<span style="color: #6b7280;">✓ Closed</span>')

    @admin.display(description=_("Requests"))
    def requests_count(self, obj):
        count = obj.inbox_requests.count()
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

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj:
            ro.extend(['code', 'display_name'])
            st = state_snapshot(obj)
            if st.get("explicit_locked"):
                ro += ['start_date', 'end_date', 'filing_start', 'filing_end', 'ects_adjustment']
        return ro

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
        create_system_annotation(obj, "LOCK", user=request.user)
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
        create_system_annotation(obj, "UNLOCK", user=request.user)
        messages.warning(request, _("Semester unlocked. Use with caution."))

    unlock_semester.label = _("Unlock Semester")
    unlock_semester.attrs = {
        "class": "btn btn-block btn-success",
        "style": "margin-bottom: 1rem;",
    }

    def has_delete_permission(self, request, obj=None):
        return False


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
    inlines = [InboxCourseInline, AnnotationInline]

    def _is_manager(self, request) -> bool:
        return is_academia_manager(request.user)

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
    list_display_links = ['reference_code',]
    list_filter = ('semester', 'stage', 'created_at')
    search_fields = (
        'reference_code',
        'person_role__person__last_name',
        'person_role__person__first_name',
        'person_role__role__name'
    )
    ordering = ('-created_at',)

    fieldsets = (
        (_("Identification"), {
            'fields': ('reference_code', 'stage', 'semester', 'person_role')
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
        'stage',
        'affidavit1_confirmed_at',
        'affidavit2_confirmed_at',
        'uploaded_form_at',
        'submission_ip',
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

        stage = inboxrequest_stage(obj)

        if stage in ('DRAFT', 'SUBMITTED'):
            # Can only verify
            drop('approve_request', 'reject_request')
        elif stage == 'VERIFIED':
            # Can approve or reject
            drop('verify_request')
        elif stage in ('APPROVED', 'REJECTED', 'TRANSFERRED'):
            # Final states - only print
            drop('verify_request', 'approve_request', 'reject_request')

        return actions

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
            # ALWAYS lock scope fields after creation
            ro.extend(['semester', 'person_role'])
            
            # Additionally lock other fields if verified/approved
            st = state_snapshot(obj)
            if st.get('locked') or (obj.semester and state_snapshot(obj.semester).get('explicit_locked')):
                ro.extend([
                    'student_note',
                    'affidavit1_confirmed_at', 
                    'affidavit2_confirmed_at',
                    'uploaded_form', 
                    'uploaded_form_at', 
                    'submission_ip'
                ])
        return ro

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
        create_system_annotation(obj, "VERIFY", user=request.user)
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
        create_system_annotation(obj, "APPROVE", user=request.user)
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
        create_system_annotation(obj, "REJECT", user=request.user)
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
            'signers': [
                {'label': obj.person_role.person.last_name},
                {'label': 'LV-Leitung | FH OÖ'},
            ]
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
        "data-action": "post-object",
        "onclick": RID_JS
    }

    def has_delete_permission(self, request, obj=None):
        return False