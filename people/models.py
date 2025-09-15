# people/models.py
import uuid
from django.conf import settings
from django.db import models
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords
from django.core.exceptions import ValidationError

class Person(models.Model):
    class Gender(models.TextChoices):
        M = "M", _("Male")
        F = "F", _("Female")
        D = "D", _("Diverse")
        X = "X", _("Not specified")

    # --- Identity ------------------------------------------------------------
    uuid = models.UUIDField(
        _("UUID"),
        default=uuid.uuid4,
        editable=False,
        unique=True,
        help_text=_("Stable system identifier."),
    )
    first_name = models.CharField(_("First name"), max_length=80)
    last_name  = models.CharField(_("Last name"),  max_length=80)

    email         = models.EmailField(_("Email"), blank=True)
    student_email = models.EmailField(_("Student email"), blank=True)

    # FH-style ("s" + 10 digits) OR federal up to 10 digits
    matric_no = models.CharField(
        _("Matriculation number"),
        max_length=12,  # covers 's' + 10 digits safely
        blank=True,
        null=True,
        validators=[
            RegexValidator(
                regex=r"^([sS]\d{9,10}|\d{1,10})$",
                message=_("Use 's' + 10 digits (FH) or up to 10 digits (federal)."),
            )
        ],
        help_text=_("Example FH: s2210562023 — federal: 52103904"),
    )

    gender = models.CharField(
        _("Gender"),
        max_length=1,
        choices=Gender.choices,
        default=Gender.X,
    )

    notes = models.TextField(_("Notes"), blank=True)

    # Link to Django account (optional)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="person",
        verbose_name=_("Account"),
        help_text=_("Link to a Django user account (optional)."),
    )

    # --- Lifecycle / flags ---------------------------------------------------
    is_active   = models.BooleanField(_("Active"), default=True)
    archived_at = models.DateTimeField(_("Archived at"), null=True, blank=True)

    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["last_name", "first_name"]
        verbose_name = _("Person")
        verbose_name_plural = _("People")
        indexes = [
            models.Index(fields=["last_name", "first_name"]),
            models.Index(fields=["matric_no"]),
        ]
        # Only enforce uniqueness when a value is present
        constraints = [
            models.UniqueConstraint(
                fields=["matric_no"],
                name="uq_person_matric_no",
                condition=models.Q(matric_no__isnull=False),
            ),
        ]

    def __str__(self):
        return f"{self.last_name}, {self.first_name}"

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    @property
    def is_effectively_active(self) -> bool:
        """Useful flag for filters: active and not archived."""
        return self.is_active and not self.is_archived


class Role(models.Model):
    class Kind(models.TextChoices):
        DEPT_HEAD = "DEPT. HEAD", _("Department head (Referent:in)")
        DEPT_CLERK = "DEPT. CLERK", _("Department clerk (Sachbearbeiter:in)")
        OTHER = "OTHER", _("Other / miscellaneous")

    name = models.CharField(_("Name"), max_length=100, unique=True)
    ects_cap = models.DecimalField(_("ECTS cap"), max_digits=4, decimal_places=1, default=0, help_text=_("The nominal reimbursible ECTS amount assigned to the role re: MOU with the academic board"))
    is_elected = models.BooleanField(_("Elected position"), default=False, help_text=_("Whether this role is elected via an election authority re: HSG 2014"))
    kind = models.CharField(_("Role type"), max_length=16, choices=Kind.choices, default=Kind.OTHER, db_index=True, help_text=_("Type of role within the (legal) personnel structure."))
    notes = models.TextField(_("Notes"), blank=True)
    is_stipend_reimbursed = models.BooleanField(_("Reimbursed via stipend"), default=False, help_text=_("Whether this role is ordinarily reimbursed via stipend [FuGeb]"))

    default_monthly_amount = models.DecimalField(_("Default monthly stipend"), max_digits=10, decimal_places=2, blank=True, null=True, help_text=_("default monthly pay (if eligible) per Statutes"))

    history = HistoricalRecords()

    class Meta:
        ordering = ["name"]
        verbose_name = _("Role")
        verbose_name_plural = _("Roles")

    def __str__(self):
        return self.name

class RoleTransitionReason(models.Model):
    """
    Dictionary of reasons for starting/ending/changing an assignment.
    Codes are R_00 ... R_99.
    """
    code = models.CharField(
        _("Code"),
        max_length=4,                 # e.g. R_00
        unique=True,
        blank=True,                   # allow blank on create → we auto-generate
        validators=[RegexValidator(
            regex=r"^R_\d{2}$",
            message=_("Code must look like R_00 … R_99."),
        )],
        help_text=_("Leave empty to auto-generate the next free code (R_00…R_99)."),
    )
    name = models.CharField(_("Name"), max_length=120)   # e.g. "Eintritt"
    active = models.BooleanField(_("Active"), default=True)

    class Meta:
        ordering = ["code"]  # zero-padded → lexicographic == numeric
        verbose_name = _("Reason")
        verbose_name_plural = _("Reasons")

    def __str__(self):
        return f"{self.code or '—'} — {self.name}"

    # ---------- helpers ----------
    @staticmethod
    def _existing_codes_set():
        return set(RoleTransitionReason.objects.values_list("code", flat=True))

    @staticmethod
    def _format_code(n: int) -> str:
        return f"R_{n:02d}"

    @classmethod
    def next_free_code(cls) -> str:
        used = cls._existing_codes_set()
        for n in range(100):                  # R_00 … R_99
            c = cls._format_code(n)
            if c not in used:
                return c
        raise ValidationError(_("You have reached the maximum of 100 reasons (R_00…R_99)."))

    # ---------- validations ----------
    def clean(self):
        super().clean()
        # If user typed a code on CREATE (no pk yet), check contiguity
        if not self.pk and self.code:
            # normalize uppercase
            self.code = self.code.upper()
            if not RegexValidator.regex.pattern if False else None:  # (no-op, keeps IDE quiet)
                pass
            # we already have RegexValidator on the field, but guard parse:
            try:
                n = int(self.code.split("_")[1])
            except Exception as exc:
                raise ValidationError({"code": _("Invalid code format.")}) from exc

            # contiguity: all lower numbers must exist
            existing = self._existing_codes_set()
            missing = [self._format_code(i) for i in range(n) if self._format_code(i) not in existing]
            if missing:
                raise ValidationError({
                    "code": _("Cannot create %(code)s because missing previous codes: %(missing)s") % {
                        "code": self.code,
                        "missing": ", ".join(missing),
                    }
                })

    def save(self, *args, **kwargs):
        # Auto-generate code if blank
        if not self.code:
            self.code = self.next_free_code()
        else:
            self.code = self.code.upper()
        super().save(*args, **kwargs)



class PersonRole(models.Model):
    person = models.ForeignKey(
        Person, on_delete=models.PROTECT, related_name="role_assignments", verbose_name=_("Person")
    )
    role = models.ForeignKey(
        Role,   on_delete=models.PROTECT, related_name="assignments",       verbose_name=_("Role")
    )

    # Core dates
    start_date = models.DateField(_("Start date"))
    end_date   = models.DateField(_("End date"), null=True, blank=True)

    # “Official”/effective dates (optional)
    effective_start = models.DateField(_("Effective start"), null=True, blank=True)
    effective_end   = models.DateField(_("Effective end"),   null=True, blank=True)

    # reasons per boundary
    start_reason = models.ForeignKey(
        RoleTransitionReason, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="assignments_started", verbose_name=_("Start reason"),
        help_text=_("Why this assignment started (e.g. Eintritt)."),
    )
    end_reason = models.ForeignKey(
        RoleTransitionReason, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="assignments_ended", verbose_name=_("End reason"),
        help_text=_("Why this assignment ended (e.g. Austritt). Required when an end date is set."),
    )
    
    confirm_date = models.DateField(_("Confirmation date"), null=True, blank=True, help_text=_("Date of assembly confirmation (if applicable)"))
    confirm_ref = models.CharField(_("Confirmation reference"), max_length=120, null=True, blank=True, help_text=_("Assembly reference or note (if applicable)"))

    # Per-assignment free-text note
    notes = models.TextField(_("Notes"), blank=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-start_date", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["person", "role", "start_date"], name="uq_person_role_start"),

            # end_date must be after start_date (if present)
            models.CheckConstraint(
                check=models.Q(end_date__gte=models.F("start_date")) | models.Q(end_date__isnull=True),
                name="ck_assignment_dates",
            ),

            # effective dates sanity
            models.CheckConstraint(
                check=models.Q(effective_start__gte=models.F("start_date")) | models.Q(effective_start__isnull=True),
                name="ck_effective_after_start",
            ),
            models.CheckConstraint(
                check=(models.Q(effective_end__gte=models.F("effective_start")) |
                       models.Q(effective_end__isnull=True) |
                       models.Q(effective_start__isnull=True)),
                name="ck_effective_order",
            ),

            # NEW: (end_date is NULL) <=> (end_reason is NULL)
            models.CheckConstraint(
                check=(models.Q(end_date__isnull=True, end_reason__isnull=True) |
                       models.Q(end_date__isnull=False, end_reason__isnull=False)),
                name="ck_end_reason_iff_end_date",
            ),
            # NEW: start_reason != end_reason when both set
            models.CheckConstraint(
                check=(models.Q(start_reason__isnull=True) |
                       models.Q(end_reason__isnull=True) |
                       ~models.Q(start_reason_id=models.F("end_reason_id"))),
                name="ck_reasons_not_equal",
            ),
            models.CheckConstraint(
                check=models.Q(confirm_date__isnull=True) | models.Q(confirm_date__gte=models.F("start_date")),
                name="ck_confirm_after_start",
            )
        ]
        verbose_name = _("Assignment")
        verbose_name_plural = _("Assignments")

    def __str__(self):
        to = self.end_date.isoformat() if self.end_date else "…"
        return f"{self.person} — {self.role} ({self.start_date} → {to})"

    @property
    def is_active(self) -> bool:
        return self.end_date is None

    # Optional server-side form validation niceties (admin will show nicer errors)
    def clean(self):
        super().clean()
        errors = {}

        if self.end_date and not self.end_reason:
            errors["end_reason"] = _("End reason is required when an end date is set.")
        if not self.end_date and self.end_reason:
            errors["end_reason"] = _("Remove end reason unless you set an end date.")
        if self.start_reason_id and self.end_reason_id and self.start_reason_id == self.end_reason_id:
            errors["end_reason"] = _("Start and end reason cannot be the same.")
        if self.confirm_ref and not self.confirm_date:
            errors["confirm_date"] = _("Provide a confirmation date when adding a reference.")
        if errors:
            from django.core.exceptions import ValidationError
            raise ValidationError(errors)