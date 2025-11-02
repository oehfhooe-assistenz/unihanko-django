#finances/models.py
from __future__ import annotations
from datetime import date, timedelta
from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords
import re
from core.utils.privacy import mask_iban

# --- helpers ---------------------------------------------------------------

from decimal import Decimal, ROUND_HALF_UP
import calendar

def calculate_proration_breakdown(
    start: date,
    end: date,
    *,
    accounting_month_days: int = 30
) -> list[dict]:
    """
    Pure function: Calculate monthly proration breakdown for a date range.
    
    Uses simple daily proration against a fixed "accounting month" 
    (default 30 days) for consistent financial calculations.
    
    Args:
        start: First day of coverage (inclusive)
        end: Last day of coverage (inclusive, will be normalized if it's the 1st)
        accounting_month_days: Days per month for proration calc (default 30)
    
    Returns:
        List of dicts with keys:
        - year (int)
        - month (int)
        - days (int): actual calendar days covered
        - month_days (int): actual calendar days in that month
        - fraction (Decimal): days / accounting_month_days
    
    Example:
        >>> calculate_proration_breakdown(date(2024, 7, 15), date(2024, 9, 14))
        [
            {"year": 2024, "month": 7, "days": 17, "month_days": 31, "fraction": Decimal("0.5667")},
            {"year": 2024, "month": 8, "days": 31, "month_days": 31, "fraction": Decimal("1.0333")},
            {"year": 2024, "month": 9, "days": 14, "month_days": 30, "fraction": Decimal("0.4667")},
        ]
    """
    # Normalize end date (treat 1st of month as last day of previous month)
    if end.day == 1:
        end = end - timedelta(days=1)
    
    # Validation
    if start > end:
        return []
    
    breakdown = []
    current = date(start.year, start.month, 1)  # Start at month boundary
    end_month = date(end.year, end.month, 1)
    
    # Iterate month by month until we've processed the end month
    while current <= end_month:
        # Calculate actual month boundaries
        month_days_real = calendar.monthrange(current.year, current.month)[1]
        month_start = current
        month_end = current.replace(day=month_days_real)
        
        # Find overlap between [start, end] and this month
        segment_start = max(start, month_start)
        segment_end = min(end, month_end)
        
        # Only include if there's actual overlap
        if segment_start <= segment_end:
            covered_days = (segment_end - segment_start).days + 1  # inclusive
            fraction = Decimal(covered_days) / Decimal(accounting_month_days)
            
            breakdown.append({
                "year": current.year,
                "month": current.month,
                "days": covered_days,
                "month_days": month_days_real,
                "fraction": fraction.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            })
        
        # Move to next month
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    
    return breakdown

def auto_end_from_start(start: date) -> date:
    """
    End = one year minus one day after start.
    Robust across leap years.
    """
    try:
        one_year_later = start.replace(year=start.year + 1)
    except ValueError:
        # Feb 29 etc.
        one_year_later = start + timedelta(days=365)
    return one_year_later - timedelta(days=1)

def default_start() -> date:
    """
    Prefill start to FY start that contains 'today' (1 July).
    """
    today = timezone.localdate()
    y = today.year if today >= date(today.year, 7, 1) else today.year - 1
    return date(y, 7, 1)

def stored_code_from_dates(start: date, end: date) -> str:
    """DB value (German style): WJ24_25"""
    return f"WJ{start.year % 100:02d}_{end.year % 100:02d}"

def localized_code(start: date, end: date, lang: str | None = None) -> str:
    """
    Display value depending on language:
      en*  -> FYyy_yy
      other-> WJyy_yy
    """
    from django.utils.translation import get_language  # local import to keep model import-time clean
    lang = (lang or get_language() or "en").lower()
    pref = "FY" if lang.startswith("en") else "WJ"
    return f"{pref}{start.year % 100:02d}_{end.year % 100:02d}"



# --- payment plan state machine ------------------------------------------------------------

def paymentplan_status(pp) -> str:
    """
    Determine PaymentPlan workflow status from HankoSign signatures and dates.
    
    Returns one of: DRAFT | PENDING | ACTIVE | CANCELLED | FINISHED
    
    Logic:
      - CANCELLED: REJECT signature exists
      - DRAFT: No SUBMIT signature (or withdrawn)
      - PENDING: Submitted but missing APPROVE:WIREF, APPROVE:CHAIR, or VERIFY:WIREF
      - FINISHED: All approvals + verify done, but past end date
      - ACTIVE: All approvals + verify done, within date range
    
    Args:
        pp: PaymentPlan instance
        
    Returns:
        Status code string (DRAFT|PENDING|ACTIVE|CANCELLED|FINISHED)
    """
    from datetime import date as _date
    from hankosign.utils import state_snapshot, has_sig
    
    # Get the current workflow state from HankoSign
    st = state_snapshot(pp)
    
    # 1. Check for rejection (terminal state)
    if st["rejected"]:  # Any REJECT signature exists
        return "CANCELLED"
    
    # 2. Check if submitted
    if not st["submitted"]:  # No SUBMIT or it was WITHDRAWN
        return "DRAFT"
    
    # 3. Check for required approvals
    # We need: APPROVE:WIREF and APPROVE:CHAIR
    approved = st.get("approved", set())
    
    if "WIREF" not in approved:
        return "PENDING"  # Still waiting for WiRef approval
    
    if "CHAIR" not in approved:
        return "PENDING"  # Still waiting for Chair approval
    
    # 4. Check for banking verification
    has_verify = has_sig(pp, "VERIFY", "WIREF")
    if not has_verify:
        return "PENDING"  # Still waiting for banking setup
    
    # 5. At this point: submitted + all approvals + verified
    #    Now check if we're past the end date
    _, end = pp.resolved_window()
    today = _date.today()
    
    if today > end:
        return "FINISHED"  # Naturally ended
    
    # 6. Everything done and still in date range
    return "ACTIVE"

# --- model -----------------------------------------------------------------

class FiscalYear(models.Model):
    code = models.CharField(
        _("Code"),
        max_length=12,
        unique=True,
        blank=True,
        help_text=_("Stored as WJyy_yy (e.g. WJ24_25). English UI shows FYyy_yy."),
    )
    label = models.CharField(_("Label"), max_length=80, blank=True)

    start = models.DateField(_("Start date"), default=default_start)
    end   = models.DateField(
        _("End date"),
        blank=True,
        null=True,
        help_text=_("Leave blank to auto-fill (1 year − 1 day)."),
    )

    is_active = models.BooleanField(_("Active"), default=False)

    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-start"]
        verbose_name = _("Fiscal year")
        verbose_name_plural = _("Fiscal years")
        indexes = [
            models.Index(fields=["start"], name="idx_fy_start"),
            models.Index(fields=["code"], name="idx_fy_code"),
        ]
        constraints = [
            # DB-level sanity: end must be after start
            models.CheckConstraint(
                check=models.Q(end__gt=models.F("start")),
                name="ck_fy_dates_order",
            ),
            # Don’t allow duplicate spans
            models.UniqueConstraint(
                fields=["start", "end"],
                name="uq_fy_span",
            ),
            # Don't allow more than one active FY
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="uq_fy_single_active_true",
            )
        ]

    # display helpers
    def display_code(self) -> str:
        e = self.end or auto_end_from_start(self.start)
        return localized_code(self.start, e)
    display_code.short_description = _("Code")

    def __str__(self) -> str:
        return self.display_code()

    def clean(self):
        errors = {}

        # If this row already exists and is locked, block changes to key fields
        if self.pk:
            try:
                original = FiscalYear.objects.get(pk=self.pk)
            except FiscalYear.DoesNotExist:
                original = None
            if original:
                from hankosign.utils import state_snapshot
                st = state_snapshot(original)
                if st.get("explicit_locked"):
                    protected = ("start", "end", "label", "code", "is_active")
                    changed = [f for f in protected if getattr(self, f) != getattr(original, f)]
                    if changed:
                        errors["__all__"] = _(
                            "This fiscal year is locked. You cannot change: %(fields)s."
                        ) % {"fields": ", ".join(changed)}

        # Normal validations / autofill
        if not self.start:
            errors["start"] = _("Start is required.")
        if not errors:
            if not self.end:
                self.end = auto_end_from_start(self.start)
            if self.end <= self.start:
                errors["end"] = _("End must be after start.")

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Ensure end/code even if form didn't call full_clean()
        if self.start and not self.end:
            self.end = auto_end_from_start(self.start)
        if self.start and self.end and (not self.code or not self.code.startswith("WJ")):
            self.code = stored_code_from_dates(self.start, self.end)
        super().save(*args, **kwargs)

import calendar
from decimal import Decimal, ROUND_HALF_UP
from django.core.validators import RegexValidator
from people.models import PersonRole

class PaymentPlan(models.Model):
    class Status(models.TextChoices):
        DRAFT     = "DRAFT", _("Draft")
        ACTIVE    = "ACTIVE", _("Active")
        FINISHED  = "FINISHED", _("Finished")
        CANCELLED = "CANCELLED", _("Cancelled")

    IBAN_SHAPE = r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$"
    BIC_SHAPE  = r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$"
    CC_SHAPE = r"^\d{3}$"

    # Ownership / scope
    person_role  = models.ForeignKey(PersonRole, on_delete=models.PROTECT, related_name="payment_plans", verbose_name=_("Assignment"))
    fiscal_year  = models.ForeignKey(FiscalYear, on_delete=models.PROTECT, related_name="payment_plans", verbose_name=_("Fiscal year"))

    # per-FY human reference code (auto)
    plan_code = models.CharField(_("Plan code"), max_length=24, unique=True, blank=True, help_text=_("Auto-generated reference (e.g. WJ24_25-00001)."))

    # cost center (3 digit number)
    cost_center  = models.CharField(_("Cost center"), max_length=3, blank=True, null=True, validators=[RegexValidator(CC_SHAPE, _("Enter a valid 3-digit cost center (KSt)"))], help_text=_("Cost center for the payment plan's personnel cost."))

    # Banking + payee
    payee_name   = models.CharField(_("Payee name"), max_length=200, blank=True)
    iban         = models.CharField(_("IBAN"), max_length=34, blank=True, validators=[RegexValidator(IBAN_SHAPE, _("Enter a valid IBAN (e.g. AT.., DE..)."))], help_text=_("Will only accept IBANs in correct format."))
    bic          = models.CharField(_("BIC/SWIFT"), max_length=11, blank=True, validators=[RegexValidator(BIC_SHAPE, _("Enter a valid BIC (8 or 11 chars)."))], help_text=_("Will only accept BIC/SWIFT in correct format."))
    reference    = models.CharField(_("Payment reference"), max_length=140, blank=True, help_text=_("For wire transfer."))
    address      = models.CharField(_("Payee address"), max_length=225, blank=True, help_text=_("Format: Street, No., Post code, City."))

    # Window (optional overrides; otherwise we derive defaults from PR ∩ FY)
    pay_start    = models.DateField(_("Pay start (optional)"), blank=True, null=True)
    pay_end      = models.DateField(_("Pay end (optional)"), blank=True, null=True)

    # Money
    monthly_amount = models.DecimalField(_("Monthly amount"), max_digits=10, decimal_places=2, help_text=_("Monthly amount derived from assigned role. Can be edited."))
    total_override = models.DecimalField(_("Total amount (plan)"), max_digits=10, decimal_places=2, blank=True, null=True, help_text=_("Total amount derived from auto-calculation ['richtwert']. Can be edited."))

    # Status + lightweight audit
    status       = models.CharField(_("Status"), max_length=10, choices=Status.choices, default=Status.DRAFT, help_text=_("Status of payment plan. Payment plans can only be fully edited if they are in the DRAFT stage."))
    status_note  = models.CharField(_("Status note (short)"), max_length=200, blank=True, help_text=_("Short note describing the current status. Optional."))
    notes        = models.TextField(_("Notes (internal)"), blank=True, help_text=_("Longer notes for internal use (e.g. 'Buchungsvermerke'). Optional."))

    # Non-Hankosign 'Signature' (dates are enough for now)
    signed_person_at = models.DateField(_("Signed by payee on"), blank=True, null=True, help_text=_("Date of signature received."))
    
    # Future media hook (nullable until the media container lands)
    pdf_file     = models.FileField(_("Signed PDF (optional)"), upload_to="payment_plans/%Y/%m/", blank=True, null=True, help_text=_("Upload for the signed payment plan PDFs. Note: Simply re-upload after each signature."))

    # Timestamps
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Payment plan")
        verbose_name_plural = _("Payment plans")
        ordering = ("-created_at",)
        constraints = [
            # ONE non-final plan per (assignment, FY). 'Final' = CANCELLED or FINISHED.
            models.UniqueConstraint(
                fields=["person_role", "fiscal_year"],
                condition=~models.Q(status__in=["CANCELLED", "FINISHED"]),
                name="uq_payment_plan_unique_per_pair_open",
            ),
            # Only one ACTIVE per (person_role, fiscal_year)
            models.UniqueConstraint(
                fields=["person_role", "fiscal_year"],
                condition=models.Q(status="ACTIVE"),
                name="uq_payment_plan_single_active_per_pair",
            ),
            # Coherent dates when both overrides are present
            models.CheckConstraint(
                check=models.Q(pay_end__isnull=True) | models.Q(pay_start__isnull=True) | models.Q(pay_end__gte=models.F("pay_start")),
                name="ck_payment_plan_start_before_end",
            ),
            # plan code cannot be empty
            models.CheckConstraint(
            check=~models.Q(plan_code=""),
            name="ck_paymentplan_plan_code_nonempty",
            ),
        ]
        indexes = [
            models.Index(fields=["fiscal_year"]),
            models.Index(fields=["person_role"]),
            models.Index(fields=["status"]),
            models.Index(fields=["plan_code"]),
        ]

    # ---------- Display ----------
    def __str__(self) -> str:
        code = self.plan_code or "—"
        return f"[{code}] {self.person_role} — {self.fiscal_year.display_code()}"

    # ---------- Resolvers & helpers ----------

    @staticmethod
    def _normalize_end_inclusive(end: date | None) -> date | None:
        """
        Treat an end date on the 1st as 'previous day' so month spans are natural:
        e.g. Apr 1 → May 1  == Apr 1 → Apr 30.
        """
        if end and end.day == 1:
            return end - timedelta(days=1)
        return end

    @property
    def iban_masked(self):
        return mask_iban(self.iban, head=6, tail=4)

    @property
    def resolved_payee_name(self) -> str:
        name = (self.payee_name or "").strip()
        if name:
            return name
        p = self.person_role.person
        return f"{p.first_name} {p.last_name}".strip()

    def _default_window_from_pr_and_fy(self) -> tuple[date, date]:
        """
        Default pay window = (PR.effective_start|start) .. (PR.effective_end|end) ∩ FY bounds.
        We clamp hard to FY here.
        """
        pr = self.person_role
        start = pr.effective_start or pr.start_date
        end   = pr.effective_end or pr.end_date or self.fiscal_year.end  # if open-ended, assume FY end
        # Fall back defensively if PR dates are missing
        if not start:
            start = self.fiscal_year.start
        if not end:
            end = self.fiscal_year.end
        # Clamp to FY
        start = max(start, self.fiscal_year.start)
        end   = min(end,   self.fiscal_year.end)
        return (start, end)

    def resolved_window(self) -> tuple[date, date]:
        """
        Final window the plan intends to cover (clamped to FY).
        If overrides are provided, use them; otherwise use PR∩FY defaults.
        """
        d_start, d_end = self._default_window_from_pr_and_fy()
        start = self.pay_start or d_start
        end   = self.pay_end   or d_end
        end = self._normalize_end_inclusive(end)
        # Clamp to FY bounds as a hard business rule
        start = max(start, self.fiscal_year.start)
        end   = min(end,   self.fiscal_year.end)
        return (start, end)

    def months_breakdown(self) -> list[dict]:
        """
        Returns a breakdown per month with simple daily proration against 30-day months.
        
        Delegates to pure function for easier testing.
        """
        start, end = self.resolved_window()
        return calculate_proration_breakdown(start, end)

    def recommended_total(self) -> Decimal:
        """
        “Richtwert”: monthly_amount * sum(proration fractions).
        Rounded half-up to cents.
        """
        if self.monthly_amount is None:
            return Decimal("0.00")
        total = sum((row["fraction"] * self.monthly_amount for row in self.months_breakdown()), Decimal("0"))
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def effective_total(self) -> Decimal:
        """What we will actually present/export as total."""
        return (self.total_override if self.total_override is not None else self.recommended_total())

    @staticmethod
    def _short_person_name(full: str) -> str:
        """
        'Sven Varszegi' -> 'S. Varszegi'
        'Sven P. Varszegi' -> 'S. Varszegi'
        Single token -> initials only: 'S.'
        """
        parts = [p for p in (full or "").split() if p]
        if not parts:
            return ""
        if len(parts) == 1:
            return f"{parts[0][0]}."
        first_initial = parts[0][0]
        last = parts[-1]
        return f"{first_initial}. {last}"

    @staticmethod
    def _initials(full: str) -> str:
        """'Sven Zoltan Varszegi' -> 'SZV'"""
        return "".join(p[0] for p in (full or "").split() if p)

    @staticmethod
    def _join_nonempty(*chunks: str, sep: str = " - ") -> str:
        return sep.join([c for c in chunks if c])

    @property
    def bank_reference_long(self) -> str:
        """
        Full template: {reference} - {payee_name} - {cost_center}
        (omit empty chunks)
        """
        name = self.resolved_payee_name
        return self._join_nonempty(
            (self.reference or "").strip(),
            name,
            (self.cost_center or "").strip(),
        )

    def bank_reference_short(self, limit: int = 140) -> str:
        """
        ≤ limit chars. Prefer 'S. Lastname' for name; if still too long, fall back to initials.
        Finally, truncate the reference part to fit.
        """
        ref = (self.reference or "").strip()
        kst = (self.cost_center or "").strip()
        name_full = self.resolved_payee_name
        name_short = self._short_person_name(name_full) or name_full
        name_init = self._initials(name_full)

        # try with short name
        s = self._join_nonempty(ref, name_short, kst)
        if len(s) <= limit:
            return s

        # try with initials
        s = self._join_nonempty(ref, name_init, kst)
        if len(s) <= limit:
            return s

        # last resort: truncate the reference part to fit
        tail = self._join_nonempty(name_init, kst)
        sep = " - " if tail else ""
        avail = max(0, limit - len(sep) - len(tail))
        ref_cut = (ref[:avail]).rstrip()
        return ref_cut + (sep + tail if tail else "")

    # ---------- Validation ----------

    def clean(self):
        errors = {}

        # Prevent FY changes after creation (keeps plan_code stable)
        if self.pk:
            orig = PaymentPlan.objects.only("fiscal_year_id").get(pk=self.pk)
            if orig.fiscal_year_id != self.fiscal_year_id:
                errors["fiscal_year"] = _("You cannot change the fiscal year after creation.")

        # Ensure FY present (protect against weird admin states)
        if not self.fiscal_year_id:
            errors["fiscal_year"] = _("Fiscal year is required.")

        # Ensure window intersects FY and is coherent
        if self.fiscal_year_id:
            fy = self.fiscal_year
            # If overrides are provided, ensure they at least overlap FY
            if self.pay_start and (self.pay_start > fy.end):
                errors["pay_start"] = _("Pay start must be within or before the fiscal year end.")
            if self.pay_end and (self.pay_end < fy.start):
                errors["pay_end"] = _("Pay end must be within or after the fiscal year start.")

            start, end = self.resolved_window()
            if start > end:
                errors["pay_start"] = _("Computed pay window is empty or inverted. Adjust start/end.")

        # Basic money sanity
        if self.monthly_amount is None or self.monthly_amount < Decimal("0.00"):
            errors["monthly_amount"] = _("Monthly amount must be a non-negative number.")

        if self.iban:
            if not _iban_checksum_ok(self.iban.replace(" ", "").upper()):
                errors["iban"] = _("IBAN checksum failed.")

        if self.fiscal_year_id and self.person_role_id:
            pr = self.person_role
            fy = self.fiscal_year
            pr_start = pr.effective_start or pr.start_date
            pr_end   = pr.effective_end   or pr.end_date
            # treat missing dates as open
            if pr_start and pr_start > fy.end or pr_end and pr_end < fy.start:
                errors["person_role"] = _("Selected assignment does not overlap the fiscal year.")

        if self.status != self.Status.DRAFT:
            required_errors = {}
            if not (self.payee_name or "").strip():
                required_errors["payee_name"] = _("Required when leaving Draft.")
            if not (self.address or "").strip():
                required_errors["address"] = _("Required when leaving Draft.")
            if not (self.reference or "").strip():
                required_errors["reference"] = _("Required when leaving Draft.")
            if not (self.cost_center or "").strip():
                required_errors["cost_center"] = _("Required when leaving Draft.")
            # monthly_amount already validated non-negative; ensure present:
            if self.monthly_amount is None:
                required_errors["monthly_amount"] = _("Required when leaving Draft.")
            # IBAN/BIC presence (shape already validated via validators/ checksum)
            if not (self.iban or "").strip():
                required_errors["iban"] = _("Required when leaving Draft.")
            if not (self.bic or "").strip():
                required_errors["bic"] = _("Required when leaving Draft.")

            if required_errors:
                errors.update(required_errors)

        if errors:
            raise ValidationError(errors)

    # ---------- State helpers ----------

    def mark_active(self, note: str | None = None):
        self.status = self.Status.ACTIVE
        if note:
            self.status_note = note
        self.save(update_fields=["status", "status_note", "updated_at"])

    def mark_finished(self, note: str | None = None):
        self.status = self.Status.FINISHED
        if note:
            self.status_note = note
        self.save(update_fields=["status", "status_note", "updated_at"])

    def mark_cancelled(self, note: str | None = None):
        self.status = self.Status.CANCELLED
        if note:
            self.status_note = note
        self.save(update_fields=["status", "status_note", "updated_at"])

    # ---------- Code generation ----------
    def _generate_plan_code(self) -> str:
        """
        Next per-FY serial: WJyy_yy-00001, WJyy_yy-00002, ...
        Row-lock the FY to serialize concurrent creates for the same year.
        """
        if not self.fiscal_year_id:
            raise ValidationError({"fiscal_year": _("Fiscal year is required before code generation.")})
        prefix = f"{self.fiscal_year.code}-"  # e.g. 'WJ24_25-'
        with transaction.atomic():
            FiscalYear.objects.select_for_update().get(pk=self.fiscal_year_id)
            existing = PaymentPlan.objects.filter(
                fiscal_year_id=self.fiscal_year_id,
                plan_code__startswith=prefix
            ).values_list("plan_code", flat=True)
            max_num = 0
            for c in existing:
                m = re.match(rf"^{re.escape(prefix)}(\d+)$", c or "")
                if m:
                    max_num = max(max_num, int(m.group(1)))
            return f"{prefix}{max_num + 1:05d}"
        
    # ---------- Save hook ----------
    def save(self, *args, **kwargs):
        # Assign plan_code once, on create
        if not self.pk and not self.plan_code:
            if not self.fiscal_year_id:
                raise ValidationError({"fiscal_year": _("Fiscal year is required.")})
            self.plan_code = self._generate_plan_code()
        super().save(*args, **kwargs)


def _iban_checksum_ok(iban: str) -> bool:
    """Mod-97 per ISO 13616."""
    if not iban or len(iban) < 4:
        return False
    s = (iban[4:] + iban[:4]).upper()
    # convert letters to numbers (A=10 ... Z=35)
    digits = "".join(str(ord(c) - 55) if "A" <= c <= "Z" else c for c in s)
    # mod 97 in chunks to avoid huge ints
    rem = 0
    for ch in digits:
        rem = (rem * 10 + int(ch)) % 97
    return rem == 1
