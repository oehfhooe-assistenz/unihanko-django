from datetime import date, timedelta
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

# --- helpers ---------------------------------------------------------------

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
    is_locked = models.BooleanField(_("Locked"), default=False, help_text=_("Locked years are read-only."))

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
            if original and original.is_locked:
                protected = ("start", "end", "label", "code", "is_active")
                changed = [f for f in protected if getattr(self, f) != getattr(original, f)]
                if changed:
                    errors["is_locked"] = _("This fiscal year is locked. You cannot change: %(fields)s.") % {
                        "fields": ", ".join(changed)
                    }
                # allow toggling is_locked itself; nothing else

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
