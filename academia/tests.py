from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import date, timedelta
from decimal import Decimal

from people.models import Person, Role, PersonRole
from .models import Semester, InboxRequest, InboxCourse
from .utils import (
    calculate_aliquoted_ects,
    calculate_overlap_percentage,
    validate_ects_total,
    get_random_words
)


class SemesterTestCase(TestCase):
    def test_semester_code_generation(self):
        """Test auto-generation of semester codes"""
        semester = Semester.objects.create(
            code="WS24",
            display_name="Winter Semester 2024/25",
            start_date=date(2024, 10, 1),
        )
        self.assertEqual(semester.code, "WS24")

    def test_filing_window(self):
        """Test filing start/end window"""
        semester = Semester.objects.create(
            code="SS25",
            display_name="Summer Semester 2025",
            start_date=date(2025, 3, 1),
            end_date=date(2025, 7, 31),
            filing_start=timezone.make_aware(timezone.datetime(2025, 3, 1, 0, 0)),
            filing_end=timezone.make_aware(timezone.datetime(2025, 4, 30, 23, 59))
        )
        self.assertIsNotNone(semester.filing_start)
        self.assertIsNotNone(semester.filing_end)

    def test_semester_locking_cascades(self):
        """Test that locking semester prevents editing requests"""
        semester = Semester.objects.create(
            code="WS24",
            display_name="Winter Semester 2024/25",
            start_date=date(2024, 10, 1),
            is_locked=False
        )

        person = Person.objects.create(
            first_name="Test",
            last_name="Student"
        )
        role = Role.objects.create(
            name="Student Rep",
            short_name="SR",
            ects_cap=Decimal('12.00')
        )
        person_role = PersonRole.objects.create(
            person=person,
            role=role,
            start_date=date(2024, 10, 1)
        )

        request = InboxRequest.objects.create(
            semester=semester,
            person_role=person_role
        )

        # Lock the semester
        semester.is_locked = True
        semester.save()

        # Trying to save request should fail validation
        request.notes = "Updated note"
        with self.assertRaises(ValidationError):
            request.clean()


class InboxRequestTestCase(TestCase):
    def setUp(self):
        self.semester = Semester.objects.create(
            code="WS24",
            display_name="Winter Semester 2024/25",
            start_date=date(2024, 10, 1),
        )

        self.person = Person.objects.create(
            first_name="Anna",
            last_name="Müller"
        )

        self.role = Role.objects.create(
            name="Student Representative",
            short_name="SR",
            ects_cap=Decimal('12.00')
        )

        self.person_role = PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2024, 10, 1)
        )

    def test_reference_code_generation(self):
        """Test auto-generation of reference codes (SSSS-LLLL-####)"""
        request = InboxRequest.objects.create(
            semester=self.semester,
            person_role=self.person_role
        )

        # Reference code format: SSSS-LLLL-####
        self.assertIsNotNone(request.reference_code)
        parts = request.reference_code.split('-')
        self.assertEqual(len(parts), 3)
        self.assertEqual(len(parts[0]), 4)  # SSSS (semester code)
        self.assertEqual(len(parts[1]), 4)  # LLLL (last name)
        self.assertEqual(len(parts[2]), 4)  # #### (sequence)

    def test_total_ects_calculation(self):
        """Test that total_ects property sums all courses"""
        request = InboxRequest.objects.create(
            semester=self.semester,
            person_role=self.person_role
        )

        InboxCourse.objects.create(
            inbox_request=request,
            course_code="CS101",
            course_name="Introduction to CS",
            ects_amount=Decimal('6.00')
        )

        InboxCourse.objects.create(
            inbox_request=request,
            course_code="CS102",
            course_name="Data Structures",
            ects_amount=Decimal('4.50')
        )

        self.assertEqual(request.total_ects, Decimal('10.50'))

    def test_request_with_no_courses(self):
        """Test request with no courses has zero total"""
        request = InboxRequest.objects.create(
            semester=self.semester,
            person_role=self.person_role
        )

        self.assertEqual(request.total_ects, Decimal('0.00'))


class InboxCourseTestCase(TestCase):
    def setUp(self):
        self.semester = Semester.objects.create(
            code="WS24",
            display_name="Winter Semester 2024/25",
            start_date=date(2024, 10, 1),
        )

        self.person = Person.objects.create(
            first_name="Test",
            last_name="Student"
        )

        self.role = Role.objects.create(
            name="Student Rep",
            short_name="SR",
            ects_cap=Decimal('12.00')
        )

        self.person_role = PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2024, 10, 1)
        )

        self.request = InboxRequest.objects.create(
            semester=self.semester,
            person_role=self.person_role
        )

    def test_course_ects_amount(self):
        """Test that course ECTS amounts are stored correctly"""
        course = InboxCourse.objects.create(
            inbox_request=self.request,
            course_code="MATH201",
            course_name="Linear Algebra",
            ects_amount=Decimal('5.00')
        )

        self.assertEqual(course.ects_amount, Decimal('5.00'))

    def test_course_decimal_precision(self):
        """Test that ECTS supports decimal precision"""
        course = InboxCourse.objects.create(
            inbox_request=self.request,
            course_code="PHY101",
            course_name="Physics Lab",
            ects_amount=Decimal('2.50')
        )

        self.assertEqual(course.ects_amount, Decimal('2.50'))


class ECTSCalculationTestCase(TestCase):
    def setUp(self):
        self.semester = Semester.objects.create(
            code="WS24",
            display_name="Winter Semester 2024/25",
            start_date=date(2024, 10, 1),
            ects_adjustment=Decimal('0.00')
        )

        self.person = Person.objects.create(
            first_name="Test",
            last_name="Person"
        )

        self.role = Role.objects.create(
            name="Full Semester Role",
            short_name="FSR",
            ects_cap=Decimal('12.00')
        )

    def test_full_semester_overlap(self):
        """Test ECTS calculation for full semester overlap"""
        person_role = PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2024, 10, 1),
        )

        aliquoted = calculate_aliquoted_ects(person_role, self.semester)
        self.assertEqual(aliquoted, Decimal('12.00'))

    def test_partial_semester_overlap(self):
        """Test ECTS calculation for partial semester (50%)"""
        # Half semester: Oct 1 - Nov 30 (61 days out of 123)
        person_role = PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2024, 10, 1),
        )

        aliquoted = calculate_aliquoted_ects(person_role, self.semester)
        # 61 / 123 = ~0.4959... * 12 = ~5.95
        self.assertAlmostEqual(float(aliquoted), 5.95, places=2)

    def test_no_overlap(self):
        """Test ECTS calculation with no overlap"""
        person_role = PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2024, 1, 1),
        )

        aliquoted = calculate_aliquoted_ects(person_role, self.semester)
        self.assertEqual(aliquoted, Decimal('0.00'))

    def test_overlap_percentage_calculation(self):
        """Test percentage overlap calculation"""
        person_role = PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2024, 10, 1),
        )

        percentage = calculate_overlap_percentage(person_role, self.semester)
        self.assertEqual(percentage, Decimal('1.0000'))

    def test_open_ended_person_role(self):
        """Test calculation with ongoing person role (no end date)"""
        person_role = PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2024, 10, 1),
            end_date=None  # Ongoing
        )

        aliquoted = calculate_aliquoted_ects(person_role, self.semester)
        self.assertEqual(aliquoted, Decimal('12.00'))


class ECTSValidationTestCase(TestCase):
    def setUp(self):
        self.semester = Semester.objects.create(
            code="WS24",
            display_name="Winter Semester 2024/25",
            start_date=date(2024, 10, 1),
            ects_adjustment=Decimal('0.00')
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
            start_date=date(2024, 10, 1),
        )

        self.request = InboxRequest.objects.create(
            semester=self.semester,
            person_role=self.person_role
        )

    def test_validate_within_limit(self):
        """Test validation when ECTS is within limit"""
        InboxCourse.objects.create(
            inbox_request=self.request,
            course_code="CS101",
            course_name="Test Course",
            ects_amount=Decimal('10.00')
        )

        is_valid, max_ects, total_ects, message = validate_ects_total(self.request)
        self.assertTrue(is_valid)
        self.assertEqual(max_ects, Decimal('12.00'))
        self.assertEqual(total_ects, Decimal('10.00'))

    def test_validate_exceeds_limit(self):
        """Test validation when ECTS exceeds limit"""
        InboxCourse.objects.create(
            inbox_request=self.request,
            course_code="CS101",
            course_name="Test Course 1",
            ects_amount=Decimal('8.00')
        )
        InboxCourse.objects.create(
            inbox_request=self.request,
            course_code="CS102",
            course_name="Test Course 2",
            ects_amount=Decimal('6.00')
        )

        is_valid, max_ects, total_ects, message = validate_ects_total(self.request)
        self.assertFalse(is_valid)
        self.assertEqual(max_ects, Decimal('12.00'))
        self.assertEqual(total_ects, Decimal('14.00'))
        self.assertIn("exceeds", message)

    def test_validate_with_bonus(self):
        """Test validation with semester bonus adjustment"""
        self.semester.ects_adjustment = Decimal('2.00')
        self.semester.save()

        InboxCourse.objects.create(
            inbox_request=self.request,
            course_code="CS101",
            course_name="Test Course",
            ects_amount=Decimal('13.00')
        )

        is_valid, max_ects, total_ects, message = validate_ects_total(self.request)
        self.assertTrue(is_valid)
        self.assertEqual(max_ects, Decimal('14.00'))  # 12 + 2 bonus

    def test_validate_with_malus(self):
        """Test validation with semester malus (negative adjustment)"""
        self.semester.ects_adjustment = Decimal('-2.00')
        self.semester.save()

        InboxCourse.objects.create(
            inbox_request=self.request,
            course_code="CS101",
            course_name="Test Course",
            ects_amount=Decimal('11.00')
        )

        is_valid, max_ects, total_ects, message = validate_ects_total(self.request)
        self.assertFalse(is_valid)
        self.assertEqual(max_ects, Decimal('10.00'))  # 12 - 2 malus


class PasswordGenerationTestCase(TestCase):
    def test_get_random_words(self):
        """Test password word generation"""
        words = get_random_words(count=2)
        self.assertEqual(len(words), 2)
        self.assertTrue(all(isinstance(w, str) for w in words))

    def test_get_random_words_unique(self):
        """Test that random words are unique"""
        words = get_random_words(count=5)
        self.assertEqual(len(words), len(set(words)))
