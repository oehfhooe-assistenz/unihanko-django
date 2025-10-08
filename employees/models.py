# employee/models.py
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional, Set

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from simple_history.models import HistoricalRecords

# External app references
from people.models import PersonRole


# ------------------------------
# helpers
# ------------------------------

def minutes_to_hhmm(minutes: int) -> str:
    """Format minutes → 'H:MM' (handles negative)."""
    sign = "-" if minutes < 0 else ""
    m = abs(int(minutes))
    h, mm = divmod(m, 60)
    return f"{sign}{h}:{mm:02d}"


def month_days(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def iter_month_dates(year: int, month: int) -> Iterable[date]:
    for d in range(1, month_days(year, month) + 1):
        yield date(year, month, d)


# Western (Gregorian) Easter calculation (Anonymous Gregorian algorithm)
def easter_date(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


# ------------------------------
# Holiday calendar (optional)
# ------------------------------

class HolidayCalendar(models.Model):
    """
    Rules per line:
      - MM-DD | EN | DE            → fixed every year (e.g. 01-06 | Epiphany | Heilige Drei Könige)
      - EASTER±N | EN | DE         → Easter ± N days (e.g. EASTER+1 | Easter Monday | Ostermontag)
      - YYYY-MM-DD | EN | DE       → one-off

    Labels: if only one label is provided, it’s used for both languages.
            We assume order: English first, German second.
    """
    name = models.CharField(_("Name"), max_length=120, unique=True)
    is_active = models.BooleanField(_("Active"), default=False, help_text=_("Use this calendar by default."))
    rules_text = models.TextField(
        _("Rules"),
        blank=True,
        help_text=_(
            "One per line. Examples:\n"
            "  01-06 | Epiphany | Heilige Drei Könige\n"
            "  EASTER+39 | Ascension Day | Christi Himmelfahrt\n"
            "  2025-05-09 | Bridge Day | Fenstertag\n"
        ),
    )

    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Holiday calendar")
        verbose_name_plural = _("Holiday calendars")
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="uq_holidaycalendar_single_active_true",
            )
        ]

    def __str__(self) -> str:
        return self.name

    # ---- parsing ----
    @dataclass(frozen=True)
    class _Rule:
        kind: str                 # 'FIXED' | 'EASTER' | 'ONEOFF'
        month: int | None
        day: int | None
        offset: int               # for EASTER±N
        date: date | None         # for ONEOFF
        label_en: str
        label_de: str

    def _parse_rules(self) -> list["_Rule"]:
        rules: list[HolidayCalendar._Rule] = []
        for raw in (self.rules_text or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            # Split into up to 3 chunks: key | EN | DE
            parts = [p.strip() for p in line.split("|")]
            key = parts[0] if parts else ""
            if not key:
                continue
            label_en = parts[1].strip() if len(parts) >= 2 else ""
            label_de = parts[2].strip() if len(parts) >= 3 else label_en

            # ONE-OFF: YYYY-MM-DD
            m_one = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", key)
            if m_one:
                y, m, d = map(int, m_one.groups())
                try:
                    dt = date(y, m, d)
                except ValueError:
                    continue
                rules.append(self._Rule("ONEOFF", None, None, 0, dt, label_en, label_de))
                continue

            # FIXED: MM-DD (every year)
            m_fix = re.fullmatch(r"(\d{2})-(\d{2})", key)
            if m_fix:
                m, d = map(int, m_fix.groups())
                if 1 <= m <= 12 and 1 <= d <= 31:
                    rules.append(self._Rule("FIXED", m, d, 0, None, label_en, label_de))
                continue

            # EASTER±N
            m_e = re.fullmatch(r"EASTER([+-]\d+)?", key, flags=re.IGNORECASE)
            if m_e:
                off = int(m_e.group(1) or "0")
                rules.append(self._Rule("EASTER", None, None, off, None, label_en, label_de))
                continue

            # silently ignore malformed lines
        return rules

    def _pick_label(self, rule: "_Rule", lang: str | None = None) -> str:
        code = (lang or get_language() or "en").lower()
        if code.startswith("de"):
            return rule.label_de or rule.label_en
        return rule.label_en or rule.label_de

    # ---- API: dates only (as before) ----
    def holidays_for_year(self, year: int) -> set[date]:
        out: set[date] = set()
        easter = easter_date(year)
        for r in self._parse_rules():
            if r.kind == "FIXED":
                try:
                    out.add(date(year, r.month, r.day))  # type: ignore[arg-type]
                except ValueError:
                    pass
            elif r.kind == "EASTER":
                out.add(easter + timedelta(days=r.offset))
            elif r.kind == "ONEOFF":
                if r.date and r.date.year == year:
                    out.add(r.date)
        return out

    # ---- Optional: with localized labels ----
    def holidays_for_year_labeled(self, year: int, lang: str | None = None) -> dict[date, str]:
        """
        Returns {date: localized_label} for the given year.
        Useful for showing holiday names in UIs/PDFs.
        """
        result: dict[date, str] = {}
        easter = easter_date(year)
        for r in self._parse_rules():
            if r.kind == "FIXED":
                try:
                    dt = date(year, r.month, r.day)  # type: ignore[arg-type]
                except ValueError:
                    continue
            elif r.kind == "EASTER":
                dt = easter + timedelta(days=r.offset)
            else:  # ONEOFF
                if not (r.date and r.date.year == year):
                    continue
                dt = r.date
            result[dt] = self._pick_label(r, lang)
        return result

    @classmethod
    def get_active(cls) -> "HolidayCalendar | None":
        try:
            return cls.objects.get(is_active=True)
        except cls.DoesNotExist:
            return None


# ------------------------------
# Employee (one per PersonRole)
# ------------------------------

class Employee(models.Model):
    """
    Employment container attached to a PersonRole assignment.

    We derive the 'effective' employment window from the linked PersonRole unless
    overridden here via `start_override` / `end_override`.
    """
    person_role = models.OneToOneField(
        PersonRole,
        on_delete=models.PROTECT,
        related_name="employment",
        verbose_name=_("Assignment"),
    )

    weekly_hours = models.DecimalField(
        _("Weekly hours"),
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=_("Nominal weekly working hours (e.g. 10.00)."),
    )

    # Running time-account (minutes). Positive = credit, negative = deficit.
    saldo_minutes = models.IntegerField(
        _("Running balance (minutes)"),
        default=0,
        help_text=_("Time-account balance across months."),
    )

    # Optional overrides for employment window
    start_override = models.DateField(_("Employment start (override)"), null=True, blank=True)
    end_override   = models.DateField(_("Employment end (override)"),   null=True, blank=True)
    is_active = models.BooleanField(_("Active"), default=True)

    notes = models.TextField(_("Notes"), blank=True)

    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Employee")
        verbose_name_plural = _("Employees")
        indexes = [
            models.Index(fields=["person_role"]),
        ]

    def __str__(self) -> str:
        p = self.person_role.person
        return f"{p.last_name}, {p.first_name} — {self.person_role.role.name}"

    # Effective window = overrides or PR window
    @property
    def effective_start(self) -> date:
        pr = self.person_role
        return self.start_override or pr.effective_start or pr.start_date

    @property
    def effective_end(self) -> Optional[date]:
        pr = self.person_role
        return self.end_override or pr.effective_end or pr.end_date

    def clean(self):
        super().clean()
        errors = {}
        if self.end_override and self.start_override and self.end_override < self.start_override:
            errors["end_override"] = _("End must be on/after start.")
        if errors:
            raise ValidationError(errors)

    # minute helpers
    @property
    def weekly_minutes(self) -> int:
        if self.weekly_hours is None:
            return 0
        return int((self.weekly_hours * Decimal(60)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @property
    def daily_expected_minutes(self) -> int:
        # 5-day week assumption
        return int(Decimal(self.weekly_minutes) / Decimal(5))

    def saldo_as_hhmm(self) -> str:
        return minutes_to_hhmm(self.saldo_minutes)


# ------------------------------
# Employment documents (ZV, DV, AA, KM, ZZ)
# ------------------------------

class EmploymentDocument(models.Model):
    class Kind(models.TextChoices):
        ZV = "ZV", _("Supplemental Agreement")
        DV = "DV", _("Contract of Employment")
        AA = "AA", _("Leave Request")
        KM = "KM", _("Sick Note")
        ZZ = "ZZ", _("Other / Miscellaneous")

    employee = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="documents", verbose_name=_("Employee")
    )
    kind = models.CharField(_("Kind"), max_length=2, choices=Kind.choices)

    title = models.CharField(_("Title/Subject"), max_length=160, blank=True)
    details = models.TextField(_("Details / body"), blank=True)

    # Optional date window (e.g. leave/sick span)
    start_date = models.DateField(_("Start"), null=True, blank=True)
    end_date   = models.DateField(_("End"),   null=True, blank=True)

    # Document lifecycle
    is_active = models.BooleanField(_("Active"), default=True)
    pdf_file  = models.FileField(_("PDF file (optional)"), upload_to="employee/docs/%Y/%m/", null=True, blank=True)

    # Read-only internal code (KIND_createdate_person_lastname or fallback to id)
    code = models.CharField(_("Code"), max_length=80, unique=True, blank=True, help_text=_("Auto-generated."))

    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Employee Document")
        verbose_name_plural = _("Document Center")
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                check=models.Q(end_date__isnull=True) | models.Q(start_date__isnull=True) | models.Q(end_date__gte=models.F("start_date")),
                name="ck_empdoc_dates_order",
            ),
            models.CheckConstraint(
                check=~models.Q(code=""),
                name="ck_empdoc_code_nonempty",
            ),
        ]
        indexes = [
            models.Index(fields=["employee"]),
            models.Index(fields=["kind"]),
            models.Index(fields=["code"]),
        ]

    def __str__(self) -> str:
        return f"[{self.code or self.kind}] {self.title or self.get_kind_display()}"

    def _generate_code(self) -> str:
        # KIND_createdate_lastname  (or fallback to id if name missing)
        d = timezone.localdate().strftime("%Y-%m-%d")
        last = slugify(self.employee.person_role.person.last_name) if self.employee_id else ""
        tail = last or f"emp{self.employee_id or 'X'}"
        base = f"{self.kind}_{d}_{tail}".upper()
        # ensure uniqueness by appending -N if necessary
        exists = EmploymentDocument.objects.filter(code__startswith=base).values_list("code", flat=True)
        seq = 0
        taken = set(exists)
        code = base
        while code in taken:
            seq += 1
            code = f"{base}-{seq}"
        return code

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._generate_code()
        super().save(*args, **kwargs)


# ------------------------------
# Timesheets
# ------------------------------

class TimeSheet(models.Model):
    """
    One sheet per employee per (year, month).
    Approval flow:
      - submitted_at set when employee submits
      - approved_at_wiref set by WiRef
      - approved_at_chair set by Chair (after WiRef)

    We snapshot the employee’s saldo at month start in `opening_saldo_minutes`
    and keep computed aggregates for convenience/exports.
    """
    employee = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="timesheets", verbose_name=_("Employee")
    )
    year = models.PositiveIntegerField(_("Year"), validators=[MinValueValidator(2000), MaxValueValidator(9999)])
    month = models.PositiveSmallIntegerField(_("Month"), validators=[MinValueValidator(1), MaxValueValidator(12)])

    # lifecycle
    submitted_at = models.DateTimeField(_("Submitted at"), null=True, blank=True)
    approved_at_wiref = models.DateTimeField(_("Approved by WiRef at"), null=True, blank=True)
    approved_at_chair = models.DateTimeField(_("Approved by Chair at"), null=True, blank=True)

    # snapshot + aggregates (minutes)
    opening_saldo_minutes = models.IntegerField(_("Opening balance (minutes)"), default=0)
    expected_minutes = models.IntegerField(_("Expected minutes"), default=0)
    worked_minutes   = models.IntegerField(_("Worked minutes"), default=0)
    credit_minutes   = models.IntegerField(_("Credit minutes (leave/sick/etc.)"), default=0)
    closing_saldo_minutes = models.IntegerField(_("Closing balance (minutes)"), default=0)

    pdf_file = models.FileField(_("Signed PDF (optional)"), upload_to="employee/timesheets/%Y/%m/", null=True, blank=True)
    export_payload = models.JSONField(_("Export payload (optional)"), null=True, blank=True)

    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    

    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Timesheet")
        verbose_name_plural = _("Timesheets")
        unique_together = (("employee", "year", "month"),)
        ordering = ("-year", "-month", "-id")
        indexes = [
            models.Index(fields=["employee", "year", "month"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(month__gte=1, month__lte=12),
                name="ck_timesheet_month_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.employee} — {self.year}-{self.month:02d}"

    # ---- status flags ----
    @property
    def is_submitted(self) -> bool:
        return self.submitted_at is not None

    @property
    def is_approved_wiref(self) -> bool:
        return self.approved_at_wiref is not None

    @property
    def is_approved_chair(self) -> bool:
        return self.approved_at_chair is not None

    # ---- expectations & aggregates ----
    def _active_holidays(self) -> Set[date]:
        cal = HolidayCalendar.get_active()
        return cal.holidays_for_year(self.year) if cal else set()

    def compute_expected_minutes(self) -> int:
        """Mon–Fri working days minus public holidays * employee.daily_expected_minutes."""
        daily = self.employee.daily_expected_minutes
        if daily <= 0:
            return 0
        hols = self._active_holidays()
        workdays = 0
        for d in iter_month_dates(self.year, self.month):
            if d.weekday() < 5 and d not in hols:  # 0=Mon..4=Fri
                workdays += 1
        return workdays * daily

    def recompute_aggregates(self, commit: bool = False):
        """
        Recalculate expected/worked/credit/closing.
        If commit=True, persist with a direct update (no save()).
        """
        # expected never needs a PK
        self.expected_minutes = self.compute_expected_minutes()

        work = 0
        credit = 0

        # Only iterate entries if we have a PK
        if self.pk:
            for e in self.entries.all():
                if e.kind == TimeEntry.Kind.WORK:
                    work += (e.minutes or 0)
                elif e.kind in (TimeEntry.Kind.LEAVE, TimeEntry.Kind.SICK):
                    credit += (e.minutes or 0)

        self.worked_minutes = work
        self.credit_minutes = credit
        self.closing_saldo_minutes = (
            self.opening_saldo_minutes + work + credit - self.expected_minutes
        )

        if commit and self.pk:
            # persist without calling save() again (avoid recursion)
            TimeSheet.objects.filter(pk=self.pk).update(
                expected_minutes=self.expected_minutes,
                worked_minutes=self.worked_minutes,
                credit_minutes=self.credit_minutes,
                closing_saldo_minutes=self.closing_saldo_minutes,
                updated_at=timezone.now(),
            )

    def clean(self):
        super().clean()
        errors = {}
        if self.approved_at_chair and not self.approved_at_wiref:
            errors["approved_at_chair"] = _("Chair approval requires WiRef approval first.")
        if self.submitted_at and self.submitted_at.tzinfo is None:
            # Normalize the unlikely case someone writes naive datetimes
            self.submitted_at = timezone.make_aware(self.submitted_at, timezone.get_current_timezone())
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        creating = self.pk is None

        # Snapshot opening saldo on first save (if not set)
        if creating and self.opening_saldo_minutes == 0:
            self.opening_saldo_minutes = self.employee.saldo_minutes

        # Compute expected without touching entries yet
        self.expected_minutes = self.compute_expected_minutes()

        # On create, keep worked/credit at 0 and compute closing
        if creating:
            self.worked_minutes = 0
            self.credit_minutes = 0
            self.closing_saldo_minutes = (
                self.opening_saldo_minutes - self.expected_minutes
            )

        # write row to get a PK
        super().save(*args, **kwargs)

        # On updates (PK exists), refresh aggregates from entries
        if not creating:
            self.recompute_aggregates(commit=True)


class TimeEntry(models.Model):
    class Kind(models.TextChoices):
        WORK = "WORK", _("Work")
        LEAVE = "LEAVE", _("Leave (paid)")      # Abwesenheitsantrag days credited
        SICK = "SICK", _("Sick (paid)")         # Krankmeldung days credited
        PUBLIC_HOLIDAY = "PUBHOL", _("Public holiday")
        OTHER = "OTHER", _("Other")

    timesheet = models.ForeignKey(
        TimeSheet, on_delete=models.CASCADE, related_name="entries", verbose_name=_("Timesheet")
    )
    date = models.DateField(_("Date"))
    kind = models.CharField(_("Kind"), max_length=6, choices=Kind.choices, default=Kind.WORK)

    # We store minutes directly (no break tracking). Optional start/end exist for convenience.
    minutes = models.PositiveIntegerField(_("Minutes"), validators=[MinValueValidator(0)], default=0)
    start_time = models.TimeField(_("Start (optional)"), null=True, blank=True)
    end_time   = models.TimeField(_("End (optional)"),   null=True, blank=True)

    comment = models.CharField(_("Comment"), max_length=240, blank=True)

    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Time entry")
        verbose_name_plural = _("Time entries")
        ordering = ("date", "id")
        constraints = [
            models.UniqueConstraint(fields=["timesheet", "date", "kind", "comment"], name="uq_timesheet_date_kind_comment"),
            models.CheckConstraint(
                check=models.Q(minutes__gte=0),
                name="ck_timeentry_minutes_nonneg",
            ),
        ]
        indexes = [
            models.Index(fields=["timesheet", "date"]),
        ]

    def __str__(self) -> str:
        return f"{self.date.isoformat()} — {self.get_kind_display()} ({minutes_to_hhmm(self.minutes)})"

    def clean(self):
        super().clean()
        errors = {}

        # Guard against entries outside the month
        if self.date and (self.date.year != self.timesheet.year or self.date.month != self.timesheet.month):
            errors["date"] = _("Entry date must lie within the sheet’s year and month.")

        # Optional convenience: if start/end present and minutes is zero, derive minutes
        if (self.start_time and self.end_time) and self.minutes == 0:
            dt_start = datetime.combine(self.date, self.start_time)
            dt_end = datetime.combine(self.date, self.end_time)
            if dt_end < dt_start:
                errors["end_time"] = _("End time must be after start time.")
            else:
                delta = int((dt_end - dt_start).total_seconds() // 60)
                if delta >= 0:
                    self.minutes = delta

        # Paid categories typically shouldn't exceed expected daily minutes too wildly
        if self.kind in (self.Kind.LEAVE, self.Kind.SICK) and self.minutes == 0:
            # Soft default: credit expected daily minutes for the employee
            self.minutes = self.timesheet.employee.daily_expected_minutes

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Keep parent aggregates in sync
        self.timesheet.recompute_aggregates(commit=True)
