from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

from tinymce.models import HTMLField
from simple_history.models import HistoricalRecords
from concurrency.fields import IntegerVersionField

from people.models import PersonRole


# ============================================================================
# UTILITIES
# ============================================================================

def int_to_roman(num):
    """Convert 1-50 to Roman numerals"""
    if num < 1 or num > 50:
        raise ValueError("Roman numerals only supported for 1-50")
    
    val = [
        (50, 'L'), (40, 'XL'), (10, 'X'), (9, 'IX'),
        (5, 'V'), (4, 'IV'), (1, 'I')
    ]
    result = []
    for i, r in val:
        count, num = divmod(num, i)
        result.append(r * count)
    return ''.join(result)


# ============================================================================
# TERM (like FiscalYear)
# ============================================================================

class Term(models.Model):
    """Legislative term / Funktionsperiode"""
    
    code = models.CharField(
        _("Code"), max_length=20, unique=True, editable=False,
        help_text=_("Auto-generated: HV25_27")
    )
    label = models.CharField(_("Label"), max_length=100)
    
    start_date = models.DateField(_("Start date"))
    end_date = models.DateField(_("End date"), help_text=_("Usually +2 years from start"))
    
    is_active = models.BooleanField(
        _("Active term"), default=False,
        help_text=_("Only one term can be active at a time")
    )
    
    notes = models.TextField(_("Notes"), blank=True)
    
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)
    
    history = HistoricalRecords()
    version = IntegerVersionField()
    
    class Meta:
        verbose_name = _("Term")
        verbose_name_plural = _("Terms")
        ordering = ["-start_date"]
    
    def __str__(self):
        return f"{self.code} — {self.label}"
    
    def save(self, *args, **kwargs):
        # Auto-generate code
        if not self.code:
            self.code = self.generate_code()
        
        # Auto-set end_date to +2 years if empty
        if not self.end_date and self.start_date:
            self.end_date = self.start_date.replace(year=self.start_date.year + 2)
        
        super().save(*args, **kwargs)
    
    def generate_code(self):
        """Generate HV25_27 from start_date"""
        y1 = self.start_date.year % 100
        y2 = (self.start_date.year + 2) % 100
        return f"HV{y1:02d}_{y2:02d}"
    
    def display_code(self):
        """For admin display"""
        return self.code
    display_code.short_description = _("Code")


# ============================================================================
# COMPOSITION & MANDATES
# ============================================================================

class Composition(models.Model):
    """Container for all mandates in a term"""
    
    term = models.OneToOneField(
        Term, on_delete=models.PROTECT,
        related_name="composition",
        verbose_name=_("Term")
    )
    
    notes = models.TextField(_("Notes"), blank=True)
    
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)
    
    history = HistoricalRecords()
    version = IntegerVersionField()
    
    class Meta:
        verbose_name = _("Composition")
        verbose_name_plural = _("Compositions")
    
    def __str__(self):
        return f"Composition for {self.term.code}"
    
    def active_mandates_count(self):
        """Count currently active mandates"""
        return self.mandates.filter(end_date__isnull=True).count()
    
    def clean(self):
        super().clean()
        # Ensure max 9 active mandates
        if self.pk and self.active_mandates_count() > 9:
            raise ValidationError(_("Cannot have more than 9 active mandates."))


class Mandate(models.Model):
    """Individual seat holder - can change during term"""
    
    class OfficerRole(models.TextChoices):
        CHAIR = "CHAIR", _("Vorsitzende/r")
        DEPUTY_1 = "DEP1", _("1. Stellvertretung")
        DEPUTY_2 = "DEP2", _("2. Stellvertretung")
        MEMBER = "MEMB", _("Mandatar/in")
    
    composition = models.ForeignKey(
        Composition, on_delete=models.CASCADE,
        related_name="mandates",
        verbose_name=_("Composition")
    )
    
    position = models.PositiveSmallIntegerField(
        _("Position"), help_text=_("Seat number (1-9)")
    )
    
    person_role = models.ForeignKey(
        PersonRole, on_delete=models.PROTECT,
        related_name="assembly_mandates",
        verbose_name=_("Person")
    )
    
    officer_role = models.CharField(
        _("Officer role"), max_length=5,
        choices=OfficerRole.choices,
        default=OfficerRole.MEMBER
    )
    
    # Track succession over time
    start_date = models.DateField(_("Start date"))
    end_date = models.DateField(_("End date"), null=True, blank=True)
    
    # Backup person (Ersatzperson)
    backup_person_role = models.ForeignKey(
        PersonRole, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="assembly_backups",
        verbose_name=_("Backup person (in system)")
    )
    backup_person_text = models.CharField(
        _("Backup person (external)"), max_length=200, blank=True,
        help_text=_("For externals not in the system")
    )
    
    notes = models.TextField(_("Notes"), blank=True)
    
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)
    
    history = HistoricalRecords()
    version = IntegerVersionField()
    
    class Meta:
        verbose_name = _("Mandate")
        verbose_name_plural = _("Mandates")
        ordering = ["position", "-start_date"]
    
    def __str__(self):
        status = "active" if not self.end_date else "ended"
        return f"Position {self.position} — {self.person_role} ({status})"
    
    @property
    def is_active(self):
        """Is this mandate currently active?"""
        return self.end_date is None
    
    def clean(self):
        super().clean()
        
        # Position must be 1-9
        if self.position < 1 or self.position > 9:
            raise ValidationError({"position": _("Position must be between 1 and 9.")})
        
        # Dates must make sense
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": _("End date cannot be before start date.")})


# ============================================================================
# SESSION
# ============================================================================

class Session(models.Model):
    """Individual HV meeting / Sitzung"""
    
    class Type(models.TextChoices):
        REGULAR = "or", _("Ordentlich")
        EXTRAORDINARY = "ao", _("Außerordentlich")
    
    term = models.ForeignKey(
        Term, on_delete=models.PROTECT,
        related_name="sessions",
        verbose_name=_("Term")
    )
    
    code = models.CharField(
        _("Code"), max_length=30, unique=True, editable=False,
        help_text=_("Auto-generated: HV25_27_I:or")
    )
    
    session_type = models.CharField(
        _("Session type"), max_length=2,
        choices=Type.choices,
        default=Type.REGULAR
    )
    
    session_date = models.DateField(_("Session date"))
    session_time = models.TimeField(_("Session time"), null=True, blank=True)
    location = models.CharField(_("Location"), max_length=200, blank=True)
    
    # Protocol metadata
    protocol_number = models.CharField(
        _("Protocol number"), max_length=50, blank=True
    )
    
    # Attendance
    attendees = models.ManyToManyField(
        Mandate, blank=True,
        related_name="attended_sessions",
        verbose_name=_("Attendees")
    )
    absent = models.ManyToManyField(
        Mandate, blank=True,
        related_name="missed_sessions",
        verbose_name=_("Absent")
    )
    other_attendees = models.TextField(
        _("Other attendees"), blank=True,
        help_text=_("External guests (Anna Bauer; Peter Müller; ...)")
    )
    
    # Workflow timestamps
    invitations_sent_at = models.DateTimeField(
        _("Invitations sent at"), null=True, blank=True
    )
    minutes_finalized_at = models.DateTimeField(
        _("Minutes finalized at"), null=True, blank=True
    )
    sent_koko_hsg_at = models.DateTimeField(
        _("Sent to KoKo/HSG at"), null=True, blank=True
    )
    
    notes = models.TextField(_("Notes"), blank=True)
    
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)
    
    history = HistoricalRecords()
    version = IntegerVersionField()
    
    class Meta:
        verbose_name = _("Session")
        verbose_name_plural = _("Sessions")
        ordering = ["-session_date", "code"]
    
    def __str__(self):
        return f"{self.code} — {self.session_date}"
    
    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self.generate_code()
        super().save(*args, **kwargs)
    
    def generate_code(self):
        """Generate HV25_27_I:or, HV25_27_II:ao, etc."""
        count = Session.objects.filter(term=self.term).count() + 1
        roman = int_to_roman(count)
        return f"{self.term.code}_{roman}:{self.session_type}"
    
    @property
    def full_display_code(self):
        """For admin display"""
        return self.code


# ============================================================================
# SESSION ITEM
# ============================================================================

class SessionItem(models.Model):
    """Agenda item / Tagesordnungspunkt"""
    
    class Kind(models.TextChoices):
        RESOLUTION = "RES", _("Beschluss")
        PROCEDURAL = "PROC", _("Ablaufinformation")
        ELECTION = "ELEC", _("Wahl")
    
    class VotingMode(models.TextChoices):
        NONE = "NONE", _("Keine Abstimmung")
        COUNTED = "COUNT", _("Stimmenzählung")
        NAMED = "NAMED", _("Namentliche Abstimmung")
    
    session = models.ForeignKey(
        Session, on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("Session")
    )
    
    item_code = models.CharField(
        _("Item code"), max_length=10, editable=False,
        help_text=_("Auto-generated: S001, S002, ...")
    )
    
    order = models.PositiveSmallIntegerField(
        _("Order"), help_text=_("Position in agenda")
    )
    
    kind = models.CharField(
        _("Kind"), max_length=10,
        choices=Kind.choices
    )
    
    title = models.CharField(_("Title"), max_length=300)
    
    # Content fields (conditional based on kind)
    # For PROCEDURAL: just use 'content'
    # For RESOLUTION/ELECTION: use subject/discussion/outcome
    content = models.TextField(
        _("Content"), blank=True,
        help_text=_("For procedural items")
    )
    
    subject = HTMLField(
        _("Subject"), blank=True,
        help_text=_("Subject of the item")
    )
    discussion = HTMLField(
        _("Discussion"), blank=True,
        help_text=_("Discussion contents for the item")
    )
    outcome = HTMLField(
        _("Outcome"), blank=True,
        help_text=_("Result or outcome for the item")
    )
    
    # Voting (for RESOLUTION kind)
    voting_mode = models.CharField(
        _("Voting mode"), max_length=10,
        choices=VotingMode.choices,
        default=VotingMode.NONE
    )
    
    # Counted votes
    votes_for = models.PositiveSmallIntegerField(
        _("Votes for"), null=True, blank=True
    )
    votes_against = models.PositiveSmallIntegerField(
        _("Votes against"), null=True, blank=True
    )
    votes_abstain = models.PositiveSmallIntegerField(
        _("Abstentions"), null=True, blank=True
    )
    
    passed = models.BooleanField(
        _("Passed"), null=True, blank=True
    )
    
    # Election link (for ELECTION kind)
    elected_person_role = models.ForeignKey(
        PersonRole, null=True, blank=True,
        on_delete=models.PROTECT,
        related_name="elected_via_assembly",
        verbose_name=_("Elected person")
    )
    
    notes = models.TextField(_("Notes"), blank=True)
    
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)
    
    history = HistoricalRecords()
    version = IntegerVersionField()
    
    class Meta:
        verbose_name = _("Session Item")
        verbose_name_plural = _("Session Items")
        ordering = ["session", "order"]
        unique_together = [("session", "order")]
    
    def __str__(self):
        return f"{self.item_code} — {self.title}"
    
    def save(self, *args, **kwargs):
        if not self.item_code:
            count = SessionItem.objects.filter(session=self.session).count() + 1
            self.item_code = f"S{count:03d}"
        
        # Call parent save
        super().save(*args, **kwargs)
        
        # If this is an election, update PersonRole
        if self.kind == self.Kind.ELECTION and self.elected_person_role_id:
            pr = self.elected_person_role
            pr.elected_via = self
            if self.session.session_date:
                pr.confirm_date = self.session.session_date
            pr.save(update_fields=['elected_via', 'confirm_date'])
    
    @property
    def full_identifier(self):
        """HV25_27_III:ao-S001"""
        return f"{self.session.code}-{self.item_code}"
    
    def clean(self):
        super().clean()
        
        # Validate voting data completeness
        if self.voting_mode == self.VotingMode.COUNTED:
            if any(v is None for v in [self.votes_for, self.votes_against, self.votes_abstain]):
                raise ValidationError(
                    _("For counted voting, all vote counts must be filled in.")
                )


# ============================================================================
# NAMED VOTE (for namentliche Abstimmung)
# ============================================================================

class Vote(models.Model):
    """Named voting record"""
    
    class Choice(models.TextChoices):
        FOR = "FOR", _("Ja")
        AGAINST = "AGAINST", _("Nein")
        ABSTAIN = "ABSTAIN", _("Enthaltung")
    
    item = models.ForeignKey(
        SessionItem, on_delete=models.CASCADE,
        related_name="named_votes",
        verbose_name=_("Item")
    )
    
    mandate = models.ForeignKey(
        Mandate, on_delete=models.PROTECT,
        verbose_name=_("Mandate")
    )
    
    vote = models.CharField(
        _("Vote"), max_length=10,
        choices=Choice.choices
    )
    
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    
    class Meta:
        verbose_name = _("Vote")
        verbose_name_plural = _("Votes")
        unique_together = [("item", "mandate")]
    
    def __str__(self):
        return f"{self.mandate} — {self.get_vote_display()}"