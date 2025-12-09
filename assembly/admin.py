# File: assembly/admin.py
# Version: 1.0.5
# Author: vas
# Modified: 2025-12-08

from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _
from django.utils.safestring import mark_safe
from django.template.loader import render_to_string
from django.utils.html import format_html
from django.urls import reverse
from django.db import transaction
from django import forms
from django.utils import timezone
from django.utils.text import slugify
from django_object_actions import DjangoObjectActions
from annotations.views import create_system_annotation
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from simple_history.admin import SimpleHistoryAdmin
from concurrency.admin import ConcurrentModelAdmin
from adminsortable2.admin import SortableAdminBase
from annotations.admin import AnnotationInline
from core.admin_mixins import ImportExportGuardMixin, safe_admin_action, HistoryGuardMixin, with_help_widget
from core.pdf import render_pdf_response
from core.utils.authz import is_assembly_manager  # You'll need to create this
from core.utils.bool_admin_status import boolean_status_span, row_state_attr_for_boolean
from hankosign.utils import (
    render_signatures_box, state_snapshot, get_action, 
    record_signature, RID_JS, sign_once, seal_signatures_context,
    object_status_span
)
from organisation.models import OrgInfo
from core.admin_mixins import log_deletions
from .models import Term, Composition, Mandate, Session, SessionItem, Vote, SessionAttendance
from django_admin_inline_paginator_plus.admin import StackedInlinePaginated

# ============================================================================
# RESOURCES (Import/Export)
# ============================================================================

class TermResource(resources.ModelResource):
    class Meta:
        model = Term
        fields = ('id', 'code', 'label', 'start_date', 'end_date', 'is_active')
        export_order = fields


class MandateResource(resources.ModelResource):
    class Meta:
        model = Mandate
        fields = ('id', 'composition', 'position', 'person_role', 'officer_role', 
                  'start_date', 'end_date', 'backup_person_role', 'backup_person_text')
        export_order = fields


class SessionResource(resources.ModelResource):
    class Meta:
        model = Session
        fields = ('id', 'term', 'code', 'session_type', 'session_date', 
                  'session_time', 'location', 'protocol_number')
        export_order = fields


class SessionItemResource(resources.ModelResource):
    class Meta:
        model = SessionItem
        fields = ('id', 'session', 'item_code', 'order', 'kind', 'title', 
                  'voting_mode', 'votes_for', 'votes_against', 'votes_abstain', 'passed')
        export_order = fields


# ============================================================================
# MANDATE ADMIN (Hidden from sidebar, needed for autocomplete)
# ============================================================================

@log_deletions
@with_help_widget
@admin.register(Mandate)
class MandateAdmin(
    SimpleHistoryAdmin, 
    ConcurrentModelAdmin,
    HistoryGuardMixin
    ):
    list_display = ('position', 'person_role', 'officer_role', 'start_date', 'end_date', 'composition')
    list_filter = ('officer_role', 'composition__term')
    search_fields = ('person_role__person__first_name', 'person_role__person__last_name', 
                     'person_role__role__name')
    autocomplete_fields = ('person_role', 'backup_person_role')
    readonly_fields = ('created_at', 'updated_at')
    
    def get_model_perms(self, request):
        # Hide from sidebar - only accessible via inlines/autocomplete
        return {}

# ============================================================================
# INLINES
# ============================================================================

class MandateInline(StackedInlinePaginated):
    model = Mandate
    extra = 1
    max_num = 9
    per_page = 1
    pagination_key = "mandate"
    fields = ('position', 'person_role', 'officer_role', 'party', 'start_date', 'end_date', 
              'backup_person_role', 'backup_person_text')
    autocomplete_fields = ('person_role', 'backup_person_role')
    ordering = ('position',)

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj and obj.term:
            term_st = state_snapshot(obj.term)
            if term_st.get("explicit_locked"):
                ro.extend(['position', 'person_role', 'officer_role', 'start_date', 
                        'end_date', 'backup_person_role', 'backup_person_text', 'party'])
        return ro


class VoteInline(StackedInlinePaginated):
    model = Vote
    extra = 0
    per_page = 10
    pagination_key = "vote"
    fields = ('mandate', 'vote')
    autocomplete_fields = ('mandate',)

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj:
            session_admin = self.admin_site._registry.get(Session)
            if session_admin and session_admin._is_locked(request, obj):
                # For VoteInline: lock both fields
                ro.extend(['mandate', 'vote'])
        return ro
    

class ElectionItemHRLinksInline(StackedInlinePaginated):
    """Inline for editing ELEC items' PersonRole links - stays editable after submission"""
    model = SessionItem
    extra = 0
    per_page = 1
    pagination_key = "session-item"
    fields = ('item_code', 'title', 'print_dispatch_btn', 'elected_person_role', 
              'elected_person_text_reference', 'elected_role_text_reference')
    readonly_fields = ('item_code', 'title', 'print_dispatch_btn')
    autocomplete_fields = ('elected_person_role',)
    can_delete = False
    show_change_link = True
    verbose_name = _("HR Links (Personnel Elections)")
    verbose_name_plural = _("HR Links (Personnel Elections)")
    
    def get_queryset(self, request):
        """Only show ELEC type items"""
        qs = super().get_queryset(request)
        return qs.filter(kind=SessionItem.Kind.ELECTION)
    
    def has_add_permission(self, request, obj=None):
        """Don't allow adding items through this inline"""
        return False
    
    def get_readonly_fields(self, request, obj=None):
        """
        Keep FK fields editable for managers even after submission.
        For non-managers, lock everything when session is locked.
        """
        ro = list(super().get_readonly_fields(request, obj))
        
        # If session exists and is locked
        if obj:
            st = state_snapshot(obj)
            # Non-managers get everything locked
            if not is_assembly_manager(request.user) and st.get("locked"):
                ro += ['elected_person_role', 'elected_person_text_reference', 
                       'elected_role_text_reference']
        
        return ro
    
    def has_delete_permission(self, request, obj=None):
        """Don't allow deleting HR links via inline"""
        return False  # HR links managed via standalone admin

    @admin.display(description="📜")
    def print_dispatch_btn(self, obj):
        """Render inline print button for dispatch document"""
        if not obj or not obj.pk:
            return ""
        
        # Check if dispatch can be generated
        can_print = (
            obj.elected_person_role and 
            not obj.elected_person_text_reference and 
            not obj.elected_role_text_reference
        )
        
        if not can_print:
            return format_html(
                '<span style="color: #999; font-size: 0.9em;" title="{}">{}</span>',
                _("Link PersonRole first"),
                "—"
            )
        
        # Generate URL to print endpoint
        url = reverse('admin:assembly_sessionitem_print_dispatch', args=[obj.pk])
        
        return format_html(
            '<a href="{}" class="button" style="padding: 3px 8px; font-size: 0.85em;" '
            'target="_blank" title="{}">{}</a>',
            url,
            _("Print dispatch document"),
            "📜 PDF"
        )


class SessionAttendanceInline(StackedInlinePaginated):
    model = SessionAttendance
    extra = 0
    per_page = 9
    pagination_key = "session-attendance"
    fields = ('mandate', 'backup_attended')
    autocomplete_fields = ('mandate',)
    verbose_name = _("Attendee")
    verbose_name_plural = _("Attendees (with backup tracking)")
    
    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj:
            session_admin = self.admin_site._registry.get(Session)
            if session_admin and session_admin._is_locked(request, obj):
                # For SessionAttendance: lock both fields
                ro.extend(['mandate', 'backup_attended'])
        return ro

# ============================================================================
# TERM ADMIN
# ============================================================================

@log_deletions
@with_help_widget
@admin.register(Term)
class TermAdmin(
    SimpleHistoryAdmin,
    DjangoObjectActions,
    ImportExportModelAdmin,
    ConcurrentModelAdmin,
    ImportExportGuardMixin,
    HistoryGuardMixin
    ):
    resource_classes = [TermResource]
    
    list_display = ('display_code', 'label', 'start_date', 'end_date', 'is_active', 
                    'updated_at', 'active_text')
    list_display_links = ('display_code',)
    list_filter = ('is_active', 'start_date')
    search_fields = ('code', 'label')
    readonly_fields = ('code', 'created_at', 'updated_at', 'signatures_box')
    inlines = [AnnotationInline]
    
    fieldsets = (
        (_("Scope"), {
            'fields': ('code', 'label', 'start_date', 'end_date', 'is_active')
        }),
        (_("Workflow & HankoSign"), {
            'fields': ('signatures_box',)
        }),
        (_("System"), {
            'fields': ('version', 'created_at', 'updated_at')
        }),
    )
    
    change_actions = ('lock_term', 'unlock_term', 'print_term')
    
    def _is_manager(self, request):
        return is_assembly_manager(request.user)
    
    @admin.display(description=_("Locked"))
    def active_text(self, obj):
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
            if st.get("explicit_locked"):
                ro += ['label', 'start_date', 'end_date', 'is_active',]
        return ro
    
    def get_change_actions(self, request, object_id, form_url):
        actions = super().get_change_actions(request, object_id, form_url)
        
        if not self._is_manager(request):
            return [a for a in actions if a == 'print_term']
        
        obj = self.get_object(request, object_id)
        if obj:
            st = state_snapshot(obj)
            is_locked = st.get("explicit_locked", False)
            if is_locked:
                return [a for a in actions if a in ('unlock_term', 'print_term')]
            else:
                return [a for a in actions if a in ('lock_term', 'print_term')]
        
        return actions
    
    @transaction.atomic
    @safe_admin_action
    def lock_term(self, request, obj):
        if not self._is_manager(request):
            messages.warning(request, _("You don't have permission to lock terms."))
            return
        st = state_snapshot(obj)
        if st.get("explicit_locked"):
            messages.info(request, _("Already locked."))
            return
        action = get_action("LOCK:-@assembly.term")
        if not action:
            messages.error(request, _("Lock action not configured."))
            return
        record_signature(request, action, obj, note=_("Term %(code)s locked") % {"code": obj.code})
        create_system_annotation(obj, "LOCK", user=request.user)
        messages.success(request, _("Term locked."))
    lock_term.label = _("Lock term")
    lock_term.attrs = {"class": "btn btn-block btn-warning", "style": "margin-bottom: 1rem;"}
    
    @transaction.atomic
    @safe_admin_action
    def unlock_term(self, request, obj):
        if not self._is_manager(request):
            messages.warning(request, _("You don't have permission to unlock terms."))
            return
        st = state_snapshot(obj)
        if not st.get("explicit_locked"):
            messages.info(request, _("Already unlocked."))
            return
        action = get_action("UNLOCK:-@assembly.term")
        if not action:
            messages.error(request, _("Unlock action not configured."))
            return
        record_signature(request, action, obj, note=_("Term %(code)s unlocked") % {"code": obj.code})
        create_system_annotation(obj, "UNLOCK", user=request.user)
        messages.success(request, _("Term unlocked."))
    unlock_term.label = _("Unlock term")
    unlock_term.attrs = {"class": "btn btn-block btn-success", "style": "margin-bottom: 1rem;"}
    
    @safe_admin_action
    def print_term(self, request, obj):
        action = get_action("RELEASE:-@assembly.term")
        if not action:
            messages.error(request, _("Release action not configured."))
            return
        sign_once(request, action, obj, note=_("Printed term overview"), window_seconds=10)
        signatures = seal_signatures_context(obj)
        ctx = {"term": obj, "org": OrgInfo.get_solo(), "signatures": signatures}
        return render_pdf_response(
            "assembly/term_pdf.html", ctx, request,
            f"HV-TERM_{obj.code}.pdf"
        )
    print_term.label = "🖨️ " + _("Print Term PDF")
    print_term.attrs = {
        "class": "btn btn-block btn-info",
        "style": "margin-bottom: 1rem;",
        "data-action": "post-object",
        "onclick": RID_JS
    }
    
    def has_delete_permission(self, request, obj=None):
        return False


# ============================================================================
# COMPOSITION ADMIN
# ============================================================================

@log_deletions
@with_help_widget
@admin.register(Composition)
class CompositionAdmin(
    SimpleHistoryAdmin,
    DjangoObjectActions,
    ImportExportModelAdmin,
    ConcurrentModelAdmin,
    ImportExportGuardMixin,
    HistoryGuardMixin
    ):
    list_display = ('term', 'active_mandates_display', 'updated_at')
    list_display_links = ('term',)
    autocomplete_fields = ('term',)
    readonly_fields = ('created_at', 'updated_at', 'signatures_box')
    inlines = [MandateInline]
    
    fieldsets = (
        (_("Scope"), {
            'fields': ('term',)
        }),
        (_("Workflow & HankoSign"), {
            'fields': ('signatures_box',)
        }),
        (_("System"), {
            'fields': ('version', 'created_at', 'updated_at')
        }),
    )
    
    change_actions = ('print_composition',)
    
    @admin.display(description=_("Active Mandates"))
    def active_mandates_display(self, obj):
        count = obj.active_mandates_count()
        return f"{count}/9"
    
    @admin.display(description=_("Signatures"))
    def signatures_box(self, obj):
        return render_signatures_box(obj)
    
    @safe_admin_action
    def print_composition(self, request, obj):
        action = get_action("RELEASE:-@assembly.composition")
        if not action:
            messages.error(request, _("Release action not configured."))
            return
        sign_once(request, action, obj, note=_("Printed board roster"), window_seconds=10)
        signatures = seal_signatures_context(obj)
        mandates = obj.mandates.filter(end_date__isnull=True).select_related('person_role__person', 'person_role__role')
        ctx = {"comp": obj, "mandates": mandates, "org": OrgInfo.get_solo(), "signatures": signatures}
        return render_pdf_response(
            "assembly/composition_pdf.html", ctx, request,
            f"HV-BOARD_{obj.term.code}.pdf"
        )
    print_composition.label = "🖨️ " + _("Print Board Roster PDF")
    print_composition.attrs = {
        "class": "btn btn-block btn-info",
        "style": "margin-bottom: 1rem;",
        "data-action": "post-object",
        "onclick": RID_JS
    }
    
    def has_delete_permission(self, request, obj=None):
        return False


# ============================================================================
# SESSION ADMIN
# ============================================================================

@log_deletions
@with_help_widget
@admin.register(Session)
class SessionAdmin(
    SimpleHistoryAdmin,
    DjangoObjectActions,
    SortableAdminBase,
    ImportExportModelAdmin,
    ConcurrentModelAdmin,
    ImportExportGuardMixin,
    HistoryGuardMixin
    ):
    resource_classes = [SessionResource]
    list_display = ('status_text', 'code', 'session_date', 'session_type',
                    'location', 'updated_at')
    list_display_links = ('code',)
    list_filter = ('status', 'session_type', 'term', 'session_date')
    search_fields = ('code', 'location', 'protocol_number')
    autocomplete_fields = ('term', 'attendees', 'absent')
    readonly_fields = ('code', 'status', 'created_at', 'updated_at', 'signatures_box')
    inlines = [SessionAttendanceInline, ElectionItemHRLinksInline, AnnotationInline]
    
    fieldsets = (
        (_("Scope"), {
            'fields': ('term', 'code', 'session_type')
        }),
        (_("Schedule & Location"), {
            'fields': ('session_date', 'session_time', 'location', 'protocol_number')
        }),
        (_("Attendance"), {
            'fields': ('absent', 'other_attendees')
        }),
        (_("Workflow & HankoSign"), {
            'fields': ('status', 'invitations_sent_at', 'minutes_finalized_at', 
                    'sent_koko_hsg_at', 'signatures_box')
        }),
        (_("System"), {
            'fields': ('version', 'created_at', 'updated_at')
        }),
    )
    
    change_actions = ('submit_session', 'withdraw_session', 'approve_session',
                     'reject_session', 'verify_session', 'print_session', 'open_protocol_editor')
    
    def _is_manager(self, request):
        return is_assembly_manager(request.user)
    
    def _is_locked(self, request, obj):
        if not obj:
            return False
        if self._is_manager(request):
            return False
        # Status is already derived from HankoSign, so use it
        # Locked if submitted or beyond
        return obj.status in (
            Session.Status.SUBMITTED,
            Session.Status.APPROVED,
            Session.Status.VERIFIED,
            Session.Status.REJECTED
        )
    
    @admin.display(description=_("Status"))
    def status_text(self, obj):
        return object_status_span(obj, final_stage="CHAIR")
    
    @admin.display(description=_("Signatures"))
    def signatures_box(self, obj):
        return render_signatures_box(obj)
    
    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj:
            ro.extend(['term', 'session_type'])
            if self._is_locked(request, obj):
                ro += ['session_date', 'session_time', 
                    'location', 'protocol_number', 'attendees', 'absent', 
                    'other_attendees']
        return ro
    
    def get_change_actions(self, request, object_id, form_url):
        actions = list(super().get_change_actions(request, object_id, form_url))
        obj = self.get_object(request, object_id)
        
        if not obj:
            return actions
        
        def drop(*names):
            for n in names:
                if n in actions:
                    actions.remove(n)
        
        # Use status field instead of state_snapshot
        status = obj.status
        
        # VERIFIED or REJECTED: Can't submit/withdraw/approve/reject anymore
        if status in (Session.Status.VERIFIED, Session.Status.REJECTED):
            drop("submit_session", "withdraw_session", "approve_session", "reject_session")
            return actions
        
        # APPROVED: Can verify, can't submit/approve
        if status == Session.Status.APPROVED:
            drop("submit_session", "approve_session", "reject_session")
            return actions
        
        # SUBMITTED: Can approve/reject/withdraw, can't submit
        if status == Session.Status.SUBMITTED:
            drop("submit_session")
            return actions
        
        # DRAFT: Can only submit
        if status == Session.Status.DRAFT:
            drop("withdraw_session", "approve_session", "reject_session", "verify_session")
            return actions
        
        return actions

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        qs = qs.select_related('term')
        qs = qs.prefetch_related('attendees', 'absent', 'items')
        return qs

    @transaction.atomic
    @safe_admin_action
    def submit_session(self, request, obj):
        st = state_snapshot(obj)
        if st["submitted"]:
            messages.info(request, _("Already submitted."))
            return
        action = get_action("SUBMIT:ASS@assembly.session")
        if not action:
            messages.error(request, _("Submit action not configured."))
            return
        record_signature(request, action, obj, note=_("Session %(code)s submitted") % {"code": obj.code})
        create_system_annotation(obj, "SUBMIT", user=request.user)
        messages.success(request, _("Submitted."))
    submit_session.label = _("Submit")
    submit_session.attrs = {"class": "btn btn-block btn-warning", "style": "margin-bottom: 1rem;"}
    
    @transaction.atomic
    @safe_admin_action
    def withdraw_session(self, request, obj):
        st = state_snapshot(obj)
        if not st["submitted"]:
            messages.info(request, _("Not submitted."))
            return
        if st["approved"]:
            messages.warning(request, _("Cannot withdraw after approval."))
            return
        action = get_action("WITHDRAW:ASS@assembly.session")
        if not action:
            messages.error(request, _("Withdraw action not configured."))
            return
        record_signature(request, action, obj, note=_("Session %(code)s withdrawn") % {"code": obj.code})
        create_system_annotation(obj, "WITHDRAW", user=request.user)
        messages.success(request, _("Withdrawn."))
    withdraw_session.label = _("Withdraw")
    withdraw_session.attrs = {"class": "btn btn-block btn-secondary", "style": "margin-bottom: 1rem;"}
    
    @transaction.atomic
    @safe_admin_action
    def approve_session(self, request, obj):
        st = state_snapshot(obj)
        if not st["submitted"]:
            messages.warning(request, _("Submit first."))
            return
        if "CHAIR" in st["approved"]:
            messages.info(request, _("Already approved."))
            return
        action = get_action("APPROVE:CHAIR@assembly.session")
        if not action:
            messages.error(request, _("Approval action not configured."))
            return
        record_signature(request, action, obj, note=_("Session %(code)s approved") % {"code": obj.code})
        create_system_annotation(obj, "APPROVE", user=request.user)
        messages.success(request, _("Approved."))
    approve_session.label = _("Approve (Chair)")
    approve_session.attrs = {"class": "btn btn-block btn-success", "style": "margin-bottom: 1rem;"}
    
    @transaction.atomic
    @safe_admin_action
    def reject_session(self, request, obj):
        st = state_snapshot(obj)
        if not st["submitted"]:
            messages.warning(request, _("Nothing to reject."))
            return
        if "CHAIR" in st["approved"]:
            messages.warning(request, _("Already approved; cannot reject."))
            return
        action = get_action("REJECT:CHAIR@assembly.session")
        if not action:
            messages.error(request, _("Reject action not configured."))
            return
        record_signature(request, action, obj, note=_("Session %(code)s rejected") % {"code": obj.code})
        create_system_annotation(obj, "REJECT", user=request.user)
        messages.success(request, _("Rejected."))
    reject_session.label = _("Reject")
    reject_session.attrs = {"class": "btn btn-block btn-danger", "style": "margin-bottom: 1rem;"}
    
    @transaction.atomic
    @safe_admin_action
    def verify_session(self, request, obj):
        st = state_snapshot(obj)
        if "CHAIR" not in st["approved"]:
            messages.warning(request, _("Approve first before verification."))
            return
        if st.get("verified"):
            messages.info(request, _("Already verified."))
            return
        action = get_action("VERIFY:-@assembly.session")
        if not action:
            messages.error(request, _("Verify action not configured."))
            return
        
        # Set timestamp
        obj.sent_koko_hsg_at = timezone.now()
        obj.save(update_fields=['sent_koko_hsg_at'])
        record_signature(request, action, obj, note=_("Session %(code)s sent to KoKo/HSG") % {"code": obj.code})
        create_system_annotation(obj, "VERIFY", user=request.user)
        messages.success(request, _("Verified and sent to KoKo/HSG."))
    verify_session.label = _("Verify (Sent to KoKo/HSG)")
    verify_session.attrs = {"class": "btn btn-block btn-primary", "style": "margin-bottom: 1rem;"}
    
    @safe_admin_action
    def print_session(self, request, obj):
        action = get_action("RELEASE:-@assembly.session")
        if not action:
            messages.error(request, _("Release action not configured."))
            return
        sign_once(request, action, obj, note=_("Printed session protocol"), window_seconds=10)
        signatures = seal_signatures_context(obj)
        items = obj.items.all().order_by('order')
        ctx = {"session": obj, "items": items, "org": OrgInfo.get_solo(), "signatures": signatures}
        return render_pdf_response(
            "assembly/protocol/session_pdf.html", ctx, request,
            f"HV-PROTOCOL_{obj.code}.pdf"
        )
    print_session.label = "🖨️ " + _("Print Protocol PDF")
    print_session.attrs = {
        "class": "btn btn-block btn-info",
        "style": "margin-bottom: 1rem;",
        "data-action": "post-object",
        "onclick": RID_JS
    }

    @safe_admin_action
    def open_protocol_editor(self, request, obj):
        """Redirect to PROTOKOL-KUN Mk. 1"""
        url = reverse('assembly:protocol_editor_session', args=[obj.pk])
        from django.shortcuts import redirect
        return redirect(url)
    open_protocol_editor.label = "📝 " + _("Open in P-KUN")
    open_protocol_editor.attrs = {
        "class": "btn btn-block",
        "style": "margin-bottom: 1rem",
    }

    def has_delete_permission(self, request, obj=None):
        return False


# ============================================================================
# SESSION ITEM ADMIN
# ============================================================================

class SessionItemAdminForm(forms.ModelForm):
    class Meta:
        model = SessionItem
        fields = '__all__'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Conditional field requirements based on kind
        kind = self.data.get('kind') or getattr(self.instance, 'kind', None)
        
        if kind == SessionItem.Kind.PROCEDURAL:
            # Only show content field
            if 'subject' in self.fields:
                self.fields['subject'].required = False
                self.fields['subject'].widget = forms.HiddenInput()
            if 'discussion' in self.fields:
                self.fields['discussion'].required = False
                self.fields['discussion'].widget = forms.HiddenInput()
            if 'outcome' in self.fields:
                self.fields['outcome'].required = False
                self.fields['outcome'].widget = forms.HiddenInput()
        else:
            # Hide content field for RES/ELEC
            if 'content' in self.fields:
                self.fields['content'].required = False
                self.fields['content'].widget = forms.HiddenInput()


@log_deletions
@with_help_widget
@admin.register(SessionItem)
class SessionItemAdmin(
    SimpleHistoryAdmin,
    DjangoObjectActions,
    ImportExportModelAdmin,
    ConcurrentModelAdmin,
    ImportExportGuardMixin,
    HistoryGuardMixin
    ):
    resource_classes = [SessionItemResource]
    form = SessionItemAdminForm
    
    list_display = ('full_identifier', 'session', 'kind', 'title', 'passed', 'updated_at')
    list_display_links = ('full_identifier',)
    list_filter = ('kind', 'voting_mode', 'passed', 'session__term')
    search_fields = ('item_code', 'title', 'session__code')
    autocomplete_fields = ('session', 'elected_person_role')
    readonly_fields = ('item_code', 'created_at', 'updated_at', 'signatures_box')
    inlines = [VoteInline, AnnotationInline]
    
    fieldsets = (
        (_("Scope"), {
            'fields': ('session', 'item_code', 'order', 'kind', 'title')
        }),
        (_("Content (Procedural)"), {
            'fields': ('content',),
        }),
        (_("Content (Resolution/Election)"), {
            'fields': ('subject', 'discussion', 'outcome'),
        }),
        (_("Voting"), {
            'fields': ('voting_mode', 'votes_for', 'votes_against', 
                    'votes_abstain', 'passed'),
        }),
        (_("Election"), {
            'fields': ('elected_person_role', 'elected_person_text_reference', 
                    'elected_role_text_reference',),
        }),
        (_("Notes"), {
            'fields': ('notes',),
        }),
        (_("Workflow & HankoSign"), {
            'fields': ('signatures_box',)
        }),
        (_("System"), {
            'fields': ('version', 'created_at', 'updated_at')
        }),
    )
    
    change_actions = ('print_dispatch_document',)
    
    @admin.display(description=_("Signatures"))
    def signatures_box(self, obj):
        return render_signatures_box(obj)
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        qs = qs.select_related('session__term', 'elected_person_role__person', 'elected_person_role__role')
        return qs

    def get_change_actions(self, request, object_id, form_url):
        """Show dispatch print only for ELEC items"""
        actions = super().get_change_actions(request, object_id, form_url)
        
        obj = self.get_object(request, object_id)
        if obj:
            # Only show dispatch print for election items
            if obj.kind != SessionItem.Kind.ELECTION or SessionItem.Kind.RESOLUTION:
                if 'print_dispatch_document' in actions:
                    actions = [a for a in actions if a != 'print_dispatch_document']
        
        return actions
    
    @safe_admin_action
    def print_dispatch_document(self, request, obj):
        """Print dispatch/appointment document for special roles (Kollegiumsmitglied, Kurator)"""
        
        if obj.kind != SessionItem.Kind.ELECTION:
            messages.error(request, _("Only election items can generate dispatch documents."))
            return
        
        if not obj.elected_person_role or obj.elected_person_text_reference or obj.elected_role_text_reference:
            messages.error(request, _("No person elected or temporary placeholders - cannot generate document."))
            return
        
        action = get_action("RELEASE:-@assembly.sessionitem")
        if not action:
            messages.error(request, _("Release action not configured."))
            return
        sign_once(request, action, obj, note=_("Printed dispatch document"), window_seconds=10)
        signatures = seal_signatures_context(obj)
        ctx = {
            "item": obj,
            "session": obj.session,
            "person_role": obj.elected_person_role,
            "org": OrgInfo.get_solo(),
            "signatures": signatures,
            # Prepare signers for qualified signature boxes
            "signers": [
                {'label': _("per pro, the ÖH FH OÖ")},
            ]
        }
        if obj.elected_person_role:
            fname = slugify(obj.elected_person_role.person.last_name)[:40]
        else:
            fname = 'TEMPREF'
        return render_pdf_response(
            "assembly/certs/dispatchreceipt_pdf.html", ctx, request,
            f"DISPATCH_{fname}_{obj.item_code}.pdf"
        )
    print_dispatch_document.label = "📜 " + _("Print Dispatch Document")
    print_dispatch_document.attrs = {
        "class": "btn btn-block btn-success",
        "style": "margin-bottom: 1rem;",
        "data-action": "post-object",
        "onclick": RID_JS
    }
    
    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        
        # Lock if parent session is locked
        if obj and obj.session_id:
            session_admin = self.admin_site._registry.get(Session)
            if session_admin and session_admin._is_locked(request, obj.session):
                ro += ['session', 'order', 'kind', 'title', 'content', 
                       'subject', 'discussion', 'outcome', 'voting_mode',
                       'votes_for', 'votes_against', 'votes_abstain', 
                       'passed', 'elected_person_role', 'notes']
        
        return ro
    
    def has_delete_permission(self, request, obj=None):
        """
        Allow deleting items ONLY if parent session is not finalized.
        Once a session is approved (CHAIR), items are locked.
        """
        # If no specific object, check general permission
        if not obj:
            return super().has_delete_permission(request, obj)
        
        # Check if parent session exists
        if not obj.session_id:
            return super().has_delete_permission(request, obj)
        
        # Get parent session's state
        session_admin = self.admin_site._registry.get(Session)
        if not session_admin:
            return False
        
        # Check if session is locked (approved by chair)
        st = state_snapshot(obj.session)
        
        # If CHAIR approved or session is locked, prevent deletion
        if "CHAIR" in st.get("approved", set()) or st.get("locked"):
            return False
        
        # Otherwise, allow deletion (session is still in draft/submitted state)
        return super().has_delete_permission(request, obj)
    
    def get_model_perms(self, request):
        """
        Hide from sidebar for non-superusers.
        Annotations should be managed via inlines.
        """
        if not request.user.is_superuser:
            return {}
        return super().get_model_perms(request)