from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _
from django.utils.safestring import mark_safe
from django.template.loader import render_to_string
from django.db import transaction
from django import forms

from django_object_actions import DjangoObjectActions
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from simple_history.admin import SimpleHistoryAdmin
from concurrency.admin import ConcurrentModelAdmin

from core.admin_mixins import ImportExportGuardMixin, HelpPageMixin, safe_admin_action
from core.pdf import render_pdf_response
from core.utils.authz import is_assembly_manager  # You'll need to create this
from core.utils.bool_admin_status import boolean_status_span, row_state_attr_for_boolean
from hankosign.utils import (
    render_signatures_box, state_snapshot, get_action, 
    record_signature, RID_JS, sign_once, seal_signatures_context,
    object_status_span
)
from organisation.models import OrgInfo

from .models import Term, Composition, Mandate, Session, SessionItem, Vote


# ============================================================================
# RESOURCES (Import/Export)
# ============================================================================

class TermResource(resources.ModelResource):
    class Meta:
        model = Term
        fields = ('id', 'code', 'label', 'start_date', 'end_date', 'is_active', 'notes')
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

@admin.register(Mandate)
class MandateAdmin(ConcurrentModelAdmin, SimpleHistoryAdmin):
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

class MandateInline(admin.StackedInline):
    model = Mandate
    extra = 1
    max_num = 9
    fields = ('position', 'person_role', 'officer_role', 'start_date', 'end_date', 
              'backup_person_role', 'backup_person_text')
    autocomplete_fields = ('person_role', 'backup_person_role')
    ordering = ('position',)


class VoteInline(admin.StackedInline):
    model = Vote
    extra = 0
    fields = ('mandate', 'vote')
    autocomplete_fields = ('mandate',)


class SessionItemInline(admin.StackedInline):
    model = SessionItem
    extra = 0
    fields = ('order', 'kind', 'title', 'item_code')
    readonly_fields = ('item_code',)
    show_change_link = True
    can_delete = False
    
    def get_max_num(self, request, obj=None, **kwargs):
        return 50


# ============================================================================
# TERM ADMIN
# ============================================================================

@admin.register(Term)
class TermAdmin(ConcurrentModelAdmin, HelpPageMixin, ImportExportGuardMixin, 
                DjangoObjectActions, ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [TermResource]
    
    list_display = ('display_code', 'label', 'start_date', 'end_date', 'is_active', 
                    'updated_at', 'active_text')
    list_display_links = ('display_code',)
    list_filter = ('is_active', 'start_date')
    search_fields = ('code', 'label')
    readonly_fields = ('code', 'created_at', 'updated_at', 'signatures_box')
    
    fieldsets = (
        (_("Basics"), {
            'fields': ('code', 'label', 'start_date', 'end_date', 'is_active')
        }),
        (_("Notes"), {
            'fields': ('notes',)
        }),
        (_("HankoSign Workflow"), {
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
                ro += ['label', 'start_date', 'end_date', 'is_active', 'notes']
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
        record_signature(request.user, action, obj, note=_("Term %(code)s locked") % {"code": obj.code})
        messages.success(request, _("Term locked."))
    lock_term.label = _("Lock term")
    lock_term.attrs = {"class": "btn btn-block btn-warning btn-sm", "style": "margin-bottom: 1rem;"}
    
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
        record_signature(request.user, action, obj, note=_("Term %(code)s unlocked") % {"code": obj.code})
        messages.success(request, _("Term unlocked."))
    unlock_term.label = _("Unlock term")
    unlock_term.attrs = {"class": "btn btn-block btn-success btn-sm", "style": "margin-bottom: 1rem;"}
    
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
        "class": "btn btn-block btn-info btn-sm",
        "style": "margin-bottom: 1rem;",
        "data-action": "post-object",
        "onclick": RID_JS
    }
    
    def has_delete_permission(self, request, obj=None):
        return False


# ============================================================================
# COMPOSITION ADMIN
# ============================================================================

@admin.register(Composition)
class CompositionAdmin(ConcurrentModelAdmin, HelpPageMixin, DjangoObjectActions, 
                       ImportExportGuardMixin, SimpleHistoryAdmin):
    list_display = ('term', 'active_mandates_display', 'updated_at')
    list_display_links = ('term',)
    autocomplete_fields = ('term',)
    readonly_fields = ('created_at', 'updated_at', 'signatures_box')
    inlines = [MandateInline]
    
    fieldsets = (
        (_("Term"), {
            'fields': ('term',)
        }),
        (_("Notes"), {
            'fields': ('notes',)
        }),
        (_("HankoSign"), {
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
        "class": "btn btn-block btn-info btn-sm",
        "style": "margin-bottom: 1rem;",
        "data-action": "post-object",
        "onclick": RID_JS
    }
    
    def has_delete_permission(self, request, obj=None):
        return False


# ============================================================================
# SESSION ADMIN
# ============================================================================

@admin.register(Session)
class SessionAdmin(ConcurrentModelAdmin, HelpPageMixin, ImportExportGuardMixin,
                   DjangoObjectActions, ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [SessionResource]
    
    list_display = ('status_text', 'code', 'session_date', 'session_type', 
                    'location', 'updated_at')
    list_display_links = ('code',)
    list_filter = ('session_type', 'term', 'session_date')
    search_fields = ('code', 'location', 'protocol_number')
    autocomplete_fields = ('term', 'attendees', 'absent')
    readonly_fields = ('code', 'created_at', 'updated_at', 'signatures_box')
    inlines = [SessionItemInline]
    
    filter_horizontal = ('attendees', 'absent')
    
    fieldsets = (
        (_("Session Details"), {
            'fields': ('term', 'code', 'session_type', 'session_date', 
                      'session_time', 'location', 'protocol_number')
        }),
        (_("Attendance"), {
            'fields': ('attendees', 'absent', 'other_attendees')
        }),
        (_("Workflow"), {
            'fields': ('invitations_sent_at', 'minutes_finalized_at', 'sent_koko_hsg_at')
        }),
        (_("Notes"), {
            'fields': ('notes',)
        }),
        (_("HankoSign Workflow"), {
            'fields': ('signatures_box',)
        }),
        (_("System"), {
            'fields': ('version', 'created_at', 'updated_at')
        }),
    )
    
    change_actions = ('submit_session', 'withdraw_session', 'approve_session',
                     'reject_session', 'verify_session', 'print_session')
    
    def _is_manager(self, request):
        return is_assembly_manager(request.user)
    
    def _is_locked(self, request, obj):
        if not obj:
            return False
        st = state_snapshot(obj)
        if self._is_manager(request):
            return False
        return bool(st.get("locked"))
    
    @admin.display(description=_("Status"))
    def status_text(self, obj):
        return object_status_span(obj, final_stage="CHAIR")
    
    @admin.display(description=_("Signatures"))
    def signatures_box(self, obj):
        return render_signatures_box(obj)
    
    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj and self._is_locked(request, obj):
            ro += ['term', 'session_type', 'session_date', 'session_time', 
                   'location', 'protocol_number', 'attendees', 'absent', 
                   'other_attendees', 'notes']
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
        
        st = state_snapshot(obj)
        approved = st.get("approved", set())
        submitted = st.get("submitted", False)
        verified = st.get("verified", False)
        chair_ok = "CHAIR" in approved or st.get("final")
        
        if chair_ok:
            drop("submit_session", "withdraw_session", "approve_session", "reject_session")
            if not verified:
                # Can still verify after approval
                pass
            return actions
        
        if submitted:
            drop("submit_session")
            if approved:
                drop("withdraw_session")
        else:
            drop("withdraw_session", "approve_session", "reject_session", "verify_session")
        
        return actions
    
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
        record_signature(request.user, action, obj, note=_("Session %(code)s submitted") % {"code": obj.code})
        messages.success(request, _("Submitted."))
    submit_session.label = _("Submit")
    submit_session.attrs = {"class": "btn btn-block btn-warning btn-sm", "style": "margin-bottom: 1rem;"}
    
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
        record_signature(request.user, action, obj, note=_("Session %(code)s withdrawn") % {"code": obj.code})
        messages.success(request, _("Withdrawn."))
    withdraw_session.label = _("Withdraw")
    withdraw_session.attrs = {"class": "btn btn-block btn-secondary btn-sm", "style": "margin-bottom: 1rem;"}
    
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
        record_signature(request.user, action, obj, note=_("Session %(code)s approved") % {"code": obj.code})
        messages.success(request, _("Approved."))
    approve_session.label = _("Approve (Chair)")
    approve_session.attrs = {"class": "btn btn-block btn-success btn-sm", "style": "margin-bottom: 1rem;"}
    
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
        record_signature(request.user, action, obj, note=_("Session %(code)s rejected") % {"code": obj.code})
        messages.success(request, _("Rejected."))
    reject_session.label = _("Reject")
    reject_session.attrs = {"class": "btn btn-block btn-danger btn-sm", "style": "margin-bottom: 1rem;"}
    
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
        
        record_signature(request.user, action, obj, note=_("Session %(code)s sent to KoKo/HSG") % {"code": obj.code})
        messages.success(request, _("Verified and sent to KoKo/HSG."))
    verify_session.label = _("Verify (Sent to KoKo/HSG)")
    verify_session.attrs = {"class": "btn btn-block btn-primary btn-sm", "style": "margin-bottom: 1rem;"}
    
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
            "assembly/certs/session_pdf.html", ctx, request,
            f"HV-PROTOCOL_{obj.code}.pdf"
        )
    print_session.label = "🖨️ " + _("Print Protocol PDF")
    print_session.attrs = {
        "class": "btn btn-block btn-info btn-sm",
        "style": "margin-bottom: 1rem;",
        "data-action": "post-object",
        "onclick": RID_JS
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


@admin.register(SessionItem)
class SessionItemAdmin(ConcurrentModelAdmin, HelpPageMixin, ImportExportGuardMixin,
                       DjangoObjectActions, ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [SessionItemResource]
    form = SessionItemAdminForm
    
    list_display = ('full_identifier', 'session', 'kind', 'title', 'passed', 'updated_at')
    list_display_links = ('full_identifier',)
    list_filter = ('kind', 'voting_mode', 'passed', 'session__term')
    search_fields = ('item_code', 'title', 'session__code')
    autocomplete_fields = ('session', 'elected_person_role')
    readonly_fields = ('item_code', 'created_at', 'updated_at', 'signatures_box')
    inlines = [VoteInline]
    
    fieldsets = (
        (_("Item Details"), {
            'fields': ('session', 'item_code', 'order', 'kind', 'title')
        }),
        (_("Content (Procedural)"), {
            'fields': ('content',),
            'classes': ('collapse',)
        }),
        (_("Content (Resolution/Election)"), {
            'fields': ('subject', 'discussion', 'outcome'),
            'classes': ('collapse',)
        }),
        (_("Voting"), {
            'fields': ('voting_mode', 'votes_for', 'votes_against', 
                      'votes_abstain', 'passed'),
            'classes': ('collapse',)
        }),
        (_("Election"), {
            'fields': ('elected_person_role',),
            'classes': ('collapse',)
        }),
        (_("Notes"), {
            'fields': ('notes',)
        }),
        (_("HankoSign"), {
            'fields': ('signatures_box',)
        }),
        (_("System"), {
            'fields': ('version', 'created_at', 'updated_at')
        }),
    )
    
    change_actions = ('print_item',)
    
    @admin.display(description=_("Signatures"))
    def signatures_box(self, obj):
        return render_signatures_box(obj)
    
    @safe_admin_action
    def print_item(self, request, obj):
        action = get_action("RELEASE:-@assembly.sessionitem")
        if not action:
            messages.error(request, _("Release action not configured."))
            return
        sign_once(request, action, obj, note=_("Printed session item"), window_seconds=10)
        signatures = seal_signatures_context(obj)
        ctx = {"item": obj, "org": OrgInfo.get_solo(), "signatures": signatures}
        return render_pdf_response(
            "assembly/sessionitem_pdf.html", ctx, request,
            f"HV-ITEM_{obj.full_identifier}.pdf"
        )
    print_item.label = "🖨️ " + _("Print Item PDF")
    print_item.attrs = {
        "class": "btn btn-block btn-info btn-sm",
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
        # Hide from sidebar
        return {}