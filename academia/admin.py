# academia/models.py
from __future__ import annotations
from datetime import date
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords
from concurrency.fields import AutoIncVersionField
from hankosign.utils import state_snapshot, has_sig
from people.models import PersonRole, Person
import secrets
import random


# --- Utility Functions -------------------------------------------------------

def generate_semester_password():
    """Generate a memorable password in format: word-word-## (e.g., forest-mountain-42)"""
    # Import here to avoid circular dependency
    from .utils import get_random_words

    word1, word2 = get_random_words(2)
    number = random.randint(10, 99)
    return f"{word1}-{word2}-{number}"


def generate_reference_code(semester_code, last_name):
    """
    Generate reference code in format: SSSS-LLLL-####
    (e.g., WS24-SMIT-1234)

    Args:
        semester_code: 4-character semester code (e.g., "WS24")
        last_name: Person's last name

    Returns:
        String reference code
    """
    # Take first 4 chars of last name, uppercase, pad with X if needed
    name_part = last_name[:4].upper().ljust(4, 'X')

    # Generate 4 random digits
    number = secrets.randbelow(10000)
    number_part = f"{number:04d}"

    return f"{semester_code}-{name_part}-{number_part}"


# --- Models ------------------------------------------------------------------

class Semester(models.Model):
    """
    Academic semester for ECTS reimbursement tracking.

    A semester defines the time period during which ECTS reimbursements
    can be filed, approved, and audited. It includes access control via
    password for the public filing platform.
    """

    # Basic information
    code = models.CharField(
        _("Code"),
        max_length=10,
        unique=True,
        validators=[
            RegexValidator(
                regex=r'^(WS|SS)\d{2}$',
                message=_("Code must be in format: WS## or SS## (e.g., WS24, SS25)")
            )
        ],
        help_text=_("Short code in format WS## or SS## (e.g., WS24, SS25)")
    )

    display_name = models.CharField(
        _("Display Name"),
        max_length=100,
        help_text=_("Full name, e.g., Winter Semester 2024/25")
    )

    start_date = models.DateField(_("Start Date"))
    end_date = models.DateField(_("End Date"))

    # Public filing window
    filing_start = models.DateTimeField(
        _("Filing Start"),
        null=True,
        blank=True,
        help_text=_("When public filing platform opens for new requests")
    )

    filing_end = models.DateTimeField(
        _("Filing End"),
        null=True,
        blank=True,
        help_text=_("When public filing platform closes for new requests")
    )

    access_password = models.CharField(
        _("Access Password"),
        max_length=50,
        blank=True,
        help_text=_("Password for public filing access (auto-generated)")
    )

    # ECTS adjustment
    ects_adjustment = models.DecimalField(
        _("ECTS Adjustment"),
        max_digits=3,
        decimal_places=1,
        default=0,
        help_text=_("Bonus/malus ECTS (e.g., +2 or -2) for elected roles")
    )

    # Audit tracking
    audit_generated_at = models.DateTimeField(
        _("Audit Generated At"),
        null=True,
        blank=True,
        help_text=_("When audit entries were last synchronized")
    )

    audit_pdf = models.FileField(
        _("Audit PDF"),
        upload_to='academia/audits/',
        null=True,
        blank=True,
        help_text=_("Generated audit report for university")
    )

    audit_sent_university_at = models.DateTimeField(
        _("Sent to University At"),
        null=True,
        blank=True,
        help_text=_("When audit was sent to university")
    )

    # Standard fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # History & versioning
    history = HistoricalRecords()
    version = AutoIncVersionField()

    class Meta:
        verbose_name = _("Semester")
        verbose_name_plural = _("Semesters")
        ordering = ['-start_date']
        constraints = [
            models.CheckConstraint(
                check=models.Q(end_date__gte=models.F('start_date')),
                name='ck_semester_dates'
            )
        ]

    def __str__(self):
        return f"{self.code} - {self.display_name}"

    def save(self, *args, **kwargs):
        # Auto-generate password if not set
        if not self.access_password:
            self.access_password = generate_semester_password()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()

        # Prevent editing if locked
        if self.pk:
            original = Semester.objects.get(pk=self.pk)
            st = state_snapshot(original)

            if st.get("explicit_locked"):
                # Allow updating audit fields even when locked
                allowed_fields = {'audit_generated_at', 'audit_pdf', 'audit_sent_university_at', 'updated_at'}
                changed_fields = set()

                for field in self._meta.get_fields():
                    if field.name in allowed_fields:
                        continue
                    if hasattr(field, 'attname'):
                        if getattr(self, field.attname) != getattr(original, field.attname):
                            changed_fields.add(field.verbose_name or field.name)

                if changed_fields:
                    raise ValidationError(
                        _("Semester is locked. Cannot modify: %(fields)s") % {
                            'fields': ', '.join(changed_fields)
                        }
                    )

    @property
    def is_filing_open(self):
        """Check if filing window is currently open"""
        now = timezone.now()
        if not self.filing_start or not self.filing_end:
            return False
        return self.filing_start <= now <= self.filing_end


class InboxRequest(models.Model):
    """
    ECTS reimbursement request submitted by student.

    This is the main working table where students submit their course
    reimbursement requests. Requests are verified by staff and approved
    by chair before being included in the semester audit.
    """

    # Core relationships
    semester = models.ForeignKey(
        Semester,
        on_delete=models.PROTECT,
        related_name='inbox_requests',
        verbose_name=_("Semester")
    )

    person_role = models.ForeignKey(
        PersonRole,
        on_delete=models.PROTECT,
        related_name='ects_requests',
        verbose_name=_("Person Role"),
        help_text=_("The role under which ECTS are being claimed")
    )

    # Reference & access
    reference_code = models.CharField(
        _("Reference Code"),
        max_length=20,
        unique=True,
        blank=True,
        help_text=_("Unique code for student to access their request")
    )

    submission_ip = models.GenericIPAddressField(
        _("Submission IP"),
        null=True,
        blank=True,
        help_text=_("IP address from which request was submitted (audit trail)")
    )

    # Student input
    student_note = models.TextField(
        _("Student Note"),
        blank=True,
        help_text=_("Optional note from student")
    )

    # Affidavit tracking
    affidavit1_confirmed_at = models.DateTimeField(
        _("Affidavit 1 Confirmed At"),
        null=True,
        blank=True,
        help_text=_("When student confirmed initial submission affidavit")
    )

    affidavit2_confirmed_at = models.DateTimeField(
        _("Affidavit 2 Confirmed At"),
        null=True,
        blank=True,
        help_text=_("When student confirmed form upload affidavit")
    )

    # Form upload
    uploaded_form = models.FileField(
        _("Uploaded Form"),
        upload_to='academia/forms/%Y/%m/',
        null=True,
        blank=True,
        help_text=_("Signed form with professor signatures")
    )

    uploaded_form_at = models.DateTimeField(
        _("Uploaded Form At"),
        null=True,
        blank=True
    )

    # Standard fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # History & versioning
    history = HistoricalRecords()
    version = AutoIncVersionField()

    class Meta:
        verbose_name = _("Inbox Request")
        verbose_name_plural = _("Inbox Requests")
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['person_role', 'semester'],
                name='uq_inbox_one_per_person_per_semester'
            )
        ]

    def __str__(self):
        return f"{self.reference_code} - {self.person_role.person.last_name}"

    def save(self, *args, **kwargs):
        # Auto-generate reference code on first save
        if not self.reference_code and self.person_role_id and self.semester_id:
            semester_code = self.semester.code
            last_name = self.person_role.person.last_name

            # Ensure uniqueness
            max_attempts = 100
            for _ in range(max_attempts):
                code = generate_reference_code(semester_code, last_name)
                if not InboxRequest.objects.filter(reference_code=code).exists():
                    self.reference_code = code
                    break

            if not self.reference_code:
                raise ValidationError(_("Could not generate unique reference code"))

        super().save(*args, **kwargs)

    def clean(self):
        super().clean()

        # Check if parent semester is locked
        if self.semester_id:
            semester = Semester.objects.get(pk=self.semester_id)
            st = state_snapshot(semester)

            if st.get("explicit_locked"):
                raise ValidationError(
                    _("Semester is locked. Cannot modify requests.")
                )

        # Check if request itself is locked (for modifications after creation)
        if self.pk:
            original = InboxRequest.objects.get(pk=self.pk)
            st = state_snapshot(original)

            # Allow file upload even if verified
            if has_sig(original, 'VERIFY', ''):
                # Only allow updating uploaded_form and affidavit2
                allowed_fields = {'uploaded_form', 'uploaded_form_at', 'affidavit2_confirmed_at', 'updated_at'}
                changed_fields = set()

                for field in self._meta.get_fields():
                    if field.name in allowed_fields:
                        continue
                    if hasattr(field, 'attname'):
                        if getattr(self, field.attname) != getattr(original, field.attname):
                            changed_fields.add(field.verbose_name or field.name)

                if changed_fields:
                    raise ValidationError(
                        _("Request verified. Cannot modify: %(fields)s") % {
                            'fields': ', '.join(changed_fields)
                        }
                    )

    @property
    def stage(self):
        """
        Derive stage from HankoSign signatures and upload state.

        Returns:
            str: One of DRAFT, SUBMITTED, VERIFIED, APPROVED, REJECTED, TRANSFERRED
        """
        # Check for rejection first
        if has_sig(self, 'REJECT', 'CHAIR'):
            return 'REJECTED'

        # Check if transferred to audit (check if AuditEntry exists)
        # Avoid circular import by doing late import
        from academia_audit.models import AuditEntry
        if AuditEntry.objects.filter(
            audit_semester__semester=self.semester,
            person=self.person_role.person,
            inbox_requests=self
        ).exists():
            return 'TRANSFERRED'

        # Check HankoSign approvals
        if has_sig(self, 'APPROVE', 'CHAIR'):
            return 'APPROVED'

        if has_sig(self, 'VERIFY', ''):
            return 'VERIFIED'

        # Check if form uploaded
        if self.uploaded_form and self.affidavit2_confirmed_at:
            return 'SUBMITTED'

        # Check if courses entered
        if self.affidavit1_confirmed_at and self.courses.exists():
            return 'DRAFT'

        return 'DRAFT'

    @property
    def total_ects(self):
        """Calculate total ECTS from all courses"""
        return sum(course.ects_amount for course in self.courses.all())


class InboxCourse(models.Model):
    """
    Individual course within an ECTS reimbursement request.

    Each course represents a specific class for which the student
    is requesting ECTS credit. At least one of course_code or
    course_name must be provided.
    """

    inbox_request = models.ForeignKey(
        InboxRequest,
        on_delete=models.CASCADE,
        related_name='courses',
        verbose_name=_("Inbox Request")
    )

    course_code = models.CharField(
        _("Course Code"),
        max_length=20,
        blank=True,
        help_text=_("Course code, e.g., LV101")
    )

    course_name = models.CharField(
        _("Course Name"),
        max_length=200,
        blank=True,
        help_text=_("Full course name, e.g., Advanced Mathematics")
    )

    ects_amount = models.DecimalField(
        _("ECTS Amount"),
        max_digits=3,
        decimal_places=1,
        help_text=_("ECTS credit for this course")
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Course")
        verbose_name_plural = _("Courses")
        ordering = ['id']

    def __str__(self):
        if self.course_code and self.course_name:
            return f"{self.course_code} - {self.course_name} ({self.ects_amount} ECTS)"
        elif self.course_code:
            return f"{self.course_code} ({self.ects_amount} ECTS)"
        elif self.course_name:
            return f"{self.course_name} ({self.ects_amount} ECTS)"
        return f"Course ({self.ects_amount} ECTS)"

    def clean(self):
        super().clean()

        # At least one of course_code or course_name must be provided
        if not self.course_code and not self.course_name:
            raise ValidationError(
                _("At least one of course code or course name is required")
            )

        # ECTS amount must be positive
        if self.ects_amount and self.ects_amount <= 0:
            raise ValidationError(
                _("ECTS amount must be greater than 0")
            )