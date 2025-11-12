from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import date, timedelta
from decimal import Decimal

from people.models import Person, Role, PersonRole
from academia.models import Semester, InboxRequest, InboxCourse
from .models import AuditSemester, AuditEntry
from .utils import synchronize_audit_entries
from hankosign.models import Action, Signature, Signatory
from django.contrib.auth import get_user_model

User = get_user_model()


class AuditSemesterTestCase(TestCase):
    def setUp(self):
        self.semester = Semester.objects.create(
            code="WS24",
            display_name="Winter Semester 2024/25",
            start_date=date(2024, 10, 1),
            end_date=date(2025, 1, 31),
        )

    def test_audit_semester_creation(self):
        """Test creating an AuditSemester linked to a Semester"""
        audit_semester = AuditSemester.objects.create(
            semester=self.semester
        )
        self.assertEqual(audit_semester.semester, self.semester)
        self.assertIsNone(audit_semester.audit_sent_university_at)

    def test_one_to_one_relationship(self):
        """Test that only one AuditSemester can exist per Semester"""
        AuditSemester.objects.create(semester=self.semester)

        # Trying to create another should fail
        with self.assertRaises(Exception):
            AuditSemester.objects.create(semester=self.semester)

    def test_audit_semester_locking(self):
        """Test that locking audit semester cascades to entries"""
        audit_semester = AuditSemester.objects.create(
            semester=self.semester,
            is_locked=False
        )

        person = Person.objects.create(
            first_name="Test",
            last_name="Person"
        )

        entry = AuditEntry.objects.create(
            audit_semester=audit_semester,
            person=person,
            aliquoted_ects=Decimal('12.00'),
            final_ects=Decimal('12.00'),
            reimbursed_ects=Decimal('0.00'),
            remaining_ects=Decimal('12.00')
        )

        # Lock the audit semester
        audit_semester.is_locked = True
        audit_semester.save()

        # Trying to save entry should fail validation
        entry.final_ects = Decimal('10.00')
        with self.assertRaises(ValidationError):
            entry.clean()


class AuditEntryTestCase(TestCase):
    def setUp(self):
        self.semester = Semester.objects.create(
            code="WS24",
            display_name="Winter Semester 2024/25",
            start_date=date(2024, 10, 1),
                end_date=date(2025, 1, 31),
            ects_adjustment=Decimal('0.00')
        )

        self.audit_semester = AuditSemester.objects.create(
            semester=self.semester
        )

        self.person = Person.objects.create(
            first_name="Anna",
            last_name="Test"
        )

        self.role = Role.objects.create(
            name="Student Representative",
            short_name="SR",
            ects_cap=Decimal('12.00')
        )

    def test_audit_entry_creation(self):
        """Test creating an AuditEntry with calculations"""
        entry = AuditEntry.objects.create(
            audit_semester=self.audit_semester,
            person=self.person,
            aliquoted_ects=Decimal('12.00'),
            final_ects=Decimal('12.00'),
            reimbursed_ects=Decimal('5.00'),
            remaining_ects=Decimal('7.00')
        )

        self.assertEqual(entry.aliquoted_ects, Decimal('12.00'))
        self.assertEqual(entry.final_ects, Decimal('12.00'))
        self.assertEqual(entry.reimbursed_ects, Decimal('5.00'))
        self.assertEqual(entry.remaining_ects, Decimal('7.00'))

    def test_checked_at_timestamp(self):
        """Test that checked_at can be set to mark manual review"""
        entry = AuditEntry.objects.create(
            audit_semester=self.audit_semester,
            person=self.person,
            aliquoted_ects=Decimal('12.00'),
            final_ects=Decimal('12.00'),
            reimbursed_ects=Decimal('0.00'),
            remaining_ects=Decimal('12.00')
        )

        self.assertIsNone(entry.checked_at)

        # Mark as checked
        entry.checked_at = timezone.now()
        entry.save()

        self.assertIsNotNone(entry.checked_at)

    def test_calculation_details_json(self):
        """Test that calculation_details stores JSON properly"""
        entry = AuditEntry.objects.create(
            audit_semester=self.audit_semester,
            person=self.person,
            aliquoted_ects=Decimal('12.00'),
            final_ects=Decimal('12.00'),
            reimbursed_ects=Decimal('0.00'),
            remaining_ects=Decimal('12.00'),
            calculation_details={
                'roles': [
                    {
                        'role_name': 'Test Role',
                        'aliquoted_ects': 12.00
                    }
                ],
                'bonus_malus': 0.00
            }
        )

        self.assertIsInstance(entry.calculation_details, dict)
        self.assertIn('roles', entry.calculation_details)
        self.assertEqual(entry.calculation_details['bonus_malus'], 0.00)


class SynchronizeAuditEntriesTestCase(TestCase):
    def setUp(self):
        self.semester = Semester.objects.create(
            code="WS24",
            display_name="Winter Semester 2024/25",
            start_date=date(2024, 10, 1),
                end_date=date(2025, 1, 31),
            ects_adjustment=Decimal('0.00')
        )

        self.audit_semester = AuditSemester.objects.create(
            semester=self.semester
        )

        self.person1 = Person.objects.create(
            first_name="Anna",
            last_name="Müller"
        )

        self.person2 = Person.objects.create(
            first_name="Max",
            last_name="Schmidt"
        )

        self.role = Role.objects.create(
            name="Student Rep",
            short_name="SR",
            ects_cap=Decimal('12.00')
        )

        self.person_role1 = PersonRole.objects.create(
            person=self.person1,
            role=self.role,
            start_date=date(2024, 10, 1),
            end_date=date(2025, 1, 31),
        )

        self.person_role2 = PersonRole.objects.create(
            person=self.person2,
            role=self.role,
            start_date=date(2024, 10, 1),
            end_date=date(2025, 1, 31),
        )

    def test_synchronize_creates_new_entries(self):
        """Test that synchronize creates new AuditEntry records"""
        created, updated, skipped = synchronize_audit_entries(self.audit_semester)

        self.assertEqual(created, 2)  # Two people
        self.assertEqual(updated, 0)
        self.assertEqual(skipped, 0)

        entries = AuditEntry.objects.filter(audit_semester=self.audit_semester)
        self.assertEqual(entries.count(), 2)

    def test_synchronize_idempotency(self):
        """Test that running synchronize multiple times is safe (idempotent)"""
        # First run
        created1, updated1, skipped1 = synchronize_audit_entries(self.audit_semester)
        self.assertEqual(created1, 2)

        # Second run - should update unchecked entries
        created2, updated2, skipped2 = synchronize_audit_entries(self.audit_semester)
        self.assertEqual(created2, 0)
        self.assertEqual(updated2, 2)  # Updates both unchecked entries
        self.assertEqual(skipped2, 0)

    def test_synchronize_preserves_checked_entries(self):
        """Test that synchronize skips entries that have been manually checked"""
        # First synchronize
        created, updated, skipped = synchronize_audit_entries(self.audit_semester)
        self.assertEqual(created, 2)

        # Mark one entry as checked
        entry1 = AuditEntry.objects.filter(person=self.person1).first()
        entry1.checked_at = timezone.now()
        entry1.final_ects = Decimal('10.00')  # Manual adjustment
        entry1.save()

        # Second synchronize
        created2, updated2, skipped2 = synchronize_audit_entries(self.audit_semester)
        self.assertEqual(created2, 0)
        self.assertEqual(updated2, 1)  # Only person2's entry updated
        self.assertEqual(skipped2, 1)  # person1's entry skipped

        # Verify manual adjustment preserved
        entry1.refresh_from_db()
        self.assertEqual(entry1.final_ects, Decimal('10.00'))

    def test_synchronize_calculates_aliquoted_ects(self):
        """Test that synchronize correctly calculates aliquoted ECTS"""
        # Create person role for partial semester (50%)
        person3 = Person.objects.create(
            first_name="Test",
            last_name="Partial"
        )
        PersonRole.objects.create(
            person=person3,
            role=self.role,
            start_date=date(2024, 10, 1),
            end_date=date(2025, 1, 31),
        )

        created, updated, skipped = synchronize_audit_entries(self.audit_semester)

        entry = AuditEntry.objects.get(person=person3)
        # Should be approximately 6 ECTS (50% of 12)
        self.assertGreater(entry.aliquoted_ects, Decimal('5.50'))
        self.assertLess(entry.aliquoted_ects, Decimal('6.50'))

    def test_synchronize_applies_bonus_malus(self):
        """Test that synchronize applies semester bonus/malus"""
        self.semester.ects_adjustment = Decimal('2.00')  # Bonus
        self.semester.save()

        created, updated, skipped = synchronize_audit_entries(self.audit_semester)

        entry = AuditEntry.objects.filter(person=self.person1).first()
        # final_ects should be aliquoted (12) + bonus (2) = 14
        self.assertEqual(entry.final_ects, Decimal('14.00'))

    def test_synchronize_with_approved_requests(self):
        """Test that synchronize counts reimbursed ECTS from approved requests"""
        # Create user and signatory for signatures
        user = User.objects.create_user(username="chair", password="test")
        signatory = Signatory.objects.create(user=user, label="Chair")

        # Create an InboxRequest with courses
        request = InboxRequest.objects.create(
            semester=self.semester,
            person_role=self.person_role1
        )

        InboxCourse.objects.create(
            inbox_request=request,
            course_code="CS101",
            course_name="Test Course",
            ects_amount=Decimal('5.00')
        )

        # Create APPROVE:CHAIR action and signature
        action = Action.objects.get_or_create(
            verb='APPROVE',
            stage='CHAIR',
            scope='academia.InboxRequest'
        )[0]

        Signature.objects.create(
            content_object=request,
            action=action,
            signatory=signatory,
            signed_at=timezone.now()
        )

        # Synchronize
        created, updated, skipped = synchronize_audit_entries(self.audit_semester)

        entry = AuditEntry.objects.get(person=self.person1)
        self.assertEqual(entry.reimbursed_ects, Decimal('5.00'))
        self.assertEqual(entry.remaining_ects, Decimal('7.00'))  # 12 - 5

    def test_synchronize_max_ects_not_sum(self):
        """Test that with multiple roles, synchronize uses MAX not SUM"""
        # Add second role with higher ECTS
        role2 = Role.objects.create(
            name="Board Member",
            short_name="BM",
            ects_cap=Decimal('15.00')
        )

        PersonRole.objects.create(
            person=self.person1,
            role=role2,
            start_date=date(2024, 10, 1),
            end_date=date(2025, 1, 31),
        )

        created, updated, skipped = synchronize_audit_entries(self.audit_semester)

        entry = AuditEntry.objects.get(person=self.person1)
        # Should be 15 (max), not 27 (sum of 12 + 15)
        self.assertEqual(entry.aliquoted_ects, Decimal('15.00'))

    def test_synchronize_only_eligible_roles(self):
        """Test that synchronize only includes roles eligible for ECTS"""
        # Create ineligible role
        ineligible_role = Role.objects.create(
            name="Volunteer",
            short_name="VOL",
            ects_cap=Decimal('0.00')
        )

        person3 = Person.objects.create(
            first_name="Test",
            last_name="Volunteer"
        )

        PersonRole.objects.create(
            person=person3,
            role=ineligible_role,
            start_date=date(2024, 10, 1),
            end_date=date(2025, 1, 31),
        )

        created, updated, skipped = synchronize_audit_entries(self.audit_semester)

        # Should not create entry for person3
        self.assertEqual(created, 2)  # Only person1 and person2
        self.assertFalse(
            AuditEntry.objects.filter(person=person3).exists()
        )

    def test_synchronize_prevents_negative_ects(self):
        """Test that negative final_ects is clamped to zero"""
        self.semester.ects_adjustment = Decimal('-20.00')  # Large malus
        self.semester.save()

        created, updated, skipped = synchronize_audit_entries(self.audit_semester)

        entry = AuditEntry.objects.filter(person=self.person1).first()
        # Should be 0, not negative
        self.assertEqual(entry.final_ects, Decimal('0.00'))
        self.assertGreaterEqual(entry.final_ects, Decimal('0.00'))


class AuditEntryM2MTestCase(TestCase):
    def setUp(self):
        self.semester = Semester.objects.create(
            code="WS24",
            display_name="Winter Semester 2024/25",
            start_date=date(2024, 10, 1),
            end_date=date(2025, 1, 31),
        )

        self.audit_semester = AuditSemester.objects.create(
            semester=self.semester
        )

        self.person = Person.objects.create(
            first_name="Test",
            last_name="Person"
        )

        self.role = Role.objects.create(
            name="Test Role",
            short_name="TR",
            ects_cap=Decimal('12.00')
        )

        self.person_role = PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2024, 10, 1)
        )

    def test_audit_entry_person_roles_relationship(self):
        """Test M2M relationship between AuditEntry and PersonRoles"""
        entry = AuditEntry.objects.create(
            audit_semester=self.audit_semester,
            person=self.person,
            aliquoted_ects=Decimal('12.00'),
            final_ects=Decimal('12.00'),
            reimbursed_ects=Decimal('0.00'),
            remaining_ects=Decimal('12.00')
        )

        entry.person_roles.add(self.person_role)
        self.assertEqual(entry.person_roles.count(), 1)
        self.assertIn(self.person_role, entry.person_roles.all())

    def test_audit_entry_inbox_requests_relationship(self):
        """Test M2M relationship between AuditEntry and InboxRequests"""
        request = InboxRequest.objects.create(
            semester=self.semester,
            person_role=self.person_role
        )

        entry = AuditEntry.objects.create(
            audit_semester=self.audit_semester,
            person=self.person,
            aliquoted_ects=Decimal('12.00'),
            final_ects=Decimal('12.00'),
            reimbursed_ects=Decimal('0.00'),
            remaining_ects=Decimal('12.00')
        )

        entry.inbox_requests.add(request)
        self.assertEqual(entry.inbox_requests.count(), 1)
        self.assertIn(request, entry.inbox_requests.all())
