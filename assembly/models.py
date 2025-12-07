# File: assembly/models.py
# Version: 1.0.1
# Author: vas
# Modified: 2025-12-06

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

def session_status(session) -> str:
    """
    Determine Session workflow status from HankoSign signatures.
    
    Returns one of: DRAFT | SUBMITTED | APPROVED | VERIFIED | REJECTED
    
    Logic:
      - REJECTED: Any REJECT signature exists
      - DRAFT: No SUBMIT signature (or withdrawn)
      - SUBMITTED: Submitted but CHAIR hasn't approved
      - APPROVED: CHAIR approved but not yet verified
      - VERIFIED: All done, sent to KoKo/HSG
    
    Args:
        session: Session instance
        
    Returns:
        Status code string (DRAFT|SUBMITTED|APPROVED|VERIFIED|REJECTED)
    """
    from hankosign.utils import state_snapshot
    
    st = state_snapshot(session)
    
    # 1. Check for rejection
    if st.get("rejected"):
        return "REJECTED"
    
    # 2. Check if submitted
    if not st.get("submitted"):
        return "DRAFT"
    
    # 3. Check for Chair approval
    approved = st.get("approved", set())
    if "CHAIR" not in approved:
        return "SUBMITTED"
    
    # 4. Check for verification (sent to KoKo/HSG)
    if not st.get("verified"):
        return "APPROVED"
    
    # 5. Everything done
    return "VERIFIED"


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
    
    #notes = models.TextField(_("Notes"), blank=True)
    
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
        """Generate HV25_27 from start_date and end_date"""
        y1 = self.start_date.year % 100
        
        # Use actual end_date if provided, otherwise assume +2 years
        if self.end_date:
            y2 = self.end_date.year % 100
        else:
            y2 = (self.start_date.year + 2) % 100
        
        return f"HV{y1:02d}_{y2:02d}"
    
    def display_code(self):
        """For admin display"""
        return self.code
    display_code.short_description = _("Code")

    def clean(self):
        super().clean()
        errors = {}
        
        # Validate date ordering
        if self.start_date and self.end_date and self.end_date < self.start_date:
            errors['end_date'] = _("End date cannot be before start date.")
        
        # Defensive check for duplicate code (even though auto-generated)
        if self.code:
            existing = Term.objects.filter(code=self.code).exclude(pk=self.pk).exists()
            if existing:
                errors['code'] = _("A term with this code already exists.")
        
        if errors:
            raise ValidationError(errors)


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
    
    #notes = models.TextField(_("Notes"), blank=True)
    
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
        errors = {}
        
        # Check for duplicate term (OneToOne)
        if self.term_id:
            existing = Composition.objects.filter(
                term_id=self.term_id
            ).exclude(pk=self.pk).exists()
            
            if existing:
                errors['term'] = _("A composition already exists for this term.")
        
        # Ensure max 9 active mandates (existing logic - keep as-is)
        if self.pk and self.active_mandates_count() > 9:
            errors['__all__'] = _("Cannot have more than 9 active mandates.")
        
        if errors:
            raise ValidationError(errors)


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
    party = models.CharField(
        _("Party affiliation"), max_length=100, blank=True,
        help_text=_("Wahlwerbende Gruppe/Liste (e.g., VSSTÖ, AG, GRAS)")
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

    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        SUBMITTED = "SUBMITTED", _("Submitted")
        APPROVED = "APPROVED", _("Approved by Chair")
        VERIFIED = "VERIFIED", _("Sent to KoKo/HSG")
        REJECTED = "REJECTED", _("Rejected re-work")

    
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

    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        help_text=_("Workflow status derived from signatures.")
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
        Mandate,
        through='SessionAttendance',
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
    
    #notes = models.TextField(_("Notes"), blank=True)
    
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
        if self.pk:
            self.status = session_status(self)
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
    
    def clean(self):
        super().clean()
        errors = {}
        
        # Validate date makes sense
        if self.session_date and self.term_id:
            term = Term.objects.get(pk=self.term_id)
            if not (term.start_date <= self.session_date <= term.end_date):
                errors['session_date'] = _(
                    "Session date must fall within term period (%(start)s - %(end)s)."
                ) % {'start': term.start_date, 'end': term.end_date}
        
        # Defensive check for duplicate code
        if self.code:
            existing = Session.objects.filter(code=self.code).exclude(pk=self.pk).exists()
            if existing:
                errors['code'] = _("A session with this code already exists.")
        
        if errors:
            raise ValidationError(errors)


# ============================================================================
# SESSION ATTENDANCE TRACKING
# ============================================================================


class SessionAttendance(models.Model):
    """Track who actually attended - primary mandatary or backup"""
    
    session = models.ForeignKey(
        Session, 
        on_delete=models.CASCADE,
        related_name='attendance_records',
        verbose_name=_("Session")
    )
    
    mandate = models.ForeignKey(
        Mandate,
        on_delete=models.PROTECT,
        verbose_name=_("Mandate")
    )
    
    backup_attended = models.BooleanField(
        _("Backup Attended"),
        default=False,
        help_text=_("Check if backup person attended instead of primary mandatary")
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = _("Session Attendance")
        verbose_name_plural = _("Session Attendances")
        ordering = ['mandate__position']
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'mandate'],
                name='uq_attendance_session_mandate'
            )
        ]
    
    def __str__(self):
        who = "Backup" if self.backup_attended else "Primary"
        return f"{self.mandate} ({who}) @ {self.session.code}"
    
    def clean(self):
        super().clean()
        errors = {}
        
        # Check for duplicate (session, mandate) before DB does
        if self.session_id and self.mandate_id:
            existing = SessionAttendance.objects.filter(
                session_id=self.session_id,
                mandate_id=self.mandate_id
            ).exclude(pk=self.pk).exists()
            
            if existing:
                errors['__all__'] = _(
                    "This mandate is already recorded as attending this session."
                )
        
        if errors:
            raise ValidationError(errors)



# ============================================================================
# SESSION ITEM
# ============================================================================

class SessionItem(models.Model):
    """Agenda item / Tagesordnungspunkt"""
    
    class Kind(models.TextChoices):
        RESOLUTION = "RES", _("Beschluss")
        PROCEDURAL = "PROC", _("Ablaufinformation")
        ELECTION = "ELEC", _("Beschluss iSe Personalwahl")
    
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

    elected_person_text_reference = models.CharField(
        _("Elected person (text reference)"),
        max_length=200,
        blank=True,
        help_text=_("Temporary text reference for elected person - to be linked to PersonRole later")
    )

    elected_role_text_reference = models.CharField(
        _("Elected role (text reference)"),
        max_length=200,
        blank=True,
        help_text=_("Temporary text reference for elected role - to be linked to PersonRole later")
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
        
        super().save(*args, **kwargs)
        
        # Only update PersonRole if session is approved
        if (self.kind == self.Kind.ELECTION and 
            self.elected_person_role_id and
            self.session.status in (Session.Status.APPROVED, Session.Status.VERIFIED)):
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
        errors = {}
        
        # Check for duplicate (session, order)
        if self.session_id and self.order:
            existing = SessionItem.objects.filter(
                session_id=self.session_id,
                order=self.order
            ).exclude(pk=self.pk).exists()
            
            if existing:
                errors['order'] = _(
                    "An item with order %(order)d already exists in this session."
                ) % {'order': self.order}
        
        # Validate voting data completeness (existing logic - keep as-is)
        if self.voting_mode == self.VotingMode.COUNTED:
            if any(v is None for v in [self.votes_for, self.votes_against, self.votes_abstain]):
                errors['__all__'] = _(
                    "For counted voting, all vote counts must be filled in."
                )
        
        if errors:
            raise ValidationError(errors)


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
    
    def clean(self):
        super().clean()
        errors = {}
        
        # Check for duplicate (item, mandate)
        if self.item_id and self.mandate_id:
            existing = Vote.objects.filter(
                item_id=self.item_id,
                mandate_id=self.mandate_id
            ).exclude(pk=self.pk).exists()
            
            if existing:
                errors['__all__'] = _(
                    "This mandate has already voted on this item."
                )
        
        if errors:
            raise ValidationError(errors)