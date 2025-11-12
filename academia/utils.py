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
    Calculate aliquoted ECTS for a PersonRole during a semester window.

    Accounts for partial semester overlap by prorating based on the
    number of days the person worked in their role during the semester.

    Args:
        person_role: PersonRole instance
        semester: Semester instance

    Returns:
        Decimal: Aliquoted ECTS amount (rounded to 2 decimal places)
    """
    from people.models import PersonRole
    from academia.models import Semester

    # Find overlap between PersonRole dates and Semester dates
    pr_start = max(person_role.start_date, semester.start_date)
    pr_end = min(
        person_role.end_date if person_role.end_date else date.max,
        semester.end_date
    )

    # If no overlap, return 0
    if pr_start > pr_end:
        return Decimal('0.00')

    # Calculate percentage of semester worked
    days_worked = (pr_end - pr_start).days + 1  # Inclusive
    semester_days = (semester.end_date - semester.start_date).days + 1

    percentage = Decimal(days_worked) / Decimal(semester_days)

    # Apply to role's max ECTS
    max_ects = Decimal(str(person_role.role.max_ects_per_semester))
    aliquoted = (max_ects * percentage).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    return aliquoted


def calculate_overlap_percentage(person_role, semester):
    """
    Calculate what percentage of the semester a PersonRole was active.

    Args:
        person_role: PersonRole instance
        semester: Semester instance

    Returns:
        Decimal: Percentage (0-1) of semester overlap
    """
    pr_start = max(person_role.start_date, semester.start_date)
    pr_end = min(
        person_role.end_date if person_role.end_date else date.max,
        semester.end_date
    )

    if pr_start > pr_end:
        return Decimal('0.00')

    days_worked = (pr_end - pr_start).days + 1
    semester_days = (semester.end_date - semester.start_date).days + 1

    percentage = (Decimal(days_worked) / Decimal(semester_days)).quantize(
        Decimal('0.0001'),
        rounding=ROUND_HALF_UP
    )

    return percentage


# --- Audit Synchronization ---------------------------------------------------

@transaction.atomic
def synchronize_audit_entries(semester):
    """
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
                'nominal_ects': float(pr.role.max_ects_per_semester),
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
    Validate that total ECTS from courses doesn't exceed max entitled.

    Args:
        inbox_request: InboxRequest instance

    Returns:
        tuple: (is_valid: bool, max_ects: Decimal, total_ects: Decimal, message: str)
    """
    from academia.models import InboxRequest

    # Calculate max entitled ECTS for this person role during semester
    person_role = inbox_request.person_role
    semester = inbox_request.semester

    # Calculate aliquoted ECTS
    aliquoted = calculate_aliquoted_ects(person_role, semester)

    # Apply semester bonus/malus
    max_ects = aliquoted + Decimal(str(semester.ects_adjustment))

    # Ensure not negative
    if max_ects < 0:
        max_ects = Decimal('0.00')

    # Calculate total from courses
    total_ects = Decimal('0.00')
    for course in inbox_request.courses.all():
        total_ects += Decimal(str(course.ects_amount))

    is_valid = total_ects <= max_ects

    if not is_valid:
        message = f"Total ECTS ({total_ects}) exceeds maximum entitled ({max_ects}) for this role."
    else:
        message = f"Total ECTS ({total_ects}) is within limit ({max_ects})."

    return is_valid, max_ects, total_ects, message
