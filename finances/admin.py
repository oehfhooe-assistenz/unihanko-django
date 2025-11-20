#finances/admin.py
from django.contrib import admin, messages
from django import forms
from django.utils.translation import gettext_lazy as _, pgettext
from django.utils.text import slugify
from django.utils import timezone
from django.utils.html import format_html
from django_object_actions import DjangoObjectActions
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from simple_history.admin import SimpleHistoryAdmin
from django.db import transaction, IntegrityError
from django.utils.safestring import mark_safe
from organisation.models import OrgInfo
from .models import FiscalYear, PaymentPlan, default_start, auto_end_from_start, stored_code_from_dates
from core.pdf import render_pdf_response
from core.admin_mixins import ImportExportGuardMixin, HelpPageMixin, safe_admin_action, ManagerOnlyHistoryMixin
from core.utils.authz import is_finances_manager
from hankosign.utils import render_signatures_box, state_snapshot, get_action, record_signature, has_sig, sign_once, RID_JS, object_status_span, seal_signatures_context
from finances.models import paymentplan_status
from django.core.exceptions import PermissionDenied
from core.utils.bool_admin_status import boolean_status_span, row_state_attr_for_boolean
from concurrency.admin import ConcurrentModelAdmin
from annotations.admin import AnnotationInline
from annotations.views import create_system_annotation

# =============== Import–Export ===============
class FiscalYearResource(resources.ModelResource):
    class Meta:
        model = FiscalYear
        fields = (
            "id", "code", "label", "start", "end",
            "is_active", "created_at", "updated_at"
        )
        export_order = fields


class PaymentPlanResource(resources.ModelResource):
    class Meta:
        model = PaymentPlan
        fields = (
            "id",
            "plan_code",
            "person_role",
            "fiscal_year",
            "cost_center",
            "payee_name",
            "address",
            "iban", "bic", "reference",
            "pay_start", "pay_end",
            "monthly_amount", "total_override",
            "status", "status_note",
            "signed_person_at", "signed_wiref_at", "signed_chair_at",
            "created_at", "updated_at",
        )
        export_order = fields


# =============== Admin forms ===============
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


class PaymentPlanForm(forms.ModelForm):
    class Meta:
        model = PaymentPlan
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        F = self.fields
        obj = self.instance

        # Help texts (keep your original window/richtwert notes)
        if obj.pk:
            if "monthly_amount" in F:
                F["monthly_amount"].help_text = _(
                    "Auto-filled from role default. Adjust if needed for this specific plan."
                )
            
            if "pay_start" in F:
                F["pay_start"].help_text = _(
                    "Auto-calculated from assignment dates ∩ fiscal year. Adjust if needed."
                )
            
            if "pay_end" in F:
                F["pay_end"].help_text = _(
                    "Auto-calculated from assignment dates ∩ fiscal year. Adjust if needed."
                )

        # (2) No silent autofill of name/amount. Only default the reference on *add*.
        if not obj.pk and "reference" in F and not self.initial.get("reference"):
            self.initial["reference"] = "Funktionsgebühr"


        if obj.pk:
            # (3) Suggestion chips (visible/nudgy, but won’t change data unless clicked)
            suggested_name = ""
            try:
                if getattr(obj, "person_role_id", None):
                    p = obj.person_role.person
                    suggested_name = f"{(p.first_name or '').strip()} {(p.last_name or '').strip()}".strip()
            except Exception:
                pass

            def _chip(label: str, field_id: str, value: str) -> str:
                if not value:
                    return ""
                # inline JS to set the input value
                return (
                    f'<a class="uh-chip" '
                    f'style="margin-left:.5rem; padding:2px 8px; border-radius:999px; background:#eef2ff; '
                    f'border:1px solid #c7d2fe; cursor:pointer; font-weight:600;" '
                    f'onclick="(function(){{var el=document.getElementById(\'{field_id}\'); if(el){{el.value={value!r}; el.dispatchEvent(new Event(\'change\'));}}}})()">'
                    f'{label}</a>'
                )

            if "payee_name" in F:
                F["payee_name"].help_text = mark_safe(
                    _("<strong>Tip:</strong> Use the assignment holder’s name")
                    + _chip(_("Use name"), "id_payee_name", suggested_name)
                )

            if "reference" in F:
                F["reference"].help_text = mark_safe(
                    _("<strong>Tip:</strong> Default reference")
                    + _chip(_("Use “Funktionsgebühr”"), "id_reference", "Funktionsgebühr")
                )

    # Normalize banking inputs
    def clean_iban(self):
        iban = (self.cleaned_data.get("iban") or "").replace(" ", "").upper()
        return iban

    def clean_bic(self):
        bic = (self.cleaned_data.get("bic") or "").replace(" ", "").upper()
        return bic

    def clean_reference(self):
        # keep explicit; do NOT append name automatically
        ref = (self.cleaned_data.get("reference") or "").strip()
        return ref or "Funktionsgebühr"

    # (5) Stricter validation when leaving DRAFT (form-level)
    def clean(self):
        cleaned = super().clean()
        status = cleaned.get("status")
        if status and status != PaymentPlan.Status.DRAFT:
            required_fields = ["payee_name", "address", "reference", "cost_center", "iban", "bic"]
            for f in required_fields:
                v = cleaned.get(f)
                if not (str(v).strip() if v is not None else ""):
                    self.add_error(f, _("Required when leaving Draft."))
            if cleaned.get("monthly_amount") is None:
                self.add_error("monthly_amount", _("Required when leaving Draft."))
        return cleaned


# =============== Filters ===============
class FYChipsFilter(admin.SimpleListFilter):
    title = _("Year")
    parameter_name = "fy"
    template = "admin/filters/fy_chips.html"

    def lookups(self, request, model_admin):
        fys = FiscalYear.objects.order_by("-start")[:4]
        return [(fy.pk, fy.display_code()) for fy in fys]

    def queryset(self, request, qs):
        val = self.value()
        if val:
            return qs.filter(fiscal_year_id=val)
        return qs


# =============== PaymentPlan Admin ===============
@admin.register(PaymentPlan)
class PaymentPlanAdmin(
    SimpleHistoryAdmin,
    DjangoObjectActions,
    ImportExportModelAdmin,
    ConcurrentModelAdmin,
    HelpPageMixin,
    ImportExportGuardMixin,
    ManagerOnlyHistoryMixin
    ):
    resource_classes = [PaymentPlanResource]
    form = PaymentPlanForm
    actions = ("export_selected_pdf",)
    inlines = [AnnotationInline]

    # --- helpers ------------------------------------------------------------
    def _is_manager(self, request) -> bool:
        return is_finances_manager(request.user)

    # --- list / filters / search -------------------------------------------
    list_display = (
        "status_text",
        "plan_code",
        "person_role",
        "fiscal_year",
        "cost_center",
        "monthly_amount",
        "effective_total_display",
        "updated_at",
        "active_text",
    )
    list_filter = (FYChipsFilter, "status", "pay_start", "pay_end", "cost_center",)
    search_fields = (
        "plan_code",
        "person_role__person__last_name",
        "person_role__person__first_name",
        "person_role__role__name",
        "payee_name",
        "reference",
        "cost_center",
        "address",
    )
    list_display_links = ("plan_code",)
    autocomplete_fields = ("person_role", "fiscal_year")

    readonly_fields = (
        "plan_code_or_hint",
        "created_at", "updated_at",
        "window_preview", "breakdown_preview", "recommended_total_display", "role_monthly_hint",
        "bank_reference_preview_full", "pdf_file", "submission_ip", "signatures_box", "status", "version"
    )

    list_per_page = 50
    ordering = ("-created_at",)

    fieldsets = (
        (_("Scope"), {
            "fields": ("plan_code_or_hint", "person_role", "fiscal_year", "status"),
        }),
        (_("Budget"), {
            "fields": (
                "cost_center",
                "monthly_amount", "role_monthly_hint",
                "total_override", "recommended_total_display",
                "breakdown_preview"
            ),
            "description": "ℹ️ " + _("Financial parameters set by WiRef."),
        }),
        (_("Payment Window"), {
            "fields": ("pay_start", "pay_end", "window_preview"),
        }),
        (_("Banking"), {
            "fields": (
                "payee_name", "iban", "bic", "address",
                "reference",
                "bank_reference_preview_full"
            ),
            "description": _("Payee details completed via portal. Reference text set by admin."),
        }),
        (_("Submission"), {
            "fields": ("signed_person_at", "pdf_file", "submission_ip"),
            "description": "ℹ️ " + _("Received from payee via public portal."),
        }),
        (_("Workflow & HankoSign"), {
            "fields": ("signatures_box",),
        }),
        (_("System"), {
            "fields": ("created_at", "updated_at", "version"),
        }),
    )


    # --- computed displays --------------------------------------------------
    @admin.display(description=_("Window"))
    def window_display(self, obj):
        s, e = obj.resolved_window()
        return f"{s:%Y-%m-%d} → {e:%Y-%m-%d}"


    @admin.display(description=_("Total"))
    def effective_total_display(self, obj):
        val = format(obj.effective_total, ".2f")
        return format_html("<strong>{} €</strong>", val)


    @admin.display(description=_("Status"))
    def status_text(self, obj):
        # PaymentPlan uses WIREF/CHAIR approval stages
        return object_status_span(obj, final_stage="CHAIR", tier1_stage="WIREF")


    @admin.display(description=_("Locked"))
    def active_text(self, obj):
        if not obj:
            return "—"
        
        # Check FY lock cascade
        if obj.fiscal_year_id:
            fy_st = state_snapshot(obj.fiscal_year)
            is_locked = fy_st.get("explicit_locked", False)
        else:
            is_locked = False
        
        return boolean_status_span(
            value=not is_locked,  # True = unlocked
            true_label=_("Open"),
            false_label=_("Locked"),
            true_code="ok",
            false_code="off",
        )


    @admin.display(description=_("Signatures"))
    def signatures_box(self, obj):
        return render_signatures_box(obj)


    @admin.display(description=_("Resolved window (clamped to FY)"))
    def window_preview(self, obj):
        from django.template.loader import render_to_string
        
        if not obj.pk:
            return _("— will be shown after saving —")
        
        s, e = obj.resolved_window()
        fy = obj.fiscal_year
        
        ctx = {
            "window_start": s,
            "window_end": e,
            "fy_start": fy.start,
            "fy_end": fy.end,
            "no_overlap": (s > e),
        }
        
        html = render_to_string("admin/finances/window_preview.html", ctx)
        return mark_safe(html)


    @admin.display(description=_("Plan code"))
    def plan_code_or_hint(self, obj):
        muted_style = "color:#e74c3c;"
        if not obj or not getattr(obj, "pk", None):
            msg = pgettext("PaymentPlan admin hint", "will be generated after saving")
            return format_html('<span style="{}">— {} —</span>', muted_style, msg)
        empty = pgettext("PaymentPlan admin hint", "not available")
        return obj.plan_code or format_html('<span style="{}">{}</span>', muted_style, empty)


    @admin.display(description=_("Role’s default monthly amount (per Statutes)"))
    def role_monthly_hint(self, obj):
        if not obj or not obj.person_role_id:
            return "—"
        amt = getattr(obj.person_role.role, "default_monthly_amount", None)
        return f"{amt:.2f} €" if amt is not None else "—"


    @admin.display(description=_("Monthly breakdown (30-day proration)"))
    def breakdown_preview(self, obj):
        from django.template.loader import render_to_string
        
        if not obj or not obj.pk:
            return _("— will be shown after saving —")
        
        rows = obj.months_breakdown()
        ctx = {"rows": rows}
        
        html = render_to_string("admin/finances/breakdown_preview.html", ctx)
        return mark_safe(html)


    @admin.display(description=_("Recommended total ['richtwert']"))
    def recommended_total_display(self, obj):
        if not obj.pk:
            return _("— will be shown after saving —")
        val = format(obj.recommended_total(), ".2f")
        return format_html('<code style="color: yellow;">{} €</code>', val)


    @admin.display(description=_("Bank reference previews"))
    def bank_reference_preview_full(self, obj):
        from django.template.loader import render_to_string
        
        if not obj or not getattr(obj, "pk", None):
            return "—"
        
        ref_full = getattr(obj, "bank_reference_long", "")
        
        # Get short ref
        ref_short = ""
        if hasattr(obj, "bank_reference_short"):
            try:
                ref_short = obj.bank_reference_short(140)
            except TypeError:
                ref_short = getattr(obj, "bank_reference_short", "")
        
        ctx = {
            "ref_full": ref_full,
            "ref_short": ref_short,
        }
        
        html = render_to_string("admin/finances/bank_reference_preview.html", ctx)
        return mark_safe(html)
    

    # --- read-only rules ----------------------------------------------------
    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        
        if not obj:
            return ro
        
        ro.extend(['submission_ip'])
        
        # 1. FY locked → full tombstone (year-end close)
        if obj.fiscal_year_id:
            fy_st = state_snapshot(obj.fiscal_year)
            if fy_st.get("explicit_locked"):
                # Lock everything except system fields
                return ro + [
                    "person_role", "fiscal_year", "cost_center",
                    "payee_name", "iban", "bic", "reference", "address",
                    "pay_start", "pay_end",
                    "monthly_amount", "total_override",
                    "signed_person_at",
                ]
        
        # 2. Workflow-driven readonly
        status = paymentplan_status(obj)
        
        if status == "DRAFT":
            # Scope locked after creation
            if obj.pk:
                ro.extend(["person_role", "fiscal_year"])
        
        elif status == "PENDING":
            ro.extend([
                "person_role", "fiscal_year", "cost_center",
                "payee_name", "iban", "bic", "reference", "address",
                "pay_start", "pay_end",
                "monthly_amount", "total_override",
                "signed_person_at",
            ])
        
        elif status in ("ACTIVE", "FINISHED", "CANCELLED"):
            # Full tombstone
            ro.extend([
                "person_role", "fiscal_year", "cost_center",
                "payee_name", "iban", "bic", "reference", "address",
                "pay_start", "pay_end",
                "monthly_amount", "total_override",
                "signed_person_at",
            ])
        
        return list(dict.fromkeys(ro))  # dedupe


    # --- queryset perf ------------------------------------------------------
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("person_role__person", "person_role__role", "fiscal_year")
    
    def get_changelist_row_attrs(self, request, obj):
        # Check FY lock cascade
        if obj.fiscal_year_id:
            fy_st = state_snapshot(obj.fiscal_year)
            is_locked = fy_st.get("explicit_locked", False)
        else:
            is_locked = False
        
        # If locked, prioritize lock state; otherwise show workflow state
        if is_locked:
            return row_state_attr_for_boolean(
                value=False,  # locked
                true_code="ok",
                false_code="locked",
            )
        else:
            # Show workflow state (final/wiref/submitted/draft will be handled by CSS)
            return {}  # Let CSS handle it via :has() selectors


    # --- object actions (status transitions) --------------------------------
    change_actions = ( "submit_plan", "withdraw_plan", "approve_wiref", "approve_chair", "verify_banking", "cancel_plan", "print_paymentplan", )

    def get_change_actions(self, request, object_id, form_url):
        actions = list(super().get_change_actions(request, object_id, form_url))
        obj = self.get_object(request, object_id)
        
        if not obj:
            return actions
        
        def drop(*names):
            for n in names:
                if n in actions:
                    actions.remove(n)
        
        # FY locked → only print
        if obj.fiscal_year_id:
            fy_st = state_snapshot(obj.fiscal_year)
            if fy_st.get("explicit_locked"):
                drop("submit_plan", "withdraw_plan", "approve_wiref", 
                    "approve_chair", "verify_banking", "cancel_plan")
                return actions
        
        # Workflow-driven visibility
        status = paymentplan_status(obj)
        
        if status == "DRAFT":
            # Show: submit, cancel, print
            drop("withdraw_plan", "approve_wiref", "approve_chair", "verify_banking", "cancel_plan",)
        
        elif status == "PENDING":
            # Show based on approvals
            st = state_snapshot(obj)
            approved = st.get("approved", set())
            
            # Always hide submit
            drop("submit_plan")
            
            # Hide withdraw if any approvals exist
            if approved:
                drop("withdraw_plan")
            
            # Hide approvals once done
            if "WIREF" in approved:
                drop("approve_wiref")
            if "CHAIR" in approved:
                drop("approve_chair")
            
            # Show verify only if both approvals present
            if "WIREF" not in approved or "CHAIR" not in approved:
                drop("verify_banking")
        
        elif status in ("ACTIVE", "FINISHED", "CANCELLED"):
            # Show only print and cancel (if still active)
            drop("submit_plan", "withdraw_plan", "approve_wiref", "approve_chair", "verify_banking")
            
            if status != "ACTIVE":
                drop("cancel_plan")
        
        return actions


    # === HankoSign Workflow Actions ===
    @transaction.atomic
    @safe_admin_action
    def submit_plan(self, request, obj):
        st = state_snapshot(obj)
        if st["submitted"]:
            messages.info(request, _("Already submitted."))
            return
        # Validate that person has completed their part
        if not obj.signed_person_at or not obj.pdf_file:
            messages.warning(request, _("Cannot submit until payee has signed and uploaded the form."))
            return
        action = get_action("SUBMIT:WIREF@finances.paymentplan")
        if not action:
            messages.error(request, _("Submit action not configured."))
            return
        record_signature(request.user, action, obj, note=_("Payment plan %(code)s submitted") % {"code": f"{obj.plan_code}"})
        create_system_annotation(obj, "SUBMIT", user=request.user)
        messages.success(request, _("Submitted."))
    submit_plan.label = _("Submit")
    submit_plan.attrs = {
        "class": "btn btn-block btn-warning",
        "style": "margin-bottom: 1rem;",
    }


    @transaction.atomic
    @safe_admin_action
    def withdraw_plan(self, request, obj): 
        st = state_snapshot(obj)
        if not st["submitted"]:
            messages.info(request, _("Not submitted."))
            return
        # Block if any approvals exist
        if st["approved"]:
            messages.warning(request, _("Cannot withdraw after approvals."))
            return   
        action = get_action("WITHDRAW:WIREF@finances.paymentplan")
        if not action:
            messages.error(request, _("Withdraw action not configured."))
            return
        record_signature(request.user, action, obj, note=_("Payment plan %(code)s withdrawn") % {"code": f"{obj.plan_code}"})
        create_system_annotation(obj, "WITHDRAW", user=request.user)
        messages.success(request, _("Withdrawn."))
    withdraw_plan.label = _("Withdraw")
    withdraw_plan.attrs = {
        "class": "btn btn-block btn-secondary",
        "style": "margin-bottom: 1rem;",
    }


    @transaction.atomic
    @safe_admin_action
    def approve_wiref(self, request, obj):
        st = state_snapshot(obj)
        if not st["submitted"]:
            messages.warning(request, _("Submit first."))
            return
        if "WIREF" in st["approved"]:
            messages.info(request, _("Already approved (WiRef)."))
            return
        action = get_action("APPROVE:WIREF@finances.paymentplan")
        if not action:
            messages.error(request, _("WiRef approval action not configured."))
            return
        record_signature(request.user, action, obj, note=_("Payment plan %(code)s approved (WiRef)") % {"code": f"{obj.plan_code}"})
        create_system_annotation(obj, "APPROVE", user=request.user)
        messages.success(request, _("Approved (WiRef)."))
    approve_wiref.label = _("Approve (WiRef)")
    approve_wiref.attrs = {
        "class": "btn btn-block btn-success",
        "style": "margin-bottom: 1rem;",
    }


    @transaction.atomic
    @safe_admin_action
    def approve_chair(self, request, obj):
        st = state_snapshot(obj)
        if not st["submitted"]:
            messages.warning(request, _("Submit first."))
            return
        if "CHAIR" in st["approved"]:
            messages.info(request, _("Already approved (Chair)."))
            return
        action = get_action("APPROVE:CHAIR@finances.paymentplan")
        if not action:
            messages.error(request, _("Chair approval action not configured."))
            return
        record_signature(request.user, action, obj, note=_("Payment plan %(code)s approved (Chair)") % {"code": f"{obj.plan_code}"})
        create_system_annotation(obj, "APPROVE", user=request.user)
        messages.success(request, _("Approved (Chair)."))
    approve_chair.label = _("Approve (Chair)")
    approve_chair.attrs = {
        "class": "btn btn-block btn-success",
        "style": "margin-bottom: 1rem;",
    }


    @transaction.atomic
    @safe_admin_action
    def verify_banking(self, request, obj):
        st = state_snapshot(obj)
        # Need both approvals first
        if "WIREF" not in st["approved"] or "CHAIR" not in st["approved"]:
            messages.warning(request, _("Both approvals required before verification."))
            return
        if has_sig(obj, "VERIFY", "WIREF"):
            messages.info(request, _("Already verified."))
            return
        action = get_action("VERIFY:WIREF@finances.paymentplan")
        if not action:
            messages.error(request, _("Verify action not configured."))
            return
        record_signature(request.user, action, obj, note=_("Payment plan %(code)s bank-transaction verified (WiRef)") % {"code": f"{obj.plan_code}"})
        create_system_annotation(obj, "VERIFY", user=request.user)
        messages.success(request, _("Banking verified. Plan is now ACTIVE."))
    verify_banking.label = _("Verify banking")
    verify_banking.attrs = {
        "class": "btn btn-block btn-primary",
        "style": "margin-bottom: 1rem;",
    }


    @transaction.atomic
    @safe_admin_action
    def cancel_plan(self, request, obj):       
        action = get_action("REJECT:-@finances.paymentplan")
        if not action:
            messages.error(request, _("Cancel action not configured."))
            return
        record_signature(request.user, action, obj, note=_("Payment plan %(code)s cancelled (WiRef or Chair)") % {"code": f"{obj.plan_code}"})
        create_system_annotation(obj, "REJECT", user=request.user)
        messages.success(request, _("Cancelled."))
    cancel_plan.label = _("Cancel plan")
    cancel_plan.attrs = {
        "class": "btn btn-block btn-danger",
        "style": "margin-bottom: 1rem;",
    }

    @safe_admin_action
    def print_paymentplan(self, request, obj):
        action = get_action("RELEASE:-@finances.paymentplan")
        if not action:
            messages.error(request, _("Release action not configured."))
            return
        sign_once(request, action, obj, note=_("Printed payment plan PDF"), window_seconds=10)
        signatures = seal_signatures_context(obj)
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        lname = slugify(obj.person_role.person.last_name)[:20]
        rsname = slugify(obj.person_role.role.short_name)[:10]
        ctx = {
            "pp": obj,
            "signatures": signatures,
            "org": OrgInfo.get_solo(),
            'signers': [
                {'label': obj.person_role.person.last_name},
                {'label': 'WiRef'},
                {'label': 'Chair'},
            ]
        }
        return render_pdf_response(
            "finances/paymentplan_pdf.html",
            ctx,
            request,
            f"FGEB-BELEG_{obj.plan_code}_{rsname}_{lname}-{date_str}.pdf"
        )
    print_paymentplan.label = "🖨️ " + _("Print PDF")
    print_paymentplan.attrs = {
        "class": "btn btn-block btn-info",
        "style": "margin-bottom: 1rem;",
        "data-action": "post-object",
        "onclick": RID_JS,
    }


    @admin.action(description=_("Export selected to PDF"))
    def export_selected_pdf(self, request, queryset):
        action = get_action("RELEASE:-@finances.paymentplan")
        if not action:
            messages.error(request, _("Release action not configured."))
            return
        
        # Sign each plan in the export
        for pp in queryset:
            try:
                sign_once(request, action, pp, note=_("Included in bulk PDF export"), window_seconds=10)
            except Exception:
                # Don't fail the whole export if one signature fails
                pass
        
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        rows = queryset.select_related("person_role__person", "person_role__role", "fiscal_year") \
                    .order_by("fiscal_year__start", "plan_code")
        return render_pdf_response(
            "finances/paymentplans_list_pdf.html",
            {"rows": rows, "org": OrgInfo.get_solo()},
            request,
            f"FGEB_SELECT-{date_str}.pdf"
        )


    # (3) Draft-stage banner
    def change_view(self, request, object_id, form_url="", extra_context=None):
        obj = self.get_object(request, object_id)
        if obj and obj.status == obj.Status.DRAFT:
            messages.info(
                request,
                mark_safe(
                    _("Draft: please wait for payment plan filing by person, then review if all fields are present and correct.")
                ),
            )
        return super().change_view(request, object_id, form_url, extra_context)

    # --- policy -------------------------------------------------------------
    def has_delete_permission(self, request, obj=None):
        """
        Allow deletion only for DRAFT status plans (if FY not locked).
        Once submitted, must use Cancel action for audit trail.
        """
        if not obj:
            return super().has_delete_permission(request, obj)
        
        # Check FY lock first
        if obj.fiscal_year_id:
            fy_st = state_snapshot(obj.fiscal_year)
            if fy_st.get("explicit_locked"):
                return False
        
        # Only allow deletion for DRAFT status
        status = paymentplan_status(obj)
        return status == "DRAFT"

    # ---------------- FY-aware Add behaviour ----------------
    def has_add_permission(self, request):
        """
        Show the green 'Add' button on the changelist only if a FY chip is selected (?fy=<id>).
        Always allow the actual add view itself.
        """
        allowed = super().has_add_permission(request)
        if not allowed:
            return False
        if request.path.endswith("/add/"):
            return True
        return bool(request.GET.get("fy"))

    def changelist_view(self, request, extra_context=None):
        """
        Remember the selected FY so we can prefill/hide the field on the add form.
        Also pass a label for the custom Add button template.
        """
        fy_id = request.GET.get("fy")
        if fy_id:
            request.session["paymentplans_selected_fy"] = fy_id
            try:
                fy_obj = FiscalYear.objects.only("start", "end", "code").get(pk=fy_id)
                selected_label = fy_obj.display_code()  # e.g. FY23_24 or WJ23_24
            except FiscalYear.DoesNotExist:
                selected_label = None
        else:
            request.session.pop("paymentplans_selected_fy", None)
            selected_label = None

        extra_context = extra_context or {}
        extra_context["selected_fy_label"] = selected_label  # used by template to label the Add button
        extra_context["selected_fy_id"] = fy_id
        return super().changelist_view(request, extra_context=extra_context)

    def get_form(self, request, obj=None, **kwargs):
        """
        On the add view, prefill and hide fiscal_year using ?fy= or the stored session value.
        """
        form = super().get_form(request, obj, **kwargs)
        if not obj and "fiscal_year" in form.base_fields:
            fy_id = (
                request.GET.get("fiscal_year")
                or request.GET.get("fy")
                or request.session.get("paymentplans_selected_fy")
            )
            if fy_id:
                form.base_fields["fiscal_year"].initial = fy_id
                form.base_fields["fiscal_year"].widget = forms.HiddenInput()

        # forward the FY to the person_role autocomplete endpoint
        fy_forward = (obj.fiscal_year_id if obj else
                      request.GET.get("fy") or request.session.get("paymentplans_selected_fy"))
        if "person_role" in form.base_fields and fy_forward:
            w = form.base_fields["person_role"].widget
            if hasattr(w, "url_parameters"):
                w.url_parameters["fy"] = fy_forward
            elif hasattr(w, "get_url"):
                url = w.get_url()
                sep = "&" if "?" in url else "?"
                w.attrs["data-autocomplete-url"] = f"{url}{sep}fy={fy_forward}"
        return form

    def get_fields(self, request, obj=None):
        """
        Ultra-minimal first save: show only scope + reference.
        After save, show everything with smart defaults.
        """
        if not obj:  # Initial ADD form
            return [
                "person_role",
                "fiscal_year", 
                "cost_center",
                "reference",
            ]
        
        # After first save, show all fields (normal fieldsets apply)
        return None  # Use fieldsets as defined

    def get_fieldsets(self, request, obj=None):
        """Only show full fieldsets after first save."""
        if not obj:
            # Minimal fieldsets for creation
            return (
                (_("Scope"), {
                    "fields": ("person_role", "fiscal_year", "cost_center"),
                    "description": _("Define the assignment and fiscal context for this payment plan."),
                }),
                (_("Banking"), {
                    "fields": ("reference",),
                    "description": _("Optional: Set payment reference text now (default: 'Funktionsgebühr')."),
                }),
            )
        
        # Full fieldsets after save
        return (
            (_("Scope"), {
                "fields": ("plan_code_or_hint", "person_role", "fiscal_year", "status"),
            }),
            (_("Budget"), {
                "fields": (
                    "cost_center",
                    "monthly_amount", "role_monthly_hint",
                    "total_override", "recommended_total_display",
                    "breakdown_preview"
                ),
                "description": _("Financial parameters set by WiRef."),
            }),
            (_("Payment Window"), {
                "fields": ("pay_start", "pay_end", "window_preview"),
            }),
            (_("Banking"), {
                "fields": (
                    "payee_name", "iban", "bic", "address",
                    "reference",
                    "bank_reference_preview_full"
                ),
                "description": _("Payee details completed via portal. Reference text set by admin."),
            }),
            (_("Submission"), {
                "fields": ("signed_person_at", "pdf_file", "submission_ip"),
                "description": _("Received from payee via public portal."),
            }),
            (_("Workflow & HankoSign"), {
                "fields": ("signatures_box",),
            }),
            (_("System"), {
                "fields": ("created_at", "updated_at", "version"),
            }),
        )

# =============== FiscalYear Admin ===============
@admin.register(FiscalYear)
class FiscalYearAdmin(
    SimpleHistoryAdmin,
    DjangoObjectActions,
    ImportExportModelAdmin,
    HelpPageMixin,
    ImportExportGuardMixin,
    ManagerOnlyHistoryMixin
    ):
    resource_classes = [FiscalYearResource]
    form = FiscalYearForm
    inlines = [AnnotationInline]
    # --- helpers ------------------------------------------------------------
    def _is_manager(self, request) -> bool:
        return is_finances_manager(request.user)

    # --- list / filters / search -------------------------------------------
    list_display = ("display_code", "start", "end", "is_active", "updated_at", "active_text")
    list_display_links = ("display_code",)
    list_filter = ("is_active", "start", "end", "is_active",)
    search_fields = ("code", "label")
    ordering = ("-start",)
    date_hierarchy = "start"
    list_per_page = 50

    # bulk actions
    actions = ("export_selected_pdf", "make_active")
    # readonly timestamps always
    readonly_fields = ("created_at", "updated_at", "active_text", "signatures_box")

    fieldsets = (
        (_("Scope"), {
            "fields": ("start", "end", "code", "label", "is_active"),
        }),
        (_("Workflow & HankoSign"), {
            "fields": ("signatures_box",),
        }),
        (_("System"), {
            "fields": ("created_at", "updated_at"),
        }),
    )


    @admin.display(description=_("Locked"))
    def active_text(self, obj):
        if not obj:
            return "—"
        
        st = state_snapshot(obj)
        is_locked = st.get("explicit_locked", False)
        
        return boolean_status_span(
            value=not is_locked,  # True = unlocked
            true_label=_("Open"),
            false_label=_("Locked"),
            true_code="ok",
            false_code="off",
        )


    @admin.display(description=_("Signatures"))
    def signatures_box(self, obj):
        return render_signatures_box(obj)


    # Prefill “Add” with current FY; user can change start and leave end blank.
    def get_changeform_initial_data(self, request):
        start = default_start()
        end = auto_end_from_start(start)
        return {"start": start, "end": end, "code": stored_code_from_dates(start, end)}


    # Make key fields read-only in the UI when locked (any user)
    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        
        if obj:
            st = state_snapshot(obj)
            if st.get("explicit_locked"):
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
    change_actions = ("print_fiscalyear", "lock_year", "unlock_year")
    @safe_admin_action
    def print_fiscalyear(self, request, obj):
        action = get_action("RELEASE:-@finances.fiscalyear")
        if not action:
            messages.error(request, _("Release action not configured."))
            return
        sign_once(request, action, obj, note=_("Printed fiscal year PDF"), window_seconds=10)
        signatures = seal_signatures_context(obj)
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        ctx = {"fy": obj, "org": OrgInfo.get_solo(), "signatures": signatures}
        return render_pdf_response(
            "finances/fiscalyear_pdf.html",
            ctx,
            request,
            f"WJFY-STATUS_{obj.display_code()}-{date_str}.pdf"
        )
    print_fiscalyear.label = "🖨️ " + _("Print receipt PDF")
    print_fiscalyear.attrs = {
        "class": "btn btn-block btn-secondary",
        "style": "margin-bottom: 1rem;",
        "data-action": "post-object",
        "onclick": RID_JS,
    }


    @admin.action(description=_("Print selected as overview PDF"))
    def export_selected_pdf(self, request, queryset):
        action = get_action("RELEASE:-@finances.fiscalyear")
        if not action:
            messages.error(request, _("Release action not configured."))
            return
        
        # Sign each FY in the export
        for fy in queryset:
            try:
                sign_once(request, action, fy, note=_("Included in bulk PDF export"), window_seconds=10)
            except Exception:
                # Don't fail the whole export if one signature fails
                pass
        
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        rows = queryset.order_by("-start")
        return render_pdf_response(
            "finances/fiscalyears_list_pdf.html",
            {"rows": rows, "org": OrgInfo.get_solo()},
            request,
            f"WJFY-SELECT-{date_str}.pdf"
        )


    @admin.action(description=_("Set selected as active (and clear others)"))
    def make_active(self, request, queryset):
        if not self._is_manager(request):
            messages.warning(request, _("You don't have permission to set active."))
            return

        # Block locked targets (check via state_snapshot)
        locked_objs = []
        for fy in queryset:
            st = state_snapshot(fy)
            if st.get("explicit_locked"):
                locked_objs.append(fy)
        
        if locked_objs:
            messages.warning(
                request,
                _("You cannot set a locked fiscal year as active. Deselect locked rows first.")
            )
            return

        count = queryset.count()
        if count != 1:
            messages.warning(
                request,
                _("Select exactly one fiscal year to set active (you selected %(n)d).") % {"n": count}
            )
            return

        target = queryset.first()
        if target.is_active:
            messages.info(
                request,
                _("%(code)s is already the active fiscal year.") % {"code": target.display_code()}
            )
            return

        try:
            with transaction.atomic():
                FiscalYear.objects.exclude(pk=target.pk).update(is_active=False)
                target.is_active = True
                target.save(update_fields=["is_active"])
            messages.success(
                request,
                _("Activated %(code)s as the current fiscal year.") % {"code": target.display_code()}
            )
        except IntegrityError:
            messages.error(
                request,
                _("Could not set active due to a database constraint (another year may have been activated concurrently).")
            )


    # === Object actions: Lock / Unlock (managers only) ===
    def get_change_actions(self, request, object_id, form_url):
        actions = super().get_change_actions(request, object_id, form_url)
        
        if not self._is_manager(request):
            # only allow Print PDF for editors
            return [a for a in actions if a == "print_fiscalyear"]
        
        obj = self.get_object(request, object_id)
        if obj:
            st = state_snapshot(obj)
            is_locked = st.get("explicit_locked", False)
            
            if is_locked:
                # hide Lock, keep Unlock + PDF
                return [a for a in actions if a in ("unlock_year", "print_fiscalyear")]
            else:
                # show Lock + PDF
                return [a for a in actions if a in ("lock_year", "print_fiscalyear")]
        
        return actions


    @transaction.atomic
    @safe_admin_action
    def lock_year(self, request, obj):
        if not self._is_manager(request):
            messages.warning(request, _("You don't have permission to lock years."))
            return
        # Check if already locked via HankoSign
        st = state_snapshot(obj)
        if st.get("explicit_locked"):
            messages.info(request, _("Already locked."))
            return
        action = get_action("LOCK:-@finances.fiscalyear")
        if not action:
            messages.error(request, _("Lock action not configured."))
            return
        record_signature(request.user, action, obj, note=_("Fiscal year %(code)s locked") % {"code": f"{obj.code}"})
        create_system_annotation(obj, "LOCK", user=request.user)
        messages.success(request, _("Fiscal year locked."))
    lock_year.label = _("Lock year")
    lock_year.attrs = {
        "class": "btn btn-block btn-warning",
        "style": "margin-bottom: 1rem;",
    }


    @transaction.atomic
    @safe_admin_action
    def unlock_year(self, request, obj):
        if not self._is_manager(request):
            messages.warning(request, _("You don't have permission to unlock years."))
            return
        # Check if locked via HankoSign
        st = state_snapshot(obj)
        if not st.get("explicit_locked"):
            messages.info(request, _("Already unlocked."))
            return
        action = get_action("UNLOCK:-@finances.fiscalyear")
        if not action:
            messages.error(request, _("Unlock action not configured."))
            return
        record_signature(request.user, action, obj, note=_("Fiscal year %(code)s unlocked") % {"code": f"{obj.code}"})
        create_system_annotation(obj, "UNLOCK", user=request.user)
        messages.success(request, _("Fiscal year unlocked."))
    unlock_year.label = _("Unlock year")
    unlock_year.attrs = {
        "class": "btn btn-block btn-success",
        "style": "margin-bottom: 1rem;",
    }


    def get_changelist_row_attrs(self, request, obj):
        st = state_snapshot(obj)
        is_locked = st.get("explicit_locked", False)
        
        # If locked, show locked state; otherwise show active state
        if is_locked:
            return row_state_attr_for_boolean(
                value=False,  # locked
                true_code="ok",
                false_code="off",
            )
        else:
            return row_state_attr_for_boolean(
                value=obj.is_active,
                true_code="ok",
                false_code="off",
            )
