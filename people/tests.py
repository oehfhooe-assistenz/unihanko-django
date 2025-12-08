# File: people/tests.py
# Version: 1.0.2
# Author: vas
# Created: 2025-12-08

from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.contrib.auth import get_user_model
from decimal import Decimal
from datetime import date, timedelta
from people.models import Person, Role, RoleTransitionReason, PersonRole

User = get_user_model()


class PersonModelTest(TestCase):
    """Test Person model validation and behavior."""

    def test_person_creation_generates_access_code(self):
        """Access code is auto-generated on creation."""
        person = Person.objects.create(
            first_name="John",
            last_name="Doe"
        )
        self.assertTrue(person.personal_access_code)
        self.assertIn("-", person.personal_access_code)
        self.assertEqual(len(person.personal_access_code.replace("-", "")), 8)

    def test_access_code_uniqueness(self):
        """Each person gets a unique access code."""
        person1 = Person.objects.create(first_name="A", last_name="B")
        person2 = Person.objects.create(first_name="C", last_name="D")
        self.assertNotEqual(person1.personal_access_code, person2.personal_access_code)

    def test_access_code_regeneration(self):
        """Access codes can be regenerated."""
        person = Person.objects.create(first_name="John", last_name="Doe")
        old_code = person.personal_access_code
        new_code = person.regenerate_access_code()
        self.assertNotEqual(old_code, new_code)
        person.refresh_from_db()
        self.assertEqual(person.personal_access_code, new_code)

    def test_matric_no_fh_format_valid(self):
        """FH matriculation numbers (s + 10 digits) are valid."""
        person = Person(
            first_name="Student",
            last_name="Test",
            matric_no="s2210562023"
        )
        person.full_clean()  # Should not raise

    def test_matric_no_federal_format_valid(self):
        """Federal matriculation numbers (up to 10 digits) are valid."""
        person = Person(
            first_name="Student",
            last_name="Test",
            matric_no="52103904"
        )
        person.full_clean()  # Should not raise

    def test_matric_no_invalid_format(self):
        """Invalid matriculation number formats are rejected."""
        person = Person(
            first_name="Student",
            last_name="Test",
            matric_no="invalid123"
        )
        with self.assertRaises(ValidationError):
            person.full_clean()

    def test_matric_no_duplicate_prevented(self):
        """Duplicate matriculation numbers are prevented atomically."""
        Person.objects.create(
            first_name="First",
            last_name="Student",
            matric_no="s1234567890"
        )
        
        person2 = Person(
            first_name="Second",
            last_name="Student",
            matric_no="s1234567890"
        )
        
        with self.assertRaises(ValidationError) as cm:
            person2.save()
        
        self.assertIn("matric_no", str(cm.exception))

    def test_matric_no_null_allowed(self):
        """Multiple persons can have null matric_no."""
        person1 = Person.objects.create(first_name="A", last_name="B", matric_no=None)
        person2 = Person.objects.create(first_name="C", last_name="D", matric_no=None)
        self.assertIsNone(person1.matric_no)
        self.assertIsNone(person2.matric_no)

    def test_email_uniqueness_enforced(self):
        """Non-empty emails must be unique."""
        Person.objects.create(
            first_name="First",
            last_name="User",
            email="test@example.com"
        )
        
        # Duplicate email should fail at DB level
        with self.assertRaises(IntegrityError):
            Person.objects.create(
                first_name="Second",
                last_name="User",
                email="test@example.com"
            )

    def test_empty_emails_allowed(self):
        """Multiple persons can have empty/blank emails."""
        person1 = Person.objects.create(first_name="A", last_name="B", email="")
        person2 = Person.objects.create(first_name="C", last_name="D", email="")
        self.assertEqual(person1.email, "")
        self.assertEqual(person2.email, "")

    def test_user_link_optional(self):
        """Django user link is optional."""
        person = Person.objects.create(first_name="John", last_name="Doe")
        self.assertIsNone(person.user)

    def test_user_link_one_to_one(self):
        """One person per Django user."""
        user = User.objects.create_user(username="testuser")
        person = Person.objects.create(
            first_name="John",
            last_name="Doe",
            user=user
        )
        self.assertEqual(person.user, user)
        self.assertEqual(user.person, person)

    def test_person_str_representation(self):
        """String representation is 'Last, First'."""
        person = Person.objects.create(first_name="John", last_name="Doe")
        self.assertEqual(str(person), "Doe, John")

    def test_person_ordering(self):
        """Persons are ordered by last name, then first name."""
        Person.objects.create(first_name="Charlie", last_name="Brown")
        Person.objects.create(first_name="Alice", last_name="Anderson")
        Person.objects.create(first_name="Bob", last_name="Brown")
        
        people = list(Person.objects.all())
        self.assertEqual(people[0].last_name, "Anderson")
        self.assertEqual(people[1].first_name, "Bob")
        self.assertEqual(people[2].first_name, "Charlie")


class RoleModelTest(TestCase):
    """Test Role model validation and behavior."""

    def test_role_creation(self):
        """Basic role creation works."""
        role = Role.objects.create(name="Test Role")
        self.assertEqual(role.name, "Test Role")
        self.assertEqual(role.kind, Role.Kind.OTHER)
        self.assertFalse(role.is_system)

    def test_system_role_must_be_other_kind(self):
        """System roles must have OTHER kind."""
        role = Role(
            name="System Role",
            is_system=True,
            kind=Role.Kind.DEPT_HEAD
        )
        with self.assertRaises(ValidationError) as cm:
            role.full_clean()
        self.assertIn("kind", str(cm.exception))

    def test_system_role_cannot_be_stipend_reimbursed(self):
        """System roles cannot be stipend-reimbursed."""
        role = Role(
            name="System Role",
            is_system=True,
            is_stipend_reimbursed=True
        )
        with self.assertRaises(ValidationError) as cm:
            role.full_clean()
        self.assertIn("is_stipend_reimbursed", str(cm.exception))

    def test_system_role_cannot_have_monthly_amount(self):
        """System roles cannot have default monthly amount."""
        role = Role(
            name="System Role",
            is_system=True,
            default_monthly_amount=Decimal("500.00")
        )
        with self.assertRaises(ValidationError) as cm:
            role.full_clean()
        self.assertIn("default_monthly_amount", str(cm.exception))

    def test_system_role_cannot_have_ects_cap(self):
        """System roles must have zero ECTS cap."""
        role = Role(
            name="System Role",
            is_system=True,
            ects_cap=Decimal("5.0")
        )
        with self.assertRaises(ValidationError) as cm:
            role.full_clean()
        self.assertIn("ects_cap", str(cm.exception))

    def test_kind_label_system_role(self):
        """System roles show 'Other/System' kind label."""
        role = Role.objects.create(
            name="System Role",
            is_system=True,
            kind=Role.Kind.OTHER
        )
        self.assertIn("System", role.kind_label)

    def test_kind_label_normal_role(self):
        """Normal roles show their kind display."""
        role = Role.objects.create(
            name="Department Head",
            kind=Role.Kind.DEPT_HEAD
        )
        self.assertIn("Department head", role.kind_label)

    def test_is_financially_relevant(self):
        """Financial relevance logic works."""
        # Stipend + not system = financially relevant
        role1 = Role.objects.create(
            name="Paid Role",
            is_stipend_reimbursed=True,
            is_system=False
        )
        self.assertTrue(role1.is_financially_relevant)
        
        # System role = not financially relevant
        role2 = Role.objects.create(
            name="System Role",
            is_stipend_reimbursed=False,
            is_system=True
        )
        self.assertFalse(role2.is_financially_relevant)
        
        # No stipend = not financially relevant
        role3 = Role.objects.create(
            name="Unpaid Role",
            is_stipend_reimbursed=False,
            is_system=False
        )
        self.assertFalse(role3.is_financially_relevant)

    def test_short_name_validation(self):
        """Short names cannot contain digits."""
        role = Role(name="Test", short_name="ABC123")
        with self.assertRaises(ValidationError):
            role.full_clean()

    def test_role_str_representation(self):
        """String representation is the name."""
        role = Role.objects.create(name="Wirtschaftsreferent")
        self.assertEqual(str(role), "Wirtschaftsreferent")


class RoleTransitionReasonTest(TestCase):
    """Test RoleTransitionReason model validation."""

    def test_reason_creation(self):
        """Basic reason creation works."""
        reason = RoleTransitionReason.objects.create(
            code="I01",
            name="Eintritt"
        )
        self.assertEqual(reason.code, "I01")
        self.assertEqual(reason.name, "Eintritt")

    def test_code_normalized_to_uppercase(self):
        """Codes are normalized to uppercase."""
        reason = RoleTransitionReason.objects.create(
            code="i01",
            name="Test"
        )
        self.assertEqual(reason.code, "I01")

    def test_valid_code_formats(self):
        """Valid code formats are accepted."""
        valid_codes = ["I01", "O99", "C15", "X99"]
        for code in valid_codes:
            reason = RoleTransitionReason(code=code, name="Test")
            reason.full_clean()  # Should not raise

    def test_invalid_code_format(self):
        """Invalid code formats are rejected."""
        invalid_codes = ["I1", "O999", "ABC", "X98", "123"]
        for code in invalid_codes:
            reason = RoleTransitionReason(code=code, name="Test")
            with self.assertRaises(ValidationError):
                reason.full_clean()

    def test_display_name_german(self):
        """Display name returns based on current language."""
        reason = RoleTransitionReason.objects.create(
            code="I01",
            name="Eintritt",
            name_en="Entry"
        )
        # Test environment is English, so it returns English name
        self.assertEqual(reason.display_name, "Entry")
        
        # Falls back to German if no English translation
        reason_no_en = RoleTransitionReason.objects.create(
            code="O01",
            name="Austritt"
        )
        self.assertEqual(reason_no_en.display_name, "Austritt")

    def test_reason_str_representation(self):
        """String representation shows code and name."""
        reason = RoleTransitionReason.objects.create(
            code="O01",
            name="Austritt"
        )
        self.assertIn("O01", str(reason))
        self.assertIn("Austritt", str(reason))


class PersonRoleModelTest(TestCase):
    """Test PersonRole model validation and behavior."""

    def setUp(self):
        """Create test data."""
        self.person = Person.objects.create(
            first_name="John",
            last_name="Doe"
        )
        self.role = Role.objects.create(name="Test Role")
        self.system_role = Role.objects.create(
            name="System Role",
            is_system=True
        )
        self.start_reason = RoleTransitionReason.objects.create(
            code="I01",
            name="Eintritt"
        )
        self.end_reason = RoleTransitionReason.objects.create(
            code="O01",
            name="Austritt"
        )

    def test_assignment_creation(self):
        """Basic assignment creation works."""
        assignment = PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2024, 1, 1)
        )
        self.assertEqual(assignment.person, self.person)
        self.assertEqual(assignment.role, self.role)
        self.assertTrue(assignment.is_active)

    def test_duplicate_assignment_prevented(self):
        """Duplicate (person, role, start_date) prevented atomically."""
        PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2024, 1, 1)
        )
        
        assignment2 = PersonRole(
            person=self.person,
            role=self.role,
            start_date=date(2024, 1, 1)
        )
        
        with self.assertRaises(ValidationError) as cm:
            assignment2.save()
        
        self.assertIn("already exists", str(cm.exception).lower())

    def test_same_person_role_different_start_dates_allowed(self):
        """Same person/role with different start dates is allowed."""
        PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
            end_reason=self.end_reason
        )
        
        assignment2 = PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2024, 7, 1)
        )
        
        self.assertEqual(PersonRole.objects.filter(
            person=self.person,
            role=self.role
        ).count(), 2)

    def test_end_date_requires_end_reason(self):
        """End date requires an end reason."""
        assignment = PersonRole(
            person=self.person,
            role=self.role,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31)
        )
        with self.assertRaises(ValidationError) as cm:
            assignment.full_clean()
        self.assertIn("end_reason", str(cm.exception).lower())

    def test_end_reason_requires_end_date(self):
        """End reason requires an end date."""
        assignment = PersonRole(
            person=self.person,
            role=self.role,
            start_date=date(2024, 1, 1),
            end_reason=self.end_reason
        )
        with self.assertRaises(ValidationError) as cm:
            assignment.full_clean()
        self.assertIn("end_reason", str(cm.exception).lower())

    def test_start_reason_must_be_I_code(self):
        """Start reason must be I## or X99."""
        assignment = PersonRole(
            person=self.person,
            role=self.role,
            start_date=date(2024, 1, 1),
            start_reason=self.end_reason  # O01 - wrong type
        )
        with self.assertRaises(ValidationError) as cm:
            assignment.full_clean()
        self.assertIn("start_reason", str(cm.exception).lower())

    def test_end_reason_must_be_O_code(self):
        """End reason must be O## or X99."""
        assignment = PersonRole(
            person=self.person,
            role=self.role,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            end_reason=self.start_reason  # I01 - wrong type
        )
        with self.assertRaises(ValidationError) as cm:
            assignment.full_clean()
        self.assertIn("end_reason", str(cm.exception).lower())

    def test_start_and_end_reason_cannot_be_same(self):
        """Start and end reason cannot be the same (except X99)."""
        other_reason = RoleTransitionReason.objects.create(
            code="X99",
            name="Other"
        )
        
        assignment = PersonRole(
            person=self.person,
            role=self.role,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            start_reason=other_reason,
            end_reason=other_reason
        )
        # X99 is allowed to be the same
        assignment.full_clean()  # Should not raise

    def test_system_role_no_confirmation(self):
        """System roles cannot have confirmation date."""
        assignment = PersonRole(
            person=self.person,
            role=self.system_role,
            start_date=date(2024, 1, 1),
            confirm_date=date(2024, 1, 15)
        )
        with self.assertRaises(ValidationError) as cm:
            assignment.full_clean()
        self.assertIn("confirm_date", str(cm.exception).lower())

    def test_system_role_no_effective_dates(self):
        """System roles cannot have effective dates."""
        assignment = PersonRole(
            person=self.person,
            role=self.system_role,
            start_date=date(2024, 1, 1),
            effective_start=date(2024, 1, 15)
        )
        with self.assertRaises(ValidationError) as cm:
            assignment.full_clean()
        self.assertIn("effective", str(cm.exception).lower())

    def test_elected_via_requires_confirm_date(self):
        """elected_via requires a confirmation date."""
        from assembly.models import Term, Session, SessionItem
        
        term = Term.objects.create(
            start_date=date(2024, 1, 1),
            label="Test Term 2024-2026"
        )
        session = Session.objects.create(
            term=term,
            session_date=date(2024, 1, 15)
        )
        item = SessionItem.objects.create(
            session=session,
            order=1,
            kind=SessionItem.Kind.ELECTION,
            title="Test Election"
        )
        
        assignment = PersonRole(
            person=self.person,
            role=self.role,
            start_date=date(2024, 1, 1),
            elected_via=item
        )
        with self.assertRaises(ValidationError) as cm:
            assignment.full_clean()
        self.assertIn("confirm_date", str(cm.exception).lower())

    def test_end_date_must_be_after_start_date(self):
        """End date must be >= start date (DB constraint)."""
        with self.assertRaises(IntegrityError):
            PersonRole.objects.create(
                person=self.person,
                role=self.role,
                start_date=date(2024, 12, 31),
                end_date=date(2024, 1, 1),
                end_reason=self.end_reason
            )

    def test_effective_start_must_be_after_start_date(self):
        """Effective start must be >= start date (DB constraint)."""
        with self.assertRaises(IntegrityError):
            PersonRole.objects.create(
                person=self.person,
                role=self.role,
                start_date=date(2024, 12, 31),
                effective_start=date(2024, 1, 1)
            )

    def test_is_active_property(self):
        """is_active property reflects end_date status."""
        active = PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2024, 1, 1)
        )
        self.assertTrue(active.is_active)
        
        inactive = PersonRole.objects.create(
            person=Person.objects.create(first_name="Jane", last_name="Doe"),
            role=self.role,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
            end_reason=self.end_reason
        )
        self.assertFalse(inactive.is_active)

    def test_assignment_str_representation(self):
        """String representation shows person, role, and dates."""
        assignment = PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            end_reason=self.end_reason
        )
        s = str(assignment)
        self.assertIn("Doe, John", s)
        self.assertIn("Test Role", s)
        self.assertIn("2024-01-01", s)
        self.assertIn("2024-12-31", s)

    def test_assignment_ordering(self):
        """Assignments are ordered by start_date descending."""
        PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2024, 1, 1)
        )
        PersonRole.objects.create(
            person=self.person,
            role=Role.objects.create(name="Other Role"),
            start_date=date(2024, 6, 1)
        )
        
        assignments = list(PersonRole.objects.all())
        self.assertEqual(assignments[0].start_date, date(2024, 6, 1))
        self.assertEqual(assignments[1].start_date, date(2024, 1, 1))


class ConcurrencyTest(TestCase):
    """Test race condition handling (PostgreSQL only)."""

    def setUp(self):
        """Create test data."""
        self.person = Person.objects.create(
            first_name="Concurrent",
            last_name="Test"
        )
        self.role = Role.objects.create(name="Concurrent Role")

    def test_concurrent_person_role_creation(self):
        """Concurrent PersonRole creation is prevented."""
        from django.db import connection
        
        # Skip test if not PostgreSQL
        if connection.vendor != 'postgresql':
            self.skipTest("PostgreSQL-specific test")
        
        from threading import Thread, Barrier
        import time
        
        barrier = Barrier(2)
        results = []
        
        def create_assignment():
            try:
                barrier.wait()  # Sync both threads
                assignment = PersonRole.objects.create(
                    person=self.person,
                    role=self.role,
                    start_date=date(2024, 1, 1)
                )
                results.append(("success", assignment.id))
            except (ValidationError, IntegrityError) as e:
                results.append(("error", str(e)))
        
        t1 = Thread(target=create_assignment)
        t2 = Thread(target=create_assignment)
        
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        # One should succeed, one should fail
        successes = [r for r in results if r[0] == "success"]
        errors = [r for r in results if r[0] == "error"]
        
        self.assertEqual(len(successes), 1, "Exactly one creation should succeed")
        self.assertEqual(len(errors), 1, "Exactly one creation should fail")
        
        # Verify only one record in DB
        self.assertEqual(
            PersonRole.objects.filter(
                person=self.person,
                role=self.role,
                start_date=date(2024, 1, 1)
            ).count(),
            1
        )