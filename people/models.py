# people/models.py
from django.db import models
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords


class Person(models.Model):
    first_name = models.CharField(_("First name"), max_length=80)
    last_name  = models.CharField(_("Last name"), max_length=80)
    email      = models.EmailField(_("Email"), blank=True)

    # Soft archive (no hard deletes policy)
    archived_at = models.DateTimeField(_("Archived at"), null=True, blank=True)

    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["last_name", "first_name"]
        verbose_name = _("Person")
        verbose_name_plural = _("People")

    def __str__(self):
        return f"{self.last_name}, {self.first_name}"

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


class Role(models.Model):
    name = models.CharField(_("Name"), max_length=100, unique=True)
    ects_cap = models.DecimalField(_("ECTS cap"), max_digits=4, decimal_places=1, default=0)
    is_elected = models.BooleanField(_("Elected position"), default=False)
    notes = models.TextField(_("Notes"), blank=True)

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
    Store stable codes (e.g., R_00, R_01) and editable human labels.
    """
    code = models.CharField(_("Code"), max_length=30, unique=True)   # e.g. "R_00"
    name = models.CharField(_("Name"), max_length=120)               # e.g. "Eintritt"
    active = models.BooleanField(_("Active"), default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = _("Reason")
        verbose_name_plural = _("Reasons")

    def __str__(self):
        return f"{self.code} — {self.name}"


class PersonRole(models.Model):
    person = models.ForeignKey(
        Person,
        on_delete=models.PROTECT,
        related_name="role_assignments",
        verbose_name=_("Person"),
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.PROTECT,
        related_name="assignments",
        verbose_name=_("Role"),
    )

    # Core dates
    start_date = models.DateField(_("Start date"))
    end_date   = models.DateField(_("End date"), null=True, blank=True)

    # “Official”/effective dates (optional)
    effective_start = models.DateField(_("Effective start"), null=True, blank=True)
    effective_end   = models.DateField(_("Effective end"),   null=True, blank=True)

    # Why did this (start/end/change) happen?
    reason = models.ForeignKey(
        RoleTransitionReason,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="assignments",
        verbose_name=_("Reason"),
    )

    # Per-assignment free-text note
    notes = models.TextField(_("Notes"), blank=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-start_date", "-id"]
        constraints = [
            # Prevent duplicate starts for same person+role on same day
            models.UniqueConstraint(
                fields=["person", "role", "start_date"],
                name="uq_person_role_start",
            ),
            # End date must be after start date (or be empty)
            models.CheckConstraint(
                check=models.Q(end_date__gte=models.F("start_date")) | models.Q(end_date__isnull=True),
                name="ck_assignment_dates",
            ),
            # (Optional) Effective start should be on/after start
            models.CheckConstraint(
                check=models.Q(effective_start__gte=models.F("start_date")) | models.Q(effective_start__isnull=True),
                name="ck_effective_after_start",
            ),
            # (Optional) Effective end should be after effective start
            models.CheckConstraint(
                check=(
                    models.Q(effective_end__gte=models.F("effective_start")) |
                    models.Q(effective_end__isnull=True) |
                    models.Q(effective_start__isnull=True)
                ),
                name="ck_effective_order",
            ),
        ]
        verbose_name = _("Assignment")
        verbose_name_plural = _("Assignments")

    def __str__(self):
        to = self.end_date.isoformat() if self.end_date else "…"
        return f"{self.person} — {self.role} ({self.start_date} → {to})"

    @property
    def is_active(self) -> bool:
        # Active = no end_date
        return self.end_date is None
