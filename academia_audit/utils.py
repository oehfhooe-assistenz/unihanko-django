# academia_audit/utils.py
"""
Utility functions for Academia Audit module.

Includes audit synchronization and ECTS calculation helpers.
"""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from django.db import models, transaction
from django.utils import timezone
from django.db.models import Q


@transaction.atomic
def synchronize_audit_entries(audit_semester):
    """
    Create or update AuditEntry records for an audit semester.

    This function:
    1. Finds all PersonRoles active during the semester
    2. Groups them by Person
    3. Calculates maximum entitled ECTS (highest role, with aliquotation + bonus/malus)
    4. Sums reimbursed ECTS from approved InboxRequests
    5. Calculates remaining ECTS (final - reimbursed)
    6. Creates NEW entries only OR updates entries where checked_at IS NULL

    IMPORTANT: Preserves manually reviewed entries (checked_at != NULL).
    Can be run multiple times (idempotent).

    Args:
        audit_semester: AuditSemester instance

    Returns:
        tuple: (created_count, updated_count, skipped_count)
    """
    from people.models import PersonRole, Person
    from academia.models import InboxRequest
    from academia.utils import calculate_aliquoted_ects
    from academia_audit.models import AuditEntry
    from hankosign.utils import has_sig

    semester = audit_semester.semester

    # Find all PersonRoles active during semester
    person_roles = PersonRole.objects.filter(
        Q(start_date__lte=semester.end_date),
        Q(end_date__gte=semester.start_date) | Q(end_date__isnull=True),
        role__is_eligible_for_ects=True
    ).select_related('person', 'role')

    # Group by person
    persons_map = {}
    for pr in person_roles:
        if pr.person not in persons_map:
            persons_map[pr.person] = []
        persons_map[pr.person].append(pr)

    created_count = 0
    updated_count = 0
    skipped_count = 0

    for person, their_roles in persons_map.items():
        # Check if entry already exists
        existing = AuditEntry.objects.filter(
            audit_semester=audit_semester,
            person=person
        ).first()

        # Skip if entry exists and has been manually checked
        if existing and existing.checked_at is not None:
            skipped_count += 1
            continue

        # Calculate aliquoted ECTS for each role
        role_calcs = []
        for pr in their_roles:
            aliquoted = calculate_aliquoted_ects(pr, semester)

            role_calcs.append({
                'role_name': pr.role.name,
                'person_role_id': pr.id,
                'nominal_ects': float(pr.role.max_ects_per_semester),
                'held_from': pr.start_date.isoformat(),
                'held_to': pr.end_date.isoformat() if pr.end_date else 'ongoing',
                'aliquoted_ects': float(aliquoted),
            })

        # Max ECTS = highest role (not sum)
        if role_calcs:
            aliquoted_ects = max(Decimal(str(rc['aliquoted_ects'])) for rc in role_calcs)
        else:
            aliquoted_ects = Decimal('0.00')

        # Apply semester bonus/malus to get final ECTS
        final_ects = aliquoted_ects + Decimal(str(semester.ects_adjustment))

        # Ensure final_ects is not negative
        if final_ects < 0:
            final_ects = Decimal('0.00')

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

        # Calculate remaining ECTS
        remaining_ects = max(final_ects - total_reimbursed, Decimal('0.00'))

        calc_details = {
            'roles': role_calcs,
            'aliquoted_ects': float(aliquoted_ects),
            'bonus_malus': float(semester.ects_adjustment),
            'final_ects': float(final_ects),
            'calculation_date': timezone.now().isoformat(),
            'approved_requests_count': len(approved_requests_filtered)
        }

        if existing:
            # Update existing entry (only if not checked)
            existing.aliquoted_ects = aliquoted_ects
            existing.final_ects = final_ects
            existing.reimbursed_ects = total_reimbursed
            existing.remaining_ects = remaining_ects
            existing.calculation_details = calc_details
            existing.save()

            # Update M2M relationships
            existing.person_roles.set(their_roles)
            existing.inbox_requests.set(approved_requests_filtered)

            updated_count += 1
        else:
            # Create new audit entry
            entry = AuditEntry.objects.create(
                audit_semester=audit_semester,
                person=person,
                aliquoted_ects=aliquoted_ects,
                final_ects=final_ects,
                reimbursed_ects=total_reimbursed,
                remaining_ects=remaining_ects,
                calculation_details=calc_details
            )

            # Update M2M relationships
            entry.person_roles.set(their_roles)
            entry.inbox_requests.set(approved_requests_filtered)

            created_count += 1

    return created_count, updated_count, skipped_count
