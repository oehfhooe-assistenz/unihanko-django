# File: academia_audit/admin.py
# Version: 1.0.5
# Author: vas
# Modified: 2025-12-08

from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _
from django.utils.text import slugify
from django.utils import timezone
from django_object_actions import DjangoObjectActions
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from simple_history.admin import SimpleHistoryAdmin
from django.db import transaction
from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from annotations.admin import AnnotationInline
from annotations.views import create_system_annotation
from core.admin_mixins import log_deletions
from core.admin_mixins import ImportExportGuardMixin, safe_admin_action, HistoryGuardMixin, with_help_widget
from core.pdf import render_pdf_response
from core.utils.authz import is_academia_audit_manager
from core.utils.bool_admin_status import boolean_status_span
from hankosign.utils import (
    render_signatures_box, state_snapshot, get_action,
    record_signature, RID_JS, sign_once, seal_signatures_context, has_sig,
    object_status_span
)
from organisation.models import OrgInfo
from concurrency.admin import ConcurrentModelAdmin
from django_admin_inline_paginator_plus.admin import StackedInlinePaginated
from .models import AuditSemester, AuditEntry
from .utils import synchronize_audit_entries


# ============================================================================
# RESOURCES (Import/Export)
# ============================================================================

class AuditSemesterResource(resources.ModelResource):
    class Meta:
        model = AuditSemester
        fields = ('id', 'semester__code', 'audit_sent_university_at', 'created_at', 'updated_at')
        export_order = fields


class AuditEntryResource(resources.ModelResource):
    class Meta:
        model = AuditEntry
        fields = (
            'id', 'audit_semester__semester__code', 'person__last_name', 'person__first_name',
            'aliquoted_ects', 'final_ects', 'reimbursed_ects', 'remaining_ects',
            'checked_at', 'created_at', 'updated_at'
        )
        export_order = fields


# ============================================================================
# INLINES (add before AuditSemesterAdmin class)
# ============================================================================

class AuditEntryInline(StackedInlinePaginated):
    model = AuditEntry
    extra = 0
    fieldsets = (
        (_("Person"), {
            'fields': ('person',)
        }),
        (_("ECTS Calculations"), {
            'fields': (
                'aliquoted_ects',
                'final_ects',
                'reimbursed_ects',
                'remaining_ects',
            )
        }),
        (_("Review"), {
            'fields': ('linked_pdfs_display', 'checked_at', 'notes')
        }),
    )
    per_page = 5
    pagination_key = "audit-entry"
    readonly_fields = ('person', 'linked_pdfs_display')  # Scope field always readonly
    autocomplete_fields = ('person',)
    show_change_link = True
    can_delete = False
    
    def get_max_num(self, request, obj=None, **kwargs):
        return 100  # Reasonable limit
    
    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        
        # If parent audit semester is locked, lock everything
        if obj:
            st = state_snapshot(obj)
            if st.get("explicit_locked"):
                ro.extend([
                    'aliquoted_ects',
                    'final_ects',
                    'reimbursed_ects',
                    'remaining_ects',
                    'notes',
                ])
        
        return ro
    
    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, AuditEntry) and instance.pk:
                # Auto-set checked_at when ECTS fields are modified via inline
                original = AuditEntry.objects.get(pk=instance.pk)
                ects_fields = ['aliquoted_ects', 'final_ects', 'reimbursed_ects', 'remaining_ects', 'notes']
                changed = any(
                    getattr(instance, field) != getattr(original, field)
                    for field in ects_fields
                )
                if changed:
                    instance.checked_at = timezone.now()
            instance.save()
        formset.save_m2m()
    
    @admin.display(description=_("Request Forms"))
    def linked_pdfs_display(self, obj):
        """Display links to all uploaded forms from linked inbox requests."""
        from django.utils.safestring import mark_safe
        
        if not obj or not obj.pk:
            return "—"
        
        requests = obj.inbox_requests.all()
        if not requests:
            return _("No requests")
        
        links = []
        for req in requests:
            if req.uploaded_form:
                url = req.uploaded_form.url
                links.append(f'<a href="{url}" target="_blank">📄 {req.reference_code}</a>')
            else:
                links.append(f'<span style="color: #999;">{req.reference_code} (no form)</span>')
        
        return mark_safe('<br>'.join(links))

    def has_add_permission(self, request, obj):
        # Can't add entries via inline - use synchronize action
        return False
    
    def has_delete_permission(self, request, obj=None):
        # Never allow deletion via inline
        return False

# ============================================================================
# AUDIT SEMESTER ADMIN
# ============================================================================

@log_deletions
@with_help_widget
@admin.register(AuditSemester)
class AuditSemesterAdmin(
    SimpleHistoryAdmin,
    DjangoObjectActions,
    ImportExportModelAdmin,
    ConcurrentModelAdmin,
    ImportExportGuardMixin,
    HistoryGuardMixin
):
    resource_classes = [AuditSemesterResource]
    inlines = [AuditEntryInline, AnnotationInline]
    list_display = (
        'status_text',
        'semester_code',
        'semester_display_name',
        'semester_dates',
        'entry_count',
        'updated_at',
        'active_text',
    )
    list_display_links = ('semester_code',)
    search_fields = ('semester__code', 'semester__display_name')
    autocomplete_fields = ('semester',)
    readonly_fields = (
        'semester_code_display',
        'semester_start_date_display',
        'semester_end_date_display',
        'created_at',
        'updated_at',
        'signatures_box',
        'audit_generated_at',
        'audit_sent_university_at'
    )

    fieldsets = (
        (_("Scope"), {
            'fields': (
                'semester',
                'semester_code_display',
                'semester_start_date_display',
                'semester_end_date_display',
            )
        }),
        (_("Audit Workflow"), {
            'fields': ('audit_generated_at', 'audit_pdf', 'audit_sent_university_at',)
        }),
        (_("Workflow & HankoSign"), {
            'fields': ('signatures_box',)
        }),
        (_("System"), {
            'fields': ('version', 'created_at', 'updated_at')
        }),
    )

    change_actions = (
        'lock_audit',
        'unlock_audit',
        'synchronize_entries',
        'verify_audit_complete',
        'approve_audit',
        'reject_audit',
        'verify_audit_sent',
        'print_audit_pdf',
    )

    def get_queryset(self, request):
        from django.db.models import Count
        qs = super().get_queryset(request)
        qs = qs.select_related('semester').annotate(_entry_count=Count('entries'))
        return qs

    def _is_manager(self, request):
        return is_academia_audit_manager(request.user)

    @admin.display(description=_("Status"))
    def status_text(self, obj):
        # AuditSemester uses CHAIR approval
        return object_status_span(obj, final_stage="CHAIR")

    @admin.display(description=_("Semester"))
    def semester_code(self, obj):
        return obj.semester.code if obj.semester else "—"

    @admin.display(description=_("Name"))
    def semester_display_name(self, obj):
        return obj.semester.display_name if obj.semester else "—"

    @admin.display(description=_("Period"))
    def semester_dates(self, obj):
        if not obj.semester:
            return "—"
        return f"{obj.semester.start_date:%Y-%m-%d} → {obj.semester.end_date:%Y-%m-%d}"

    @admin.display(description=_("Entries"), ordering='_entry_count')
    def entry_count(self, obj):
        return str(obj._entry_count)

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

    @admin.display(description=_("Semester Code"))
    def semester_code_display(self, obj):
        return obj.semester.code if obj.semester else "—"

    @admin.display(description=_("Start Date"))
    def semester_start_date_display(self, obj):
        return obj.semester.start_date if obj.semester else "—"

    @admin.display(description=_("End Date"))
    def semester_end_date_display(self, obj):
        return obj.semester.end_date if obj.semester else "—"

    @admin.display(description=_("Signatures"))
    def signatures_box(self, obj):
        return render_signatures_box(obj)

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj:
            ro.extend(['semester'])
        return ro

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
        approved = st.get("approved", set())
        is_locked = st.get("explicit_locked", False)

        # Lock/unlock visibility
        if is_locked:
            drop('lock_audit')
        else:
            drop('unlock_audit')

        # Workflow visibility
        if not is_locked:
            # Can't do audit workflows unless locked
            drop('verify_audit_complete', 'approve_audit', 'reject_audit', 'verify_audit_sent')
        else:
            # Locked audit workflows
            if st.get("verified"):
                drop('synchronize_entries')
                # After verified, can't verify again (not repeatable)
                drop('verify_audit_complete')

                # After verified, show approve/reject unless already done
                if "CHAIR" in approved:
                    drop('approve_audit', 'reject_audit')
                else:
                    # Waiting for chair approval
                    pass

                # Verify sent only after chair approval
                if "CHAIR" not in approved:
                    drop('verify_audit_sent')
            else:
                # Not verified yet
                drop('approve_audit', 'reject_audit', 'verify_audit_sent')

        return actions

    @transaction.atomic
    @safe_admin_action
    def lock_audit(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))
        st = state_snapshot(obj)
        if st.get("explicit_locked"):
            messages.info(request, _("Already locked."))
            return
        action = get_action("LOCK:-@academia_audit.AuditSemester")
        if not action:
            messages.error(request, _("Lock action not configured."))
            return
        record_signature(request, action, obj, note=f"Audit semester {obj.semester.code} locked")
        create_system_annotation(obj, "LOCK", user=request.user)
        messages.success(request, _("Audit semester locked."))

    lock_audit.label = _("Lock Audit")
    lock_audit.attrs = {"class": "btn btn-block btn-warning", "style": "margin-bottom: 1rem;"}

    @transaction.atomic
    @safe_admin_action
    def unlock_audit(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))
        st = state_snapshot(obj)
        if not st.get("explicit_locked"):
            messages.info(request, _("Already unlocked."))
            return
        action = get_action("UNLOCK:-@academia_audit.AuditSemester")
        if not action:
            messages.error(request, _("Unlock action not configured."))
            return
        record_signature(request, action, obj, note=f"Audit semester {obj.semester.code} unlocked")
        create_system_annotation(obj, "UNLOCK", user=request.user)
        messages.success(request, _("Audit semester unlocked."))

    unlock_audit.label = _("Unlock Audit")
    unlock_audit.attrs = {"class": "btn btn-block btn-success", "style": "margin-bottom: 1rem;"}

    @transaction.atomic
    @safe_admin_action
    def synchronize_entries(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))
        created, updated, skipped = synchronize_audit_entries(obj)
        create_system_annotation(obj, note=f"Synchronized: {created} created, {updated} updated, {skipped} skipped", user=request.user)
        messages.success(
            request,
            _("Audit synchronized: %(created)d created, %(updated)d updated, %(skipped)d skipped (manually checked).") % {
                'created': created,
                'updated': updated,
                'skipped': skipped,
            }
        )
    synchronize_entries.label = _("Synchronize Audit Entries")
    synchronize_entries.attrs = {"class": "btn btn-block btn-primary", "style": "margin-bottom: 1rem;"}

    @transaction.atomic
    @safe_admin_action
    def verify_audit_complete(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))

        # Check that all entries are checked
        unchecked = obj.entries.filter(checked_at__isnull=True).count()
        if unchecked > 0:
            messages.warning(
                request,
                _("Cannot verify: %(count)d entries are not yet manually checked.") % {'count': unchecked}
            )
            return

        action = get_action("VERIFY:-@academia_audit.AuditSemester")
        if not action:
            messages.error(request, _("Verify action not configured."))
            return
        record_signature(request, action, obj, note=f"Audit complete for {obj.semester.code}")
        create_system_annotation(obj, "VERIFY", user=request.user)
        messages.success(request, _("Audit verified complete."))

    verify_audit_complete.label = _("Verify Audit Complete")
    verify_audit_complete.attrs = {"class": "btn btn-block btn-success", "style": "margin-bottom: 1rem;"}

    @transaction.atomic
    @safe_admin_action
    def approve_audit(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))
        st = state_snapshot(obj)
        if not st.get("verified"):
            messages.warning(request, _("Verify audit complete first."))
            return
        if "CHAIR" in st.get("approved", set()):
            messages.info(request, _("Already approved."))
            return
        action = get_action("APPROVE:CHAIR@academia_audit.AuditSemester")
        if not action:
            messages.error(request, _("Approval action not configured."))
            return
        record_signature(request, action, obj, note=f"Audit approved for {obj.semester.code}")
        create_system_annotation(obj, "APPROVE", user=request.user)
        messages.success(request, _("Audit approved by chair."))
    approve_audit.label = _("Approve (Chair)")
    approve_audit.attrs = {"class": "btn btn-block btn-success", "style": "margin-bottom: 1rem;"}

    @transaction.atomic
    @safe_admin_action
    def reject_audit(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))
        st = state_snapshot(obj)
        if "CHAIR" in st.get("approved", set()):
            messages.warning(request, _("Already approved; cannot reject."))
            return
        action = get_action("REJECT:CHAIR@academia_audit.AuditSemester")
        if not action:
            messages.error(request, _("Reject action not configured."))
            return
        record_signature(request, action, obj, note=f"Audit rejected for {obj.semester.code}")
        create_system_annotation(obj, "REJECT", user=request.user)
        messages.warning(request, _("Audit rejected. Please review and re-verify."))
    reject_audit.label = _("Reject (Chair)")
    reject_audit.attrs = {"class": "btn btn-block btn-danger", "style": "margin-bottom: 1rem;"}

    @transaction.atomic
    @safe_admin_action
    def verify_audit_sent(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))
        st = state_snapshot(obj)
        if "CHAIR" not in st.get("approved", set()):
            messages.warning(request, _("Chair approval required first."))
            return
        action = get_action("VERIFY:SENT@academia_audit.AuditSemester")
        if not action:
            messages.error(request, _("Verify sent action not configured."))
            return

        # Set timestamp
        obj.audit_sent_university_at = timezone.now()
        obj.save(update_fields=['audit_sent_university_at'])

        record_signature(request, action, obj, note=f"Audit sent to university for {obj.semester.code}")
        create_system_annotation(obj, "VERIFY", user=request.user)
        messages.success(request, _("Verified: Audit sent to university."))

    verify_audit_sent.label = _("Verify Audit Sent")
    verify_audit_sent.attrs = {"class": "btn btn-block btn-primary", "style": "margin-bottom: 1rem;"}

    @safe_admin_action
    def print_audit_pdf(self, request, obj):
        if not self._is_manager(request):
            raise PermissionDenied(_("Not authorized"))

        entries = obj.entries.all().select_related('person', 'audit_semester__semester').prefetch_related('person_roles', 'inbox_requests')
        if not entries:
            messages.warning(request, _("No entries found. Run synchronization first."))
            return

        action = get_action("RELEASE:-@academia_audit.AuditSemester")
        if not action:
            messages.error(request, _("Release action not configured."))
            return
        sign_once(request, action, obj, note=_("Printed audit PDF"), window_seconds=10)

        date_str = timezone.localtime().strftime("%Y-%m-%d")
        signatures = seal_signatures_context(obj)

        ctx = {
            'audit_semester': obj,
            'semester': obj.semester,
            'entries': entries,
            'org': OrgInfo.get_solo(),
            'signatures': signatures,
            'generated_date': timezone.localdate(),
        }

        return render_pdf_response(
            "academia_audit/audit_semester_pdf.html",
            ctx,
            request,
            f"ECTS-AUDIT_{obj.semester.code}_{date_str}.pdf"
        )

    print_audit_pdf.label = "🖨️ " + _("Print Audit PDF")
    print_audit_pdf.attrs = {
        "class": "btn btn-block btn-info",
        "style": "margin-bottom: 1rem;",
        "data-action": "post-object",
        "onclick": RID_JS
    }

    def has_delete_permission(self, request, obj=None):
        return False


# ============================================================================
# AUDIT ENTRY ADMIN
# ============================================================================

@log_deletions
@with_help_widget
@admin.register(AuditEntry)
class AuditEntryAdmin(
    SimpleHistoryAdmin,
    ImportExportModelAdmin,
    ConcurrentModelAdmin,
    ImportExportGuardMixin,
    HistoryGuardMixin
):
    resource_classes = [AuditEntryResource]

    list_display = (
        'person',
        'audit_semester_code',
        'final_ects',
        'reimbursed_ects',
        'remaining_ects',
        'checked_status',
        'updated_at',
        'active_text',
    )
    list_display_links = ('person',)
    list_filter = ('audit_semester', 'checked_at')
    search_fields = ('person__last_name', 'person__first_name')
    autocomplete_fields = ('audit_semester', 'person')
    readonly_fields = ('created_at', 'updated_at', 'calculation_details_display', 'linked_pdfs_display')
    inlines = [AnnotationInline]
    fieldsets = (
        (_("Scope"), {
            'fields': ('audit_semester', 'person')
        }),
        (_("ECTS Calculations"), {
            'fields': (
                'aliquoted_ects',
                'final_ects',
                'reimbursed_ects',
                'remaining_ects',
                'calculation_details_display'
            )
        }),
        (_("Manual Review"), {
            'fields': ('linked_pdfs_display', 'checked_at')
        }),
        (_("Record note"), {
            'fields': ('notes',)
        }),
        (_("System"), {
            'fields': ('version', 'created_at', 'updated_at')
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        qs = qs.select_related('audit_semester__semester', 'person')
        return qs

    def _is_manager(self, request):
        return is_academia_audit_manager(request.user)

    @admin.display(description=_("Semester"))
    def audit_semester_code(self, obj):
        return obj.audit_semester.semester.code if obj.audit_semester and obj.audit_semester.semester else "—"

    @admin.display(description=_("Checked"))
    def checked_status(self, obj):
        return boolean_status_span(
            value=obj.checked_at is not None,
            true_label=_("Yes"),
            false_label=_("No"),
            true_code="ok",
            false_code="warning",
        )

    @admin.display(description=_("Locked"))
    def active_text(self, obj):
        if not obj or not obj.audit_semester:
            return "—"
        st = state_snapshot(obj.audit_semester)
        is_locked = st.get("explicit_locked", False)
        return boolean_status_span(
            value=not is_locked,
            true_label=_("Open"),
            false_label=_("Locked"),
            true_code="ok",
            false_code="off",
        )
    

    @admin.display(description=_("Linked Request Forms"))
    def linked_pdfs_display(self, obj):
        """Display links to all uploaded forms from linked inbox requests."""
        from django.utils.safestring import mark_safe
        from django.urls import reverse
        
        if not obj.pk:
            return "—"
        
        requests = obj.inbox_requests.all()
        if not requests:
            return "—"
        
        links = []
        for req in requests:
            if req.uploaded_form:
                url = req.uploaded_form.url
                links.append(f'<a href="{url}" target="_blank">📄 {req.reference_code}</a>')
            else:
                links.append(f'{req.reference_code} (no form)')
        
        return mark_safe('<br>'.join(links))

    @admin.display(description=_("Calculation Details"))
    def calculation_details_display(self, obj):
        import json
        from django.utils.safestring import mark_safe
        if not obj.calculation_details:
            return "—"
        formatted = json.dumps(obj.calculation_details, indent=2)
        return mark_safe(f"<pre>{formatted}</pre>")

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj:
            # ALWAYS lock scope fields after creation
            ro.extend(['audit_semester', 'person'])
            
            # Additionally lock calculation fields when parent is locked
            if obj.audit_semester:
                st = state_snapshot(obj.audit_semester)
                if st.get("explicit_locked"):
                    ro.extend(['aliquoted_ects', 'final_ects', 'reimbursed_ects', 
                            'remaining_ects', 'notes', 'person_roles', 'inbox_requests'])
        return ro

    def save_model(self, request, obj, form, change):
        if change:
            # Auto-set checked_at when admin modifies ECTS fields
            ects_fields = {'aliquoted_ects', 'final_ects', 'reimbursed_ects', 'remaining_ects', 'notes'}
            if any(field in form.changed_data for field in ects_fields):
                obj.checked_at = timezone.now()
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return False