# academia/utils.py
"""
Utility functions for Academia module.

Includes ECTS calculation, aliquotation, audit synchronization,
and password generation utilities.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from django.db import models, transaction
from django.utils import timezone
import random
import yaml
from pathlib import Path


# --- Password Generation -----------------------------------------------------

def get_random_words(count=2):
    """
    Get random words from wordlist for password generation.

    Args:
        count: Number of words to return

    Returns:
        List of random words
    """
    wordlist_path = Path(__file__).parent / 'wordlist.yaml'

    try:
        with open(wordlist_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            words = data.get('words', [])

            if not words:
                # Fallback words if YAML is empty
                words = [
                    'forest', 'mountain', 'river', 'ocean', 'valley',
                    'sunrise', 'sunset', 'thunder', 'breeze', 'meadow',
                    'glacier', 'canyon', 'desert', 'island', 'storm'
                ]

            return random.sample(words, min(count, len(words)))

    except FileNotFoundError:
        # Fallback if file doesn't exist yet
        fallback = [
            'forest', 'mountain', 'river', 'ocean', 'valley',
            'sunrise', 'sunset', 'thunder', 'breeze', 'meadow'
        ]
        return random.sample(fallback, count)


# --- ECTS Calculation --------------------------------------------------------

def calculate_aliquoted_ects(person_role, semester):
    """
    DEPRECATED: Moved to academia_audit.utils.calculate_aliquoted_ects()

    This function is only used for audit calculations and has been moved to
    the academia_audit app. For inbox validation, use role.ects_cap directly.

    Calculate aliquoted ECTS for a PersonRole during a semester window.

    Accounts for partial semester overlap by prorating based on the
    number of days the person worked in their role during the semester.

    Args:
        person_role: PersonRole instance
        semester: Semester instance

    Returns:
        Decimal: Aliquoted ECTS amount (rounded to 2 decimal places)
    """
    import warnings
    warnings.warn(
        "calculate_aliquoted_ects in academia.utils is deprecated. "
        "Use academia_audit.utils.calculate_aliquoted_ects() instead.",
        DeprecationWarning,
        stacklevel=2
    )

    from academia_audit.utils import calculate_aliquoted_ects as calc_aliquoted
    return calc_aliquoted(person_role, semester)


def calculate_overlap_percentage(person_role, semester):
    """
    DEPRECATED: Moved to academia_audit.utils.calculate_overlap_percentage()

    This function is only used for audit calculations and has been moved to
    the academia_audit app.

    Calculate what percentage of the semester a PersonRole was active.

    Args:
        person_role: PersonRole instance
        semester: Semester instance

    Returns:
        Decimal: Percentage (0-1) of semester overlap
    """
    import warnings
    warnings.warn(
        "calculate_overlap_percentage in academia.utils is deprecated. "
        "Use academia_audit.utils.calculate_overlap_percentage() instead.",
        DeprecationWarning,
        stacklevel=2
    )

    from academia_audit.utils import calculate_overlap_percentage as calc_overlap
    return calc_overlap(person_role, semester)


# --- Audit Synchronization ---------------------------------------------------

@transaction.atomic
def synchronize_audit_entries(semester):
    """
    DEPRECATED: Use academia_audit.utils.synchronize_audit_entries() instead.

    This function works with the deprecated SemesterAuditEntry model.
    For new audit workflows, use AuditSemester and AuditEntry models
    in the academia_audit app.

    Create or update SemesterAuditEntry records for a semester.

    This function:
    1. Finds all PersonRoles active during the semester
    2. Groups them by Person
    3. Calculates maximum entitled ECTS (highest role, with aliquotation)
    4. Sums reimbursed ECTS from approved InboxRequests
    5. Calculates bulk ECTS (max - reimbursed)
    6. Creates or updates SemesterAuditEntry records

    Can be run multiple times (idempotent) - will add new entries only,
    preserving any manual adjustments made to existing entries.

    Args:
        semester: Semester instance

    Returns:
        tuple: (created_count, skipped_count)
    """
    import warnings
    warnings.warn(
        "synchronize_audit_entries in academia.utils is deprecated. "
        "Use academia_audit.utils.synchronize_audit_entries() instead.",
        DeprecationWarning,
        stacklevel=2
    )

    from people.models import PersonRole, Person
    from academia.models import InboxRequest, SemesterAuditEntry
    from hankosign.utils import has_sig
    from django.db.models import Q

    # Find all PersonRoles active during semester
    person_roles = PersonRole.objects.filter(
        Q(start_date__lte=semester.end_date),
        Q(end_date__gte=semester.start_date) | Q(end_date__isnull=True)
    ).select_related('person', 'role')

    # Group by person
    persons_map = {}
    for pr in person_roles:
        if pr.person not in persons_map:
            persons_map[pr.person] = []
        persons_map[pr.person].append(pr)

    created_count = 0
    skipped_count = 0

    for person, their_roles in persons_map.items():
        # Check if entry already exists
        existing = SemesterAuditEntry.objects.filter(
            semester=semester,
            person=person
        ).first()

        if existing:
            skipped_count += 1
            continue

        # Calculate aliquoted ECTS for each role
        role_calcs = []
        for pr in their_roles:
            aliquoted = calculate_aliquoted_ects(pr, semester)
            percentage = calculate_overlap_percentage(pr, semester)

            role_calcs.append({
                'role_name': pr.role.name,
                'person_role_id': pr.id,
                'nominal_ects': float(pr.role.ects_cap),
                'held_from': pr.start_date.isoformat(),
                'held_to': pr.end_date.isoformat() if pr.end_date else 'ongoing',
                'aliquoted_ects': float(aliquoted),
                'percentage': float(percentage)
            })

        # Max ECTS = highest role (not sum)
        if role_calcs:
            max_ects = max(Decimal(str(rc['aliquoted_ects'])) for rc in role_calcs)
        else:
            max_ects = Decimal('0.00')

        # Apply semester bonus/malus
        max_ects += Decimal(str(semester.ects_adjustment))

        # Ensure max_ects is not negative
        if max_ects < 0:
            max_ects = Decimal('0.00')

        # Get approved InboxRequests for this person
        approved_requests = InboxRequest.objects.filter(
            person_role__person=person,
            semester=semester
        ).prefetch_related('courses')

        # Filter to only those with APPROVE:CHAIR signature
        approved_requests_filtered = []
        for req in approved_requests:
            if has_sig(req, 'APPROVE', 'CHAIR'):
                approved_requests_filtered.append(req)

        # Sum reimbursed ECTS
        total_reimbursed = Decimal('0.00')
        for req in approved_requests_filtered:
            for course in req.courses.all():
                total_reimbursed += Decimal(str(course.ects_amount))

        # Calculate bulk ECTS
        bulk_ects = max(max_ects - total_reimbursed, Decimal('0.00'))

        # Create audit entry
        entry = SemesterAuditEntry.objects.create(
            semester=semester,
            person=person,
            max_ects_entitled=max_ects,
            ects_reimbursed=total_reimbursed,
            ects_bulk=bulk_ects,
            calculation_details={
                'roles': role_calcs,
                'bonus_malus': float(semester.ects_adjustment),
                'calculation_date': timezone.now().isoformat(),
                'approved_requests_count': len(approved_requests_filtered)
            }
        )

        # Update M2M relationships
        entry.person_roles.set(their_roles)
        entry.inbox_requests.set(approved_requests_filtered)

        created_count += 1

    # Update semester's audit_generated_at timestamp
    semester.audit_generated_at = timezone.now()
    semester.save(update_fields=['audit_generated_at'])

    return created_count, skipped_count


def validate_ects_total(inbox_request):
    """
    Validate that total ECTS from courses doesn't exceed the role's nominal ECTS cap.

    This is a formal validation only - checks against the role's max ECTS without
    aliquotation. The actual earned ECTS calculation (with aliquotation based on
    work period) happens during the audit phase.

    Args:
        inbox_request: InboxRequest instance

    Returns:
        tuple: (is_valid: bool, max_ects: Decimal, total_ects: Decimal, message: str)
    """
    from academia.models import InboxRequest

    # Get the role's nominal ECTS cap (formal limit, no aliquotation)
    person_role = inbox_request.person_role
    max_ects = Decimal(str(person_role.role.ects_cap))

    # Calculate total from courses
    total_ects = Decimal('0.00')
    for course in inbox_request.courses.all():
        total_ects += Decimal(str(course.ects_amount))

    is_valid = total_ects <= max_ects

    if not is_valid:
        message = f"Total ECTS ({total_ects}) exceeds role's maximum ({max_ects})."
    else:
        message = f"Total ECTS ({total_ects}) is within role's limit ({max_ects})."

    return is_valid, max_ects, total_ects, message
