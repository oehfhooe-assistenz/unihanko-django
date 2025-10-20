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

from .models import FiscalYear, PaymentPlan, default_start, auto_end_from_start, stored_code_from_dates
from core.pdf import render_pdf_response
from core.admin_mixins import ImportExportGuardMixin


# =============== Import–Export ===============
class FiscalYearResource(resources.ModelResource):
    class Meta:
        model = FiscalYear
        fields = (
            "id", "code", "label", "start", "end",
            "is_active", "is_locked", "created_at", "updated_at"
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
        if "pay_start" in F:
            F["pay_start"].help_text = _(
                "Optional. Leave empty on first save to default to the assignment/FY window. "
                "We hard-clamp to the fiscal year."
            )
        if "pay_end" in F:
            F["pay_end"].help_text = _(
                "Optional. Leave empty on first save to default to the assignment/FY window. "
                "Must not be before start."
            )

        # (2) No silent autofill of name/amount. Only default the reference on *add*.
        if not obj.pk and "reference" in F and not self.initial.get("reference"):
            self.initial["reference"] = "Funktionsgebühr"

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
class PaymentPlanAdmin(ImportExportGuardMixin, DjangoObjectActions, ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [PaymentPlanResource]
    form = PaymentPlanForm
    actions = ("export_selected_pdf",)

    # --- helpers ------------------------------------------------------------
    def _is_manager(self, request) -> bool:
        return request.user.groups.filter(name="module:finances:manager").exists()

    # --- list / filters / search -------------------------------------------
    list_display = (
        "plan_code",
        "person_role",
        "fiscal_year",
        "window_display",
        "cost_center",
        "monthly_amount",
        "effective_total_display",
        "status_badge",
        "updated_at",
    )
    list_filter = (FYChipsFilter, "status", "pay_start", "pay_end")
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
    autocomplete_fields = ("person_role", "fiscal_year")

    # (3/4) include bank-reference previews as read-only
    readonly_fields = (
        "plan_code_or_hint",
        "created_at", "updated_at",
        "window_preview", "breakdown_preview", "recommended_total_display", "role_monthly_hint",
        "bank_reference_preview_full", "bank_reference_preview_short", "pdf_file",
    )

    list_per_page = 50
    ordering = ("-created_at",)

    fieldsets = (
        (_("Scope"), {
            "fields": ("plan_code_or_hint", "person_role", "fiscal_year"),
        }),
        (_("Budget"), {
            "fields": ("cost_center",),
        }),
        (_("Payee & banking"), {
            "fields": (
                ("payee_name",), ("iban"), ("bic"),
                ("address"), "reference",
                "bank_reference_preview_full", "bank_reference_preview_short",
            ),
        }),
        (_("Standing invoice window"), {
            "fields": (("pay_start"), ("pay_end"), "window_preview"),
        }),
        (_("Monetary amounts"), {
            "fields": (("monthly_amount"), "role_monthly_hint", ("total_override"), "recommended_total_display", "breakdown_preview"),
        }),
        (_("Payment Plan PDF Center [TBA]"), {
            "fields": (("pdf_file"),),
        }),
        (_("Status & signatures"), {
            "fields": (("status"), ("status_note"),
                       ("signed_person_at"), ("signed_wiref_at"), ("signed_chair_at")),
        }),
        (_("Miscellaneous"), {
            "fields": (("notes"),),
        }),
        (_("Timestamps"), {
            "fields": (("created_at"), ("updated_at"),),
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
    def status_badge(self, obj):
        colors = {
            obj.Status.DRAFT: "#6b7280",
            obj.Status.ACTIVE: "#2563eb",
            obj.Status.SUSPENDED: "#f59e0b",
            obj.Status.FINISHED: "#10b981",
            obj.Status.CANCELLED: "#ef4444",
        }
        label = obj.get_status_display()
        color = colors.get(obj.status, "#6b7280")
        return format_html('<span class="badge" style="background:{};color:#fff;">{}</span>', color, label)

    @admin.display(description=_("Resolved window (clamped to FY)"))
    def window_preview(self, obj):
        if not obj.pk:
            return _("— will be shown after saving —")
        s, e = obj.resolved_window()
        if s > e:
            return format_html('<div style="color:#ef4444;">{}</div>', _("No overlap with fiscal year."))
        fy = obj.fiscal_year
        return format_html(
            '<div style="font-size:12px;">'
            '<div><strong>{}</strong><span style="color:var(--uh-accent);font-weight:bold;"> {} → {}</span></div>'
            '<div>{}:<span style="color:var(--uh-accent-700);"> {} → {} </span></div>'
            "</div>",
            _("Effective invoice (plan) window:"),
            s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d"),
            _("FY bounds"),
            fy.start.strftime("%Y-%m-%d"), fy.end.strftime("%Y-%m-%d"),
        )

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
        if not obj or not obj.pk:
            return _("— will be shown after saving —")
        rows = obj.months_breakdown()
        if not rows:
            return _("No coverage in this fiscal year.")
        lines = [
            f"{r['year']}-{r['month']:02d}: {r['days']}d × {format(r['fraction'], '.4f')}"
            for r in rows
        ]
        text = "\n".join(lines)
        return format_html(
            "<pre style='margin:.5rem 0 .25rem 0; font-size:12px; white-space:pre-wrap;'>{}</pre>",
            text,
        )

    @admin.display(description=_("Recommended total ['richtwert']"))
    def recommended_total_display(self, obj):
        if not obj.pk:
            return _("— will be shown after saving —")
        val = format(obj.recommended_total(), ".2f")
        return format_html('<code style="color: yellow;">{} €</code>', val)

    # (3/4) Bank reference previews (read-only)
    @admin.display(description=_("Bank reference (full)"))
    def bank_reference_preview_full(self, obj):
        if not obj or not getattr(obj, "pk", None):
            return "—"
        return format_html(
            '<div><code>{}</code></div>'
            '<div class="help-block" style="margin-top:.25rem; color:#6b7280;">{}</div>',
            getattr(obj, "bank_reference_long", ""),
            _("Format: {reference} – {payee name} – {cost center}. Updated after saving. Used for exports."),
        )

    @admin.display(description=_("Bank reference (≤140)"))
    def bank_reference_preview_short(self, obj):
        if not obj or not getattr(obj, "pk", None):
            return "—"
        short_val = ""
        if hasattr(obj, "bank_reference_short"):
            try:
                short_val = obj.bank_reference_short(140)
            except TypeError:
                short_val = getattr(obj, "bank_reference_short", "")
        return format_html(
            '<div><code>{}</code></div>'
            '<div class="help-block" style="margin-top:.25rem; color:#6b7280;">{}</div>',
            short_val,
            _("Max 140 chars. Falls back to initials if needed; truncates the left part. Updated after saving."),
        )
    
    # --- read-only rules ----------------------------------------------------
    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj:  # editing existing plan
            ro += ["fiscal_year", "person_role"]
        if obj and obj.fiscal_year and obj.fiscal_year.is_locked:
            ro += [
                "person_role", "fiscal_year",
                "payee_name", "iban", "bic", "address", "reference",
                "pay_start", "pay_end",
                "monthly_amount", "total_override",
                "status", "status_note",
                "signed_person_at", "signed_wiref_at", "signed_chair_at",
                "pdf_file",
                "bank_reference_preview_full", "bank_reference_preview_short",
            ]
        return list(dict.fromkeys(ro))

    # --- queryset perf ------------------------------------------------------
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("person_role__person", "person_role__role", "fiscal_year")

    # --- object actions (status transitions) --------------------------------
    change_actions = ("activate_plan", "suspend_plan", "finish_plan", "cancel_plan", "print_pdf")

    def get_change_actions(self, request, object_id, form_url):
        actions = list(super().get_change_actions(request, object_id, form_url))
        obj = self.get_object(request, object_id)
        if not obj:
            return actions
        if obj.fiscal_year and obj.fiscal_year.is_locked:
            actions = [a for a in actions if a in ("print_pdf",)]
        elif obj.status == obj.Status.DRAFT:
            actions = [a for a in actions if a in ("activate_plan", "cancel_plan", "print_pdf")]
        elif obj.status == obj.Status.ACTIVE:
            actions = [a for a in actions if a in ("suspend_plan", "finish_plan", "cancel_plan", "print_pdf")]
        elif obj.status == obj.Status.SUSPENDED:
            actions = [a for a in actions if a in ("activate_plan", "finish_plan", "cancel_plan", "print_pdf")]
        else:
            actions = [a for a in actions if a in ("print_pdf",)]
        return actions

    def activate_plan(self, request, obj):
        try:
            obj.mark_active(note=_("Activated from admin"))
        except IntegrityError:
            self.message_user(
                request,
                _("Could not activate: another active plan exists for this assignment and year."),
                level=messages.ERROR,
            )
            return
        self.message_user(request, _("Plan activated."), level=messages.SUCCESS)
    activate_plan.label = _("Activate")
    activate_plan.attrs = {"class": "btn btn-block btn-success btn-sm", "style": "margin-bottom: 1rem;",}

    def suspend_plan(self, request, obj):
        obj.mark_suspended(note=_("Suspended from admin"))
        self.message_user(request, _("Plan suspended."), level=messages.SUCCESS)
    suspend_plan.label = _("Suspend")
    suspend_plan.attrs = {"class": "btn btn-block btn-warning btn-sm", "style": "margin-bottom: 1rem;",}

    def finish_plan(self, request, obj):
        obj.mark_finished(note=_("Finished from admin"))
        self.message_user(request, _("Plan finished."), level=messages.SUCCESS)
    finish_plan.label = _("Finish")
    finish_plan.attrs = {"class": "btn btn-block btn-secondary btn-sm", "style": "margin-bottom: 1rem;",}

    def cancel_plan(self, request, obj):
        obj.mark_cancelled(note=_("Cancelled from admin"))
        self.message_user(request, _("Plan cancelled."), level=messages.SUCCESS)
    cancel_plan.label = _("Cancel")
    cancel_plan.attrs = {"class": "btn btn-block btn-danger btn-sm", "style": "margin-bottom: 1rem;",}

    # === PDF actions (single + bulk) ===
    def print_pdf(self, request, obj):
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        lname = slugify(obj.person_role.person.last_name)[:20]
        rsname = slugify(obj.person_role.role.short_name)[:10]
        ctx = {"pp": obj}
        return render_pdf_response("finances/paymentplan_pdf.html", ctx, request, f"FGEB-BELEG_{obj.plan_code}_{rsname}_{lname}-{date_str}.pdf")
    print_pdf.label = "🖨️ " + _("Print Receipt PDF")
    print_pdf.attrs = {"class": "btn btn-block btn-secondary btn-sm", "style": "margin-bottom: 1rem;",}

    @admin.action(description=_("Export selected to PDF"))
    def export_selected_pdf(self, request, queryset):
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        rows = queryset.select_related("person_role__person", "person_role__role", "fiscal_year") \
                       .order_by("fiscal_year__start", "plan_code")
        return render_pdf_response("finances/paymentplans_list_pdf.html", {"rows": rows}, request, f"FGEB_SELECT-{date_str}.pdf")

    # (3) Draft-stage banner
    def change_view(self, request, object_id, form_url="", extra_context=None):
        obj = self.get_object(request, object_id)
        if obj and obj.status == obj.Status.DRAFT:
            messages.info(
                request,
                mark_safe(
                    _("Draft: please review payee name, address, IBAN/BIC, reference and cost center manually. No fields are auto-filled.")
                ),
            )
        return super().change_view(request, object_id, form_url, extra_context)

    # --- policy -------------------------------------------------------------
    def has_delete_permission(self, request, obj=None):
        return False

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

    # IMPORTANT: no prefill of monthly_amount/payee_name here anymore
    def get_changeform_initial_data(self, request):
        return super().get_changeform_initial_data(request)


# =============== FiscalYear Admin ===============
@admin.register(FiscalYear)
class FiscalYearAdmin(ImportExportGuardMixin, DjangoObjectActions, ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [FiscalYearResource]
    form = FiscalYearForm

    # --- helpers ------------------------------------------------------------
    def _is_manager(self, request) -> bool:
        return request.user.groups.filter(name="module:finances:manager").exists()

    # --- list / filters / search -------------------------------------------
    list_display = ("display_code", "start", "end", "status_badges", "updated_at")
    list_filter = ("is_active", "is_locked", "start", "end")
    search_fields = ("code", "label")
    ordering = ("-start",)
    date_hierarchy = "start"
    list_per_page = 50

    # bulk actions
    actions = ("export_selected_pdf", "make_active")

    # readonly timestamps always
    readonly_fields = ("created_at", "updated_at", "locked_state")

    fieldsets = (
        (_("Basics"), {"fields": (("start"), ("end"), "code", "label", "is_active", "locked_state")}),
        (_("Timestamps"), {"fields": (("created_at"), ("updated_at"),)}),
    )

    @admin.display(description=_("Locked"))
    def locked_state(self, obj):
        if not obj:
            return "—"
        if obj.is_locked:
            return format_html('<span class="badge" style="background:#6b7280;color:#fff;">{}</span>', _("Locked"))
        return format_html('<span class="badge" style="background:#10b981;color:#fff;">{}</span>', _("Open"))

    @admin.display(description=_("Status"))
    def status_badges(self, obj):
        parts = []
        if obj.is_active:
            parts.append('<span class="badge" style="background:#2563eb;color:#fff;margin-right:.25rem;">{}</span>'.format(_("Active")))
        if obj.is_locked:
            parts.append('<span class="badge" style="background:#6b7280;color:#fff;">{}</span>'.format(_("Locked")))
        else:
            parts.append('<span class="badge" style="background:#f59e0b;color:#fff;">{}</span>'.format(_("Open")))
        return format_html(" ".join(parts))

    # Prefill “Add” with current FY; user can change start and leave end blank.
    def get_changeform_initial_data(self, request):
        start = default_start()
        end = auto_end_from_start(start)
        return {"start": start, "end": end, "code": stored_code_from_dates(start, end)}

    # Make key fields read-only in the UI when locked (any user)
    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj and obj.is_locked:
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
    change_actions = ("print_pdf", "lock_year", "unlock_year")

    def print_pdf(self, request, obj):
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        ctx = {"fy": obj}
        return render_pdf_response("finances/fiscalyear_pdf.html", ctx, request, f"WJFY-STATUS_{obj.display_code()}-{date_str}.pdf")
    print_pdf.label = "🖨️ " + _("Print receipt PDF")
    print_pdf.attrs = {"class": "btn btn-block btn-secondary btn-sm", "style": "margin-bottom: 1rem;",}

    @admin.action(description=_("Print selected as overview PDF"))
    def export_selected_pdf(self, request, queryset):
        date_str = timezone.localtime().strftime("%Y-%m-%d")
        rows = queryset.order_by("-start")
        return render_pdf_response("finances/fiscalyears_list_pdf.html", {"rows": rows}, request, f"WJFY-SELECT-{date_str}.pdf")

    @admin.action(description=_("Set selected as active (and clear others)"))
    def make_active(self, request, queryset):
        if not self._is_manager(request):
            self.message_user(request, _("You don’t have permission to set active."), level=messages.WARNING)
            return

        # Block locked targets and enforce a single selection
        locked = queryset.filter(is_locked=True)
        if locked.exists():
            self.message_user(
                request,
                _("You cannot set a locked fiscal year as active. Deselect locked rows first."),
                level=messages.WARNING,
            )
            return

        count = queryset.count()
        if count != 1:
            self.message_user(
                request,
                _("Select exactly one fiscal year to set active (you selected %(n)d).") % {"n": count},
                level=messages.WARNING,
            )
            return

        target = queryset.first()
        if target.is_active:
            self.message_user(
                request,
                _("%(code)s is already the active fiscal year.") % {"code": target.display_code()},
                level=messages.INFO,
            )
            return

        try:
            with transaction.atomic():
                FiscalYear.objects.exclude(pk=target.pk).update(is_active=False)
                target.is_active = True
                target.save(update_fields=["is_active"])
            self.message_user(
                request,
                _("Activated %(code)s as the current fiscal year.") % {"code": target.display_code()},
                level=messages.SUCCESS,
            )
        except IntegrityError:
            self.message_user(
                request,
                _("Could not set active due to a database constraint (another year may have been activated concurrently)."),
                level=messages.ERROR,
            )

    # === Object actions: Lock / Unlock (managers only) ===
    def get_change_actions(self, request, object_id, form_url):
        actions = super().get_change_actions(request, object_id, form_url)
        if not self._is_manager(request):
            # only allow Print PDF for editors
            return [a for a in actions if a == "print_pdf"]
        obj = self.get_object(request, object_id)
        if obj:
            if obj.is_locked:
                # hide Lock, keep Unlock + PDF
                return [a for a in actions if a in ("unlock_year", "print_pdf")]
            else:
                # show Lock + PDF
                return [a for a in actions if a in ("lock_year", "print_pdf")]
        return actions

    def lock_year(self, request, obj):
        if not self._is_manager(request):
            self.message_user(request, _("You don’t have permission to lock years."), level=messages.WARNING)
            return
        if obj.is_locked:
            self.message_user(request, _("Already locked."), level=messages.INFO)
            return
        obj.is_locked = True
        obj.save(update_fields=["is_locked"])
        self.message_user(request, _("Fiscal year locked."), level=messages.SUCCESS)
    lock_year.label = _("Lock year")
    lock_year.attrs = {"class": "btn btn-block btn-warning btn-sm", "style": "margin-bottom: 1rem;",}

    def unlock_year(self, request, obj):
        if not self._is_manager(request):
            self.message_user(request, _("You don’t have permission to unlock years."), level=messages.WARNING)
            return
        if not obj.is_locked:
            self.message_user(request, _("Already open."), level=messages.INFO)
            return
        obj.is_locked = False
        obj.save(update_fields=["is_locked"])
        self.message_user(request, _("Fiscal year unlocked."), level=messages.SUCCESS)
    unlock_year.label = _("Unlock year")
    unlock_year.attrs = {"class": "btn btn-block btn-success btn-sm", "style": "margin-bottom: 1rem;",}
