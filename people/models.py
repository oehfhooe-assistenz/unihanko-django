# people/models.py
import uuid
import secrets
from django.conf import settings
from django.db import models
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords
from django.core.exceptions import ValidationError
from concurrency.fields import AutoIncVersionField
import re
from django.utils import timezone


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

    # public filing access
    personal_access_code = models.CharField(
        _("Personal access code"),
        max_length=19,
        unique=True,
        blank=True,
        help_text=_("To be shared with personnel for certain public filing systems (FuGeb etc.)."),
    )

    # --- Lifecycle / flags ---------------------------------------------------
    is_active   = models.BooleanField(_("Active"), default=True)

    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    history = HistoricalRecords()
    version = AutoIncVersionField()

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

    
    # Access code helpers
    _ACCESS_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    @classmethod
    def _generate_access_code(cls, groups: int = 2, chars_per_group: int = 4) -> str:
        """
        Example default: 'ABCD-EFGH' (8 chars + hyphen). Human-friendly, mixed alphanum.
        """
        rng = secrets.SystemRandom()
        parts = [
            "".join(rng.choice(cls._ACCESS_ALPHABET) for _ in range(chars_per_group))
            for __ in range(groups)
        ]
        return "-".join(parts)
    
    @classmethod
    def _generate_unique_access_code(cls) -> str:
        # Try a few times, extremely low collision probability
        for attempt in range(20):
            code = cls._generate_access_code()
            if not cls.objects.filter(personal_access_code=code).exists():
                return code
        # Fallback: longer code if we somehow collide often
        for attempt in range(20):
            code = cls._generate_access_code(groups=3, chars_per_group=4) # ABCD-EFGH-IJKL
            if not cls.objects.filter(personal_access_code=code).exists():
                return code
        # If we still fail, raise a clear error
        raise ValidationError(_("Could not generate a unique access code. Please try again."))
    
    def regenerate_access_code(self, *, commit: bool = True) -> str:
        """
        Regenerate to a new unique code. Returns the new code.
        """
        self.personal_access_code = self._generate_unique_access_code()
        if commit:
            self.save(update_fields=["personal_access_code", "updated_at"])
        return self.personal_access_code
    
    def save(self, *args, **kwargs):
        # Auto-assign a code on create (or if missing from legacy rows)
        if not self.personal_access_code:
            self.personal_access_code = self._generate_unique_access_code()
        super().save(*args, **kwargs)

class Role(models.Model):
    class Kind(models.TextChoices):
        DEPT_HEAD = "DEPT. HEAD", _("Department head (Referent:in)")
        DEPT_CLERK = "DEPT. CLERK", _("Department clerk (Sachbearbeiter:in)")
        OTHER = "OTHER", _("Other / miscellaneous")

    name = models.CharField(_("Name"), max_length=100, unique=True)
    short_name = models.CharField(
        _("Short form"),
        max_length=20,
        blank=True,
        validators=[RegexValidator(
            regex=r"^\D{1,20}$",
            message=_("Format: no digits, max. 20 characters, e.g. WiRef"),
        )],
        help_text=_("Role short-form"),
    )
    ects_cap = models.DecimalField(_("ECTS cap"), max_digits=4, decimal_places=1, default=0, help_text=_("The nominal reimbursible ECTS amount assigned to the role re: MOU with the academic board"))
    is_elected = models.BooleanField(_("Elected position"), default=False, help_text=_("Whether this role is elected via an election authority re: HSG 2014"))
    kind = models.CharField(_("Role type"), max_length=16, choices=Kind.choices, default=Kind.OTHER, db_index=True, help_text=_("Type of role within the (legal) personnel structure."))
    notes = models.TextField(_("Notes"), blank=True)
    is_stipend_reimbursed = models.BooleanField(_("Reimbursed via stipend"), default=False, help_text=_("Whether this role is ordinarily reimbursed via stipend [FuGeb]"))
    is_system = models.BooleanField(_("System role"), default=False, help_text=_("Internal/admin role. Ignores stipend/ECTS expectations and is treated separately in policies."))
    default_monthly_amount = models.DecimalField(_("Default monthly stipend"), max_digits=10, decimal_places=2, blank=True, null=True, help_text=_("default monthly pay (if eligible) per Statutes"))

    history = HistoricalRecords()
    version = AutoIncVersionField()

    class Meta:
        ordering = ["name"]
        verbose_name = _("Role")
        verbose_name_plural = _("Roles")
        constraints = [
            models.CheckConstraint(
                name="ck_system_kind_other",
                check=~models.Q(is_system=True) | models.Q(kind="OTHER"),
            )
        ]


    @property
    def kind_label(self) -> str:
        # Show “Other/System” when OTHER + system
        if self.kind == self.Kind.OTHER and self.is_system:
            return _("Other/System")
        return self.get_kind_display()


    # Optional: a handy predicate for money logic
    @property
    def is_financially_relevant(self) -> bool:
        return bool(self.is_stipend_reimbursed and not self.is_system)


    def __str__(self):
        return self.name


    def clean(self):
        super().clean()
        errors = {}

        if self.is_system and self.kind != self.Kind.OTHER:
            errors.setdefault("kind", []).append(_("System roles must use “Other” kind."))

        # Optional “relax expectations” hard stops:
        if self.is_system:
            if self.is_stipend_reimbursed:
                errors.setdefault("is_stipend_reimbursed", []).append(_("System roles cannot be stipend-reimbursed."))
            if self.default_monthly_amount:
                errors.setdefault("default_monthly_amount", []).append(_("Leave default monthly amount empty for system roles."))
            if self.ects_cap:
                errors.setdefault("ects_cap", []).append(_("ECTS cap must be 0 for system roles."))

        if errors:
            raise ValidationError(errors)

class RoleTransitionReason(models.Model):
    """
    Dictionary of reasons for starting/ending/changing an assignment.
    Codes are Ixx, Oxx, Cxx or (distinct) X99
    """
    code = models.CharField(
        _("Code"),
        max_length=4,                    # fits I01, O01, C99
        unique=True,
        help_text=_("Stable code like I01, O01, C99 OR X99 (to be reserved for 'Other')."),
        validators=[RegexValidator(
            regex=r"^(?:[IOC]\d{2}|X99)$",
            flags=re.I,
            message=_("Use I## / O## / C## or X99 for Other."),
        )],
    )
    name = models.CharField(_("Name"), max_length=120, help_text=_("German label/name for the reason given (e.g. Eintritt, Austritt, ...)."))
    name_en = models.CharField(_("Name (EN)"), max_length=120, blank=True, help_text=_("Optional English label/name for the reason given."))  # optional EN
    active = models.BooleanField(_("Active"), default=True)


    class Meta:
        ordering = ["code"]
        verbose_name = _("Reason")
        verbose_name_plural = _("Reasons")



    def __str__(self):
        return f"{self.code} — {self.display_name}"


    @property
    def display_name(self) -> str:
        from django.utils.translation import get_language
        lang = (get_language() or "en").lower()
        if lang.startswith("en"):
            return self.name_en or self.name
        return self.name


    def clean(self):
        super().clean()
        # normalize uppercase, keep simple
        if self.code:
            self.code = self.code.upper()


    def save(self, *args, **kwargs):
        if self.code:
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
    
    CONFIRM_REF_REGEX = r"^(?:HV|AO)-[IVXLCDM]+-\d{4}$"  # HV-<roman>-YYYY or AO-<roman>-YYYY
    confirm_date = models.DateField(
        _("Confirmation date"), 
        null=True, blank=True, 
        help_text=_("Date of assembly confirmation (if applicable)")
    )
    elected_via = models.ForeignKey(
        'assembly.SessionItem',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='elected_persons',
        verbose_name=_("Elected via"),
        help_text=_("Assembly session item that confirmed this appointment")
    )

    # Per-assignment free-text note
    notes = models.TextField(_("Notes"), blank=True)

    history = HistoricalRecords()
    version = AutoIncVersionField()

    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

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
                check=models.Q(confirm_date__isnull=True) | models.Q(confirm_date__gte=models.F("start_date")),
                name="ck_confirm_after_start",
            )
        ]
        indexes = [
            models.Index(fields=["effective_start"]),
            models.Index(fields=["effective_end"]),
            models.Index(fields=["effective_start", "effective_end"]),
            models.Index(fields=["person", "end_date"]),
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
        I_OR_X = re.compile(r'^(?:I\d{2}|X99)$', re.I)
        O_OR_X = re.compile(r'^(?:O\d{2}|X99)$', re.I)
        super().clean()

        errors = {}

        if self.role and getattr(self.role, "is_system", False):
            # System roles shouldn't carry confirmation paperwork
            if self.confirm_date or self.elected_via_id:  # ← Changed
                errors.setdefault("confirm_date", []).append(_("Confirmation isn't used for system roles."))
                errors.setdefault("elected_via", []).append(_("Confirmation isn't used for system roles."))  # ← Changed
                self.confirm_date = None
                self.elected_via = None  # ← Changed

            # Optional: disallow effective_* dates for clarity
            if self.effective_start or self.effective_end:
                errors.setdefault("effective_start", []).append(_("Use start/end only for system roles (no effective dates)."))
                errors.setdefault("effective_end", []).append(_("Use start/end only for system roles (no effective dates)."))

        # --- start_reason format ---
        if self.start_reason:
            sc = (self.start_reason.code or "").upper()
            if not I_OR_X.fullmatch(sc):
                errors.setdefault("start_reason", []).append(_("Pick a start reason (I##) or X99 (Other)."))

        # --- end_reason format ---
        if self.end_reason:
            ec = (self.end_reason.code or "").upper()
            if not O_OR_X.fullmatch(ec):
                errors.setdefault("end_reason", []).append(_("Pick an end reason (O##) or X99 (Other)."))

        # --- coupling end_date <-> end_reason ---
        if self.end_date and not self.end_reason:
            errors.setdefault("end_reason", []).append(_("Reason is required when an end date is set."))
        if not self.end_date and self.end_reason:
            errors.setdefault("end_reason", []).append(_("Remove end reason unless you set an end date."))

        # --- start != end (except both X99) ---
        if self.start_reason_id and self.end_reason_id:
            sc = (self.start_reason.code or "").upper()
            ec = (self.end_reason.code or "").upper()
            if sc != "X99" and ec != "X99" and self.start_reason_id == self.end_reason_id:
                errors.setdefault("end_reason", []).append(
                    _("Start and end reason cannot be the same (except X99).")
                )

        # --- elected_via requires date ---
        if self.elected_via_id and not self.confirm_date:  # ← Changed
            errors.setdefault("confirm_date", []).append(_("Provide a confirmation date when using assembly election."))  # ← Changed

        if errors:
            raise ValidationError(errors)