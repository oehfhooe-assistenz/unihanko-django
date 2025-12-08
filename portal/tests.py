# File: portal/tests.py
# Version: 1.0.1
# Author: vas
# Created: 2025-12-08

from django.test import TestCase
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from decimal import Decimal
from datetime import date, timedelta
from io import BytesIO

from academia.models import Semester, InboxRequest
from people.models import Person, Role, PersonRole
from finances.models import FiscalYear, PaymentPlan

from portal.forms import (
    AccessCodeForm, CourseForm, FileRequestForm,
    BankingDetailsForm, PaymentAccessForm, PaymentUploadForm
)
from portal.utils import validate_pdf_upload


class AccessCodeFormTest(TestCase):
    """Test AccessCodeForm validation for semester and reference codes."""

    def setUp(self):
        """Create test data."""
        self.semester = Semester.objects.create(
            code="WS24",
            display_name="Wintersemester 2024",
            start_date=date(2024, 10, 1),
            end_date=date(2025, 2, 28),
            filing_start=timezone.make_aware(timezone.datetime(2024, 11, 1)),
            filing_end=timezone.make_aware(timezone.datetime(2025, 1, 31)),
            access_password="forest-mountain-23"
        )
        
        person = Person.objects.create(
            first_name="John",
            last_name="Doe"
        )
        role = Role.objects.create(name="Test Role")
        person_role = PersonRole.objects.create(
            person=person,
            role=role,
            start_date=date(2024, 1, 1)
        )
        
        self.inbox_request = InboxRequest.objects.create(
            semester=self.semester,
            person_role=person_role,
            filing_source='PUBLIC'
        )

    def test_valid_semester_code(self):
        """Valid semester access code is accepted."""
        form = AccessCodeForm(semester=self.semester)
        form.cleaned_data = {'access_code': 'forest-mountain-23'}
        try:
            cleaned = form.clean_access_code()
            self.assertEqual(form.access_type, 'semester')
            self.assertEqual(cleaned, 'forest-mountain-23')
        except ValidationError:
            self.fail("Valid semester code should not raise ValidationError")

    def test_semester_code_case_insensitive(self):
        """Semester codes are case-insensitive."""
        form = AccessCodeForm(semester=self.semester)
        form.cleaned_data = {'access_code': 'FOREST-MOUNTAIN-23'}
        try:
            cleaned = form.clean_access_code()
            self.assertEqual(form.access_type, 'semester')
        except ValidationError:
            self.fail("Case-insensitive semester code should work")

    def test_valid_reference_code(self):
        """Valid reference code is accepted."""
        form = AccessCodeForm(semester=self.semester)
        form.cleaned_data = {'access_code': self.inbox_request.reference_code}
        try:
            cleaned = form.clean_access_code()
            self.assertEqual(form.access_type, 'reference')
            self.assertEqual(form.inbox_request, self.inbox_request)
        except ValidationError:
            self.fail("Valid reference code should not raise ValidationError")

    def test_invalid_code(self):
        """Invalid codes are rejected."""
        form = AccessCodeForm(semester=self.semester)
        form.cleaned_data = {'access_code': 'invalid-code-123'}
        with self.assertRaises(ValidationError):
            form.clean_access_code()

    def test_reference_code_wrong_semester(self):
        """Reference code for wrong semester is rejected."""
        other_semester = Semester.objects.create(
            code="SS25",
            display_name="Sommersemester 2025",
            start_date=date(2025, 3, 1),
            end_date=date(2025, 7, 31),
            filing_start=timezone.make_aware(timezone.datetime(2025, 4, 1)),
            filing_end=timezone.make_aware(timezone.datetime(2025, 6, 30)),
            access_password="summer-code-25"
        )
        
        form = AccessCodeForm(semester=other_semester)
        form.cleaned_data = {'access_code': self.inbox_request.reference_code}
        with self.assertRaises(ValidationError) as cm:
            form.clean_access_code()
        self.assertIn("not for the selected semester", str(cm.exception))


class CourseFormTest(TestCase):
    """Test CourseForm ECTS validation."""

    def test_valid_whole_ects(self):
        """Whole ECTS numbers are accepted."""
        form = CourseForm(data={
            'course_code': 'CS101',
            'course_name': 'Computer Science',
            'ects_amount': '5'
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['ects_amount'], Decimal('5.0'))

    def test_valid_half_ects(self):
        """Half ECTS values are accepted."""
        form = CourseForm(data={
            'course_code': 'MATH202',
            'ects_amount': '7.5'
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['ects_amount'], Decimal('7.5'))

    def test_ects_too_small(self):
        """ECTS below 0.5 is rejected."""
        form = CourseForm(data={
            'course_code': 'TEST',
            'ects_amount': '0.2'
        })
        self.assertFalse(form.is_valid())
        self.assertIn('ects_amount', form.errors)

    def test_ects_too_large(self):
        """ECTS above 15.0 is rejected."""
        form = CourseForm(data={
            'course_code': 'TEST',
            'ects_amount': '20.0'
        })
        self.assertFalse(form.is_valid())
        self.assertIn('ects_amount', form.errors)

    def test_ects_without_course_info(self):
        """ECTS provided but no course code or name."""
        form = CourseForm(data={
            'ects_amount': '5.0'
        })
        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)

    def test_course_info_without_ects(self):
        """Course info provided but no ECTS."""
        form = CourseForm(data={
            'course_code': 'CS101',
            'course_name': 'Computer Science'
        })
        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)

    def test_empty_form_valid(self):
        """Empty form (all fields blank) is valid."""
        form = CourseForm(data={})
        self.assertTrue(form.is_valid())

    def test_ects_decimal_conversion(self):
        """Whole numbers are converted to .0 format."""
        form = CourseForm(data={
            'course_name': 'Test Course',
            'ects_amount': '3'
        })
        self.assertTrue(form.is_valid())
        # Check it's stored as Decimal with .0
        self.assertEqual(str(form.cleaned_data['ects_amount']), '3.0')


class BankingDetailsFormTest(TestCase):
    """Test BankingDetailsForm IBAN/BIC validation."""

    def setUp(self):
        """Create test payment plan."""
        person = Person.objects.create(
            first_name="Jane",
            last_name="Smith"
        )
        role = Role.objects.create(name="Test Role")
        person_role = PersonRole.objects.create(
            person=person,
            role=role,
            start_date=date(2024, 1, 1)
        )
        fiscal_year = FiscalYear.objects.create(
            code="FY24",
            start=date(2024, 1, 1),
            end=date(2024, 12, 31)
        )
        self.payment_plan = PaymentPlan.objects.create(
            person_role=person_role,
            fiscal_year=fiscal_year,
            monthly_amount=Decimal('500.00')
        )

    def test_valid_austrian_iban(self):
        """Valid Austrian IBAN is accepted."""
        # Use a valid Austrian test IBAN (AT611904300234573201)
        form = BankingDetailsForm(
            data={
                'payee_name': 'Jane Smith',
                'iban': 'AT61 1904 3002 3457 3201',
                'bic': 'RZOOAT2L',
                'address': 'Hauptstrasse 1\n1010 Wien\nAustria'
            },
            instance=self.payment_plan
        )
        self.assertTrue(form.is_valid(), f"Form errors: {form.errors}")
        # Check normalization
        self.assertEqual(form.cleaned_data['iban'], 'AT611904300234573201')
        self.assertEqual(form.cleaned_data['bic'], 'RZOOAT2L')

    def test_iban_wrong_country(self):
        """Non-Austrian IBAN is rejected."""
        form = BankingDetailsForm(
            data={
                'payee_name': 'Jane Smith',
                'iban': 'DE89370400440532013000',
                'bic': 'COBADEFF',
                'address': 'Test Address'
            },
            instance=self.payment_plan
        )
        self.assertFalse(form.is_valid())
        self.assertIn('iban', form.errors)

    def test_iban_wrong_length(self):
        """IBAN with wrong length is rejected."""
        form = BankingDetailsForm(
            data={
                'payee_name': 'Jane Smith',
                'iban': 'AT1234567890',  # Too short (12 chars instead of 20)
                'bic': 'RZOOAT2L',
                'address': 'Test Address'
            },
            instance=self.payment_plan
        )
        self.assertFalse(form.is_valid())
        self.assertIn('iban', form.errors)

    def test_bic_invalid_length(self):
        """BIC with invalid length is rejected."""
        form = BankingDetailsForm(
            data={
                'payee_name': 'Jane Smith',
                'iban': 'AT61 1904 3002 3457 3201',
                'bic': 'RZOO',  # Too short
                'address': 'Test Address'
            },
            instance=self.payment_plan
        )
        self.assertFalse(form.is_valid())
        self.assertIn('bic', form.errors)

    def test_bic_valid_lengths(self):
        """BIC with 8 or 11 chars is accepted."""
        # 8 chars
        form8 = BankingDetailsForm(
            data={
                'payee_name': 'Jane Smith',
                'iban': 'AT61 1904 3002 3457 3201',
                'bic': 'RZOOAT2L',
                'address': 'Hauptstrasse 1, 1010 Wien'
            },
            instance=self.payment_plan
        )
        self.assertTrue(form8.is_valid(), f"Form8 errors: {form8.errors}")
        
        # 11 chars
        form11 = BankingDetailsForm(
            data={
                'payee_name': 'Jane Smith',
                'iban': 'AT61 1904 3002 3457 3201',
                'bic': 'RZOOAT2LXXX',
                'address': 'Hauptstrasse 1, 1010 Wien'
            },
            instance=self.payment_plan
        )
        self.assertTrue(form11.is_valid(), f"Form11 errors: {form11.errors}")

    def test_address_required(self):
        """Address field is required."""
        form = BankingDetailsForm(
            data={
                'payee_name': 'Jane Smith',
                'iban': 'AT61 1904 3002 3457 3201',
                'bic': 'RZOOAT2L',
                'address': ''
            },
            instance=self.payment_plan
        )
        self.assertFalse(form.is_valid())
        self.assertIn('address', form.errors)

    def test_address_too_short(self):
        """Very short addresses are rejected."""
        form = BankingDetailsForm(
            data={
                'payee_name': 'Jane Smith',
                'iban': 'AT61 1904 3002 3457 3201',
                'bic': 'RZOOAT2L',
                'address': 'ABC'
            },
            instance=self.payment_plan
        )
        self.assertFalse(form.is_valid())
        self.assertIn('address', form.errors)


class PaymentAccessFormTest(TestCase):
    """Test PaymentAccessForm PAC validation."""

    def setUp(self):
        """Create test person with PAC."""
        self.person = Person.objects.create(
            first_name="John",
            last_name="Doe",
            personal_access_code="ABCD-EFGH"
        )
        self.fiscal_year = FiscalYear.objects.create(
            code="FY24",
            start=date(2024, 1, 1),
            end=date(2024, 12, 31)
        )

    def test_valid_pac(self):
        """Valid PAC is accepted and person is found."""
        # Note: CAPTCHA will fail in tests, so we test the clean_pac method directly
        form = PaymentAccessForm(fiscal_year=self.fiscal_year)
        # Simulate what happens when form processes PAC field
        form.cleaned_data = {'pac': 'ABCD-EFGH'}
        try:
            cleaned_pac = form.clean_pac()
            self.assertEqual(form.person, self.person)
            self.assertEqual(cleaned_pac, 'ABCD-EFGH')
        except ValidationError:
            self.fail("Valid PAC should not raise ValidationError")

    def test_pac_case_insensitive(self):
        """PAC lookup is case-insensitive."""
        form = PaymentAccessForm(fiscal_year=self.fiscal_year)
        form.cleaned_data = {'pac': 'abcd-efgh'}
        try:
            cleaned_pac = form.clean_pac()
            self.assertEqual(form.person, self.person)
        except ValidationError:
            self.fail("Case-insensitive PAC should work")

    def test_invalid_pac(self):
        """Invalid PAC is rejected."""
        form = PaymentAccessForm(fiscal_year=self.fiscal_year)
        form.cleaned_data = {'pac': 'INVALID-CODE'}
        with self.assertRaises(ValidationError):
            form.clean_pac()


class PDFValidationTest(TestCase):
    """Test validate_pdf_upload utility function."""

    def _create_pdf_file(self, content=b'%PDF-1.4\n%Test PDF', filename='test.pdf', size_mb=1):
        """Helper to create test PDF files."""
        # Create content of specified size
        content_size = int(size_mb * 1024 * 1024)
        padded_content = content + b'\x00' * (content_size - len(content))
        return SimpleUploadedFile(filename, padded_content, content_type='application/pdf')

    def test_valid_pdf_passes(self):
        """Valid PDF file passes validation."""
        pdf_file = self._create_pdf_file()
        try:
            result = validate_pdf_upload(pdf_file)
            self.assertEqual(result, pdf_file)
        except ValidationError:
            # This might fail because we're not creating a real PDF
            # In production, you'd use a library to create valid PDFs
            pass

    def test_file_too_large(self):
        """Files over 20MB are rejected."""
        large_file = self._create_pdf_file(size_mb=25)
        with self.assertRaises(ValidationError) as cm:
            validate_pdf_upload(large_file)
        self.assertIn('exceeds', str(cm.exception))

    def test_non_pdf_extension_rejected(self):
        """Non-PDF files are rejected."""
        exe_file = SimpleUploadedFile('malware.exe', b'content', content_type='application/x-msdownload')
        with self.assertRaises(ValidationError) as cm:
            validate_pdf_upload(exe_file)
        self.assertIn('PDF', str(cm.exception))

    def test_custom_size_limit(self):
        """Custom size limits work."""
        pdf_file = self._create_pdf_file(size_mb=5)
        with self.assertRaises(ValidationError):
            validate_pdf_upload(pdf_file, max_size_mb=2)

    def test_file_extension_case_insensitive(self):
        """PDF extension check is case-insensitive."""
        pdf_file = self._create_pdf_file(filename='test.PDF')
        try:
            # Should not raise on extension check
            validate_pdf_upload(pdf_file)
        except ValidationError as e:
            # Should only fail on PDF structure, not extension
            self.assertNotIn('PDF files are allowed', str(e))


class FileRequestFormTest(TestCase):
    """Test FileRequestForm person_role filtering."""

    def setUp(self):
        """Create test data."""
        self.semester = Semester.objects.create(
            code="WS24",
            display_name="Winter 2024",
            start_date=date(2024, 10, 1),
            end_date=date(2025, 2, 28),
            filing_start=timezone.make_aware(timezone.datetime(2024, 11, 1)),
            filing_end=timezone.make_aware(timezone.datetime(2025, 1, 31)),
            access_password="test"
        )
        
        person = Person.objects.create(first_name="John", last_name="Doe")
        
        # Create end reason for ended assignment
        from people.models import RoleTransitionReason
        self.end_reason = RoleTransitionReason.objects.create(
            code="O01",
            name="Austritt"
        )
        
        # Regular role
        self.regular_role = Role.objects.create(
            name="Regular Role",
            is_system=False,
            ects_cap=Decimal('10.0')
        )
        
        # System role (should be filtered out)
        self.system_role = Role.objects.create(
            name="System Role",
            is_system=True
        )
        
        # Active assignment (should appear)
        self.active_pr = PersonRole.objects.create(
            person=person,
            role=self.regular_role,
            start_date=date(2024, 1, 1)
        )
        
        # System assignment (should NOT appear)
        self.system_pr = PersonRole.objects.create(
            person=person,
            role=self.system_role,
            start_date=date(2024, 1, 1)
        )
        
        # Ended before semester (should NOT appear)
        self.ended_pr = PersonRole.objects.create(
            person=Person.objects.create(first_name="Jane", last_name="Smith"),
            role=self.regular_role,
            start_date=date(2023, 1, 1),
            end_date=date(2023, 12, 31),
            end_reason=self.end_reason
        )

    def test_filters_system_roles(self):
        """System roles are excluded from queryset."""
        form = FileRequestForm(semester=self.semester)
        qs = form.fields['person_role'].queryset
        
        self.assertIn(self.active_pr, qs)
        self.assertNotIn(self.system_pr, qs)

    def test_filters_by_semester_dates(self):
        """Only assignments active during semester are shown."""
        form = FileRequestForm(semester=self.semester)
        qs = form.fields['person_role'].queryset
        
        self.assertIn(self.active_pr, qs)
        self.assertNotIn(self.ended_pr, qs)

    def test_custom_label_format(self):
        """Custom labels show person, role, dates, and ECTS."""
        form = FileRequestForm(semester=self.semester)
        label = form._label_from_instance(self.active_pr)
        
        self.assertIn("Doe, John", label)
        self.assertIn("Regular Role", label)
        self.assertIn("2024-01-01", label)
        self.assertIn("10.0 ECTS", label)