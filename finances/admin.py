from django.contrib import admin, messages
from django import forms
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html, format_html_join
from django_object_actions import DjangoObjectActions
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from simple_history.admin import SimpleHistoryAdmin
from django.db import transaction, IntegrityError
from django.utils.safestring import mark_safe

from .models import FiscalYear, PaymentPlan, default_start, auto_end_from_start, stored_code_from_dates
from core.pdf import render_pdf_response


# =============== Import–Export ===============
class FiscalYearResource(resources.ModelResource):
    class Meta:
        model = FiscalYear
        fields = ("id", "code", "label", "start", "end", "is_active", "is_locked", "created_at", "updated_at")
        export_order = ("id", "code", "label", "start", "end", "is_active", "is_locked", "created_at", "updated_at")

class PaymentPlanResource(resources.ModelResource):
    class Meta:
        model = PaymentPlan
        fields = (
            "id",
            "person_role",
            "fiscal_year",
            "payee_name",
            "iban", "bic", "reference",
            "pay_start", "pay_end",
            "monthly_amount", "total_override",
            "status", "status_note",
            "signed_person_at", "signed_wiref_at", "signed_chair_at",
            "created_at", "updated_at",
        )
        export_order = fields

# =============== Admin form ===============
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

        if "pay_start" in F:
            F["pay_start"].help_text = _(
                "Optional. Leave empty to default to the assignment/FY window. "
                "We hard-clamp to the fiscal year."
            )
        if "pay_end" in F:
            F["pay_end"].help_text = _(
                "Optional. Leave empty to default to the assignment/FY window. "
                "Must not be before start."
            )
        if "total_override" in F:
            F["total_override"].help_text = _(
                "Optional. If set, this replaces the computed total (“richtwert”)."
            )
        if "payee_name" in F:
            F["payee_name"].help_text = _(
                "Optional. Leave blank to use the person’s name from the assignment."
            )

        # Prefill monthly on Add using the assignment's role
        if not self.instance.pk and "monthly_amount" in F:
            pr = self.initial.get("person_role") or getattr(self.instance, "person_role", None)
            role_amt = None
            try:
                role_amt = getattr(getattr(pr, "role", None), "default_monthly_amount", None)
            except Exception:
                pass
            if role_amt is not None and not self.initial.get("monthly_amount"):
                self.initial["monthly_amount"] = role_amt

    def clean_iban(self):
        iban = (self.cleaned_data.get("iban") or "").replace(" ", "").upper()
        return iban

    def clean_bic(self):
        bic = (self.cleaned_data.get("bic") or "").replace(" ", "").upper()
        return bic

    def clean_reference(self):
        ref = (self.cleaned_data.get("reference") or "").strip()
        return ref or ("Funktionsgebühr " + self.cleaned_data.get("payee_name"))



# =============== Admin ===============
@admin.register(FiscalYear)
class FiscalYearAdmin(DjangoObjectActions, ImportExportModelAdmin, SimpleHistoryAdmin):
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
        ctx = {"fy": obj}
        return render_pdf_response("finances/fiscalyear_pdf.html", ctx, request, f"{obj.display_code()}.pdf")
    print_pdf.label = _("Print PDF")
    print_pdf.attrs = {"class": "btn btn-block btn-outline-secondary btn-sm"}

    @admin.action(description=_("Export selected to PDF"))
    def export_selected_pdf(self, request, queryset):
        rows = queryset.order_by("-start")
        return render_pdf_response("finances/fiscalyears_list_pdf.html", {"rows": rows}, request, "fiscal_years.pdf")

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
                level=messages.warning,
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
        except IntegrityError:
            self.message_user(
                request,
                _("Could not set active due to a database constraint (another year may have been activated concurrently)."),
                level=messages.ERROR,
            )
            return

        self.message_user(
            request,
            _("Activated %(code)s as the current fiscal year.") % {"code": target.display_code()},
            level=messages.SUCCESS,
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
    lock_year.attrs = {"class": "btn btn-block btn-outline-warning btn-sm"}

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
    unlock_year.attrs = {"class": "btn btn-block btn-outline-success btn-sm"}

from .models import FiscalYear, PaymentPlan

class FYChipsFilter(admin.SimpleListFilter):
    title = _("Year")
    parameter_name = "fy"
    template = "admin/filters/fy_chips.html"   # custom template below

    def lookups(self, request, model_admin):
        # show most recent 6 years (tweak as you like)
        fys = FiscalYear.objects.order_by("-start")[:4]
        # label: 2023, 2024… (or use fy.display_code() for FY23_24)
        return [(fy.pk, str(fy.start.year)) for fy in fys]

    def queryset(self, request, qs):
        val = self.value()
        if val:
            return qs.filter(fiscal_year_id=val)
        return qs

@admin.register(PaymentPlan)
class PaymentPlanAdmin(DjangoObjectActions, ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [PaymentPlanResource]
    form = PaymentPlanForm

    # --- helpers ------------------------------------------------------------
    def _is_manager(self, request) -> bool:
        return request.user.groups.filter(name="module:finances:manager").exists()

    # --- list / filters / search -------------------------------------------
    list_display = (
        "person_role",
        "fiscal_year",
        "window_display",
        "monthly_amount",
        "effective_total_display",
        "status_badge",
        "updated_at",
    )
    list_filter = (FYChipsFilter, "status", "pay_start", "pay_end")
    search_fields = (
        "person_role__person__last_name",
        "person_role__person__first_name",
        "person_role__role__name",
        "payee_name",
        "reference",
    )
    autocomplete_fields = ("person_role", "fiscal_year")
    readonly_fields = (
        "created_at", "updated_at",
        "window_preview", "breakdown_preview", "recommended_total_display", "role_monthly_hint",
    )
    date_hierarchy = None
    list_per_page = 50
    ordering = ("-created_at",)

    fieldsets = (
        (_("Scope"), {
            "fields": ("person_role", "fiscal_year"),
        }),
        (_("Payee & banking"), {
            "fields": (("payee_name",), ("iban"), ("bic"), "reference"),
        }),
        (_("Standing invoice window"), {
            "fields": (("pay_start"), ("pay_end"), "window_preview"),
        }),
        (_("Monetary amounts"), {
            "fields": (("monthly_amount"), "role_monthly_hint", ("total_override"), "recommended_total_display", "breakdown_preview"),
        }),
        (_("Status & signatures"), {
            "fields": (("status"), ("status_note"),
                       ("signed_person_at"), ("signed_wiref_at"), ("signed_chair_at")),
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
        # Pre-format to string to avoid SafeString + format spec collision
        val = format(obj.effective_total, ".2f")
        return format_html("<strong>{} €</strong>", val)

    @admin.display(description=_("Status"))
    def status_badge(self, obj):
        colors = {
            obj.Status.DRAFT: "#6b7280",      # gray
            obj.Status.ACTIVE: "#2563eb",     # blue
            obj.Status.SUSPENDED: "#f59e0b",  # amber
            obj.Status.FINISHED: "#10b981",   # green
            obj.Status.CANCELLED: "#ef4444",  # red
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

    @admin.display(description=_("Bank line preview"))
    def bank_preview(self, obj):
        if not obj.pk:
            return _("— will be shown after saving —")
        iban = (obj.iban or "").replace(" ", "")
        masked = f"{iban[:4]}••••••••••••{iban[-4:]}" if len(iban) > 8 else iban
        val = format(obj.effective_total, ".2f")
        return format_html("<code>{} | {} € | {}</code>", masked, val, obj.reference or _("Stipend"))

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

        # Plain text lines; no HTML tags inside, so nothing to escape/strip
        lines = [
            f"{r['year']}-{r['month']:02d}: {r['days']}d × {format(r['fraction'], '.4f')}"
            for r in rows
        ]
        text = "\n".join(lines)
        # Render in <pre> so newlines are preserved and content is visibly non-empty
        return format_html(
            "<pre style='margin:.5rem 0 .25rem 0; font-size:12px; white-space:pre-wrap;'>{}</pre>",
            text,
        )


    @admin.display(description=_("Recommended total"))
    def recommended_total_display(self, obj):
        if not obj.pk:
            return _("— will be shown after saving —")
        val = format(obj.recommended_total(), ".2f")
        return format_html('<code style="color: yellow;">{} €</code>', val)

    # --- read-only when FY locked ------------------------------------------
    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj and obj.fiscal_year and obj.fiscal_year.is_locked:
            # lock everything except status display (but status itself becomes immutable via actions hiding)
            ro += [
                "person_role", "fiscal_year",
                "payee_name", "iban", "bic", "reference",
                "pay_start", "pay_end",
                "monthly_amount", "total_override",
                "status", "status_note",
                "signed_person_at", "signed_wiref_at", "signed_chair_at",
                "pdf_file",
            ]
        return ro

    # --- queryset perf ------------------------------------------------------
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("person_role__person", "person_role__role", "fiscal_year")

    # --- object actions (status transitions) --------------------------------
    change_actions = ("activate_plan", "suspend_plan", "finish_plan")

    def get_change_actions(self, request, object_id, form_url):
        actions = list(super().get_change_actions(request, object_id, form_url))
        obj = self.get_object(request, object_id)
        if not obj:
            return actions

        # If FY locked: hide all transitions
        if obj.fiscal_year and obj.fiscal_year.is_locked:
            return []

        # Show/hide based on status
        if obj.status == obj.Status.DRAFT:
            actions = [a for a in actions if a in ("activate_plan",)]
        elif obj.status == obj.Status.ACTIVE:
            actions = [a for a in actions if a in ("suspend_plan", "finish_plan")]
        elif obj.status == obj.Status.SUSPENDED:
            actions = [a for a in actions if a in ("activate_plan", "finish_plan")]
        else:
            # FINISHED / CANCELLED: no transitions
            actions = []
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
    activate_plan.attrs = {"class": "btn btn-block btn-outline-success btn-sm"}

    def suspend_plan(self, request, obj):
        obj.mark_suspended(note=_("Suspended from admin"))
        self.message_user(request, _("Plan suspended."), level=messages.SUCCESS)
    suspend_plan.label = _("Suspend")
    suspend_plan.attrs = {"class": "btn btn-block btn-outline-warning btn-sm"}

    def finish_plan(self, request, obj):
        obj.mark_finished(note=_("Finished from admin"))
        self.message_user(request, _("Plan finished."), level=messages.SUCCESS)
    finish_plan.label = _("Finish")
    finish_plan.attrs = {"class": "btn btn-block btn-outline-secondary btn-sm"}

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        pr_id = request.GET.get("person_role") or request.GET.get("person_role__id__exact")
        if pr_id:
            from people.models import PersonRole
            try:
                pr = PersonRole.objects.select_related("role", "person").get(pk=pr_id)
                amt = getattr(pr.role, "default_monthly_amount", None)
                if amt:
                    initial["monthly_amount"] = amt
                initial.setdefault("payee_name", f"{pr.person.first_name} {pr.person.last_name}".strip())
            except PersonRole.DoesNotExist:
                pass
        return initial

    # --- policy -------------------------------------------------------------
    def has_delete_permission(self, request, obj=None):
        return False

