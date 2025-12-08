# File: employees/tests.py
# Version: 1.0.1
# Author: vas
# Modified: 2025-12-08

from django.test import TestCase, TransactionTestCase
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User, Group
from django.db import connection, IntegrityError
from django.utils import timezone
from datetime import date, time as dt_time, timedelta
from decimal import Decimal
import threading
import time

from people.models import Person, Role, PersonRole
from .models import (
    Employee,
    TimeSheet,
    TimeEntry,
    EmployeeLeaveYear,
    HolidayCalendar,
    EmploymentDocument,
    easter_date,
    minutes_to_hhmm,
)


# =========================
# Test Fixtures / Helpers
# =========================

class EmployeeTestMixin:
    """Mixin providing common test data setup."""
    
    def setUp(self):
        """
        Use setUp instead of setUpTestData for TransactionTestCase compatibility.
        TransactionTestCase flushes the database after each test, so class-level
        data doesn't persist.
        """
        super().setUp()
        
        # Create person and role
        self.person = Person.objects.create(
            first_name="Test",
            last_name="Employee",
            email="test@example.com"
        )
        
        self.role = Role.objects.create(
            name="Test Role"
        )
        
        self.person_role = PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2024, 1, 1)
        )
        
        # Create employee
        self.employee = Employee.objects.create(
            person_role=self.person_role,
            weekly_hours=Decimal("20.00"),
            annual_leave_days_base=25,
            annual_leave_days_extra=0
        )
        
        # Create manager user and group
        self.manager_user = User.objects.create_user(
            username='manager',
            password='test123'
        )
        manager_group, _ = Group.objects.get_or_create(name='module:employees:manager')
        self.manager_user.groups.add(manager_group)
        
        # Create regular staff user
        self.staff_user = User.objects.create_user(
            username='staff',
            password='test123',
            is_staff=True
        )


# =========================
# Issue #3: TimeSheet Race Condition Tests
# =========================

class TimeSheetRaceConditionTestCase(EmployeeTestMixin, TransactionTestCase):
    """
    Test that TimeSheet.save() handles concurrent creation attempts.
    Uses TransactionTestCase to test actual database behavior.
    """
    
    def setUp(self):
        super().setUp()
    
    def test_concurrent_timesheet_creation_with_retry(self):
        """Test that retry logic prevents duplicate timesheets."""
        # Skip if SQLite (doesn't support true concurrency)
        if 'sqlite' in connection.vendor:
            self.skipTest("SQLite doesn't support concurrent transactions")
        
        employee = self.employee
        year, month = 2025, 1
        
        results = {'created': [], 'errors': []}
        barrier = threading.Barrier(2)  # Sync both threads
        
        def create_timesheet(thread_id):
            try:
                # Wait for both threads to be ready
                barrier.wait()
                
                # Both try to create at the same time
                ts = TimeSheet.objects.create(
                    employee=employee,
                    year=year,
                    month=month
                )
                results['created'].append((thread_id, ts.pk))
            except Exception as e:
                results['errors'].append((thread_id, str(e)))
        
        # Start two threads
        t1 = threading.Thread(target=create_timesheet, args=(1,))
        t2 = threading.Thread(target=create_timesheet, args=(2,))
        
        t1.start()
        t2.start()
        
        t1.join()
        t2.join()
        
        # One should succeed, one should fail or retry and fail
        # But we should only have ONE timesheet in database
        count = TimeSheet.objects.filter(
            employee=employee,
            year=year,
            month=month
        ).count()
        
        self.assertEqual(count, 1, "Should only have one timesheet created")
    
    def test_timesheet_creation_retry_sequential(self):
        """
        Test retry logic sequentially (works on SQLite).
        Simulates the race condition by creating one sheet first.
        """
        employee = self.employee
        year, month = 2025, 2
        
        # Create first timesheet
        ts1 = TimeSheet.objects.create(
            employee=employee,
            year=year,
            month=month
        )
        self.assertIsNotNone(ts1.pk)
        
        # Try to create duplicate (should fail with IntegrityError)
        with self.assertRaises(IntegrityError):
            TimeSheet.objects.create(
                employee=employee,
                year=year,
                month=month
            )
        
        # Verify still only one exists
        count = TimeSheet.objects.filter(
            employee=employee,
            year=year,
            month=month
        ).count()
        self.assertEqual(count, 1)


# =========================
# Issue #2: Aggregate Race Condition Tests
# =========================

class TimeSheetAggregatesTestCase(EmployeeTestMixin, TransactionTestCase):
    """
    Test that TimeSheet.recompute_aggregates() handles concurrent updates correctly.
    """
    
    def setUp(self):
        super().setUp()
        self.timesheet = TimeSheet.objects.create(
            employee=self.employee,
            year=2025,
            month=1
        )
    
    def test_concurrent_entry_saves_maintain_correct_totals(self):
        """Test that concurrent TimeEntry saves produce correct aggregates."""
        # Skip if SQLite
        if 'sqlite' in connection.vendor:
            self.skipTest("SQLite doesn't support concurrent transactions")
        
        ts = self.timesheet
        
        # Create entries concurrently
        results = {'created': [], 'errors': []}
        barrier = threading.Barrier(3)
        
        def create_entry(thread_id, day, minutes):
            try:
                barrier.wait()
                entry = TimeEntry.objects.create(
                    timesheet=ts,
                    date=date(2025, 1, day),
                    kind=TimeEntry.Kind.WORK,
                    minutes=minutes
                )
                results['created'].append((thread_id, entry.pk))
            except Exception as e:
                results['errors'].append((thread_id, str(e)))
        
        # Three threads creating entries
        t1 = threading.Thread(target=create_entry, args=(1, 5, 100))
        t2 = threading.Thread(target=create_entry, args=(2, 6, 200))
        t3 = threading.Thread(target=create_entry, args=(3, 7, 150))
        
        t1.start()
        t2.start()
        t3.start()
        
        t1.join()
        t2.join()
        t3.join()
        
        # Refresh timesheet
        ts.refresh_from_db()
        
        # Check aggregates are correct
        expected_total = 100 + 200 + 150
        self.assertEqual(ts.worked_minutes, expected_total,
                        "Worked minutes should match sum of all entries")
    
    def test_recompute_aggregates_calculates_correctly(self):
        """Test that aggregate calculation is correct."""
        ts = self.timesheet
        
        # Create various entries
        TimeEntry.objects.create(
            timesheet=ts,
            date=date(2025, 1, 5),
            kind=TimeEntry.Kind.WORK,
            minutes=480  # 8 hours
        )
        TimeEntry.objects.create(
            timesheet=ts,
            date=date(2025, 1, 6),
            kind=TimeEntry.Kind.WORK,
            minutes=240  # 4 hours
        )
        TimeEntry.objects.create(
            timesheet=ts,
            date=date(2025, 1, 7),
            kind=TimeEntry.Kind.LEAVE,
            minutes=480  # 8 hours leave
        )
        TimeEntry.objects.create(
            timesheet=ts,
            date=date(2025, 1, 8),
            kind=TimeEntry.Kind.SICK,
            minutes=240  # 4 hours sick
        )
        
        # Recompute
        ts.recompute_aggregates(commit=True)
        ts.refresh_from_db()
        
        # Verify
        expected_work = 480 + 240  # 720
        expected_credit = 480 + 240  # 720
        
        self.assertEqual(ts.worked_minutes, expected_work)
        self.assertEqual(ts.credit_minutes, expected_credit)
    
    def test_recompute_aggregates_with_no_entries(self):
        """Test recompute on empty timesheet."""
        ts = self.timesheet
        ts.recompute_aggregates(commit=True)
        ts.refresh_from_db()
        
        self.assertEqual(ts.worked_minutes, 0)
        self.assertEqual(ts.credit_minutes, 0)


# =========================
# Issue #1: Manager Bypass Tests
# =========================

class TimeEntryValidationTestCase(EmployeeTestMixin, TestCase):
    """
    Test TimeEntry validation logic.
    NOTE: Manager bypass is tested at admin layer, not model layer.
    """
    
    def setUp(self):
        super().setUp()
        self.timesheet = TimeSheet.objects.create(
            employee=self.employee,
            year=2025,
            month=1
        )
    
    def test_duplicate_entry_blocked(self):
        """Test that duplicate entries are caught in validation."""
        # Create first entry
        entry1 = TimeEntry.objects.create(
            timesheet=self.timesheet,
            date=date(2025, 1, 5),
            kind=TimeEntry.Kind.WORK,
            minutes=480,
            comment="Test"
        )
        
        # Try to create duplicate
        entry2 = TimeEntry(
            timesheet=self.timesheet,
            date=date(2025, 1, 5),
            kind=TimeEntry.Kind.WORK,
            minutes=480,
            comment="Test"  # Same comment
        )
        
        with self.assertRaises(ValidationError) as cm:
            entry2.full_clean()
        
        self.assertIn("already exists", str(cm.exception).lower())
    
    def test_entry_must_be_in_timesheet_month(self):
        """Test that entries must be within the timesheet's month."""
        entry = TimeEntry(
            timesheet=self.timesheet,  # 2025-01
            date=date(2025, 2, 5),     # Wrong month!
            kind=TimeEntry.Kind.WORK,
            minutes=480
        )
        
        with self.assertRaises(ValidationError) as cm:
            entry.full_clean()
        
        self.assertIn("month", str(cm.exception).lower())
    
    def test_work_blocked_on_public_holiday(self):
        """Test that WORK entries are blocked on public holidays."""
        # Create holiday calendar
        cal = HolidayCalendar.objects.create(
            name="Test Calendar",
            is_active=True,
            rules_text="01-01 | New Year | Neujahr"
        )
        
        entry = TimeEntry(
            timesheet=self.timesheet,
            date=date(2025, 1, 1),  # New Year's Day
            kind=TimeEntry.Kind.WORK,
            minutes=480
        )
        
        with self.assertRaises(ValidationError) as cm:
            entry.full_clean()
        
        self.assertIn("holiday", str(cm.exception).lower())
    
    def test_time_span_validation(self):
        """Test start/end time validation."""
        # End before start should fail
        entry = TimeEntry(
            timesheet=self.timesheet,
            date=date(2025, 1, 5),
            kind=TimeEntry.Kind.WORK,
            start_time=dt_time(17, 0),
            end_time=dt_time(9, 0),  # Before start!
            minutes=480
        )
        
        with self.assertRaises(ValidationError) as cm:
            entry.full_clean()
        
        self.assertIn("after start", str(cm.exception).lower())
    
    def test_time_span_calculates_minutes(self):
        """Test that time span automatically calculates minutes."""
        entry = TimeEntry(
            timesheet=self.timesheet,
            date=date(2025, 1, 5),
            kind=TimeEntry.Kind.WORK,
            start_time=dt_time(9, 0),
            end_time=dt_time(17, 0)  # 8 hours
        )
        
        entry.full_clean()
        
        self.assertEqual(entry.minutes, 480)  # 8 * 60
    
    def test_leave_gets_default_daily_minutes(self):
        """Test that LEAVE entries get default daily minutes."""
        entry = TimeEntry(
            timesheet=self.timesheet,
            date=date(2025, 1, 5),
            kind=TimeEntry.Kind.LEAVE
            # No minutes or time span provided
        )
        
        entry.full_clean()
        
        expected = self.employee.daily_expected_minutes
        self.assertEqual(entry.minutes, expected)
    
    def test_work_requires_minutes_or_timespan(self):
        """Test that WORK entries require either minutes or time span."""
        entry = TimeEntry(
            timesheet=self.timesheet,
            date=date(2025, 1, 5),
            kind=TimeEntry.Kind.WORK
            # No minutes or time span
        )
        
        with self.assertRaises(ValidationError) as cm:
            entry.full_clean()
        
        self.assertIn("minutes", str(cm.exception).lower())


# =========================
# Holiday Calendar Tests
# =========================

class HolidayCalendarTestCase(TestCase):
    """Test holiday calendar parsing and calculation."""
    
    def test_easter_calculation(self):
        """Test Easter date calculation."""
        # Known Easter dates
        self.assertEqual(easter_date(2024), date(2024, 3, 31))
        self.assertEqual(easter_date(2025), date(2025, 4, 20))
        self.assertEqual(easter_date(2026), date(2026, 4, 5))
    
    def test_fixed_date_parsing(self):
        """Test parsing of fixed date rules."""
        cal = HolidayCalendar.objects.create(
            name="Test",
            is_active=True,
            rules_text="01-01 | New Year | Neujahr\n12-25 | Christmas | Weihnachten"
        )
        
        holidays = cal.holidays_for_year(2025)
        
        self.assertIn(date(2025, 1, 1), holidays)
        self.assertIn(date(2025, 12, 25), holidays)
    
    def test_easter_relative_parsing(self):
        """Test parsing of Easter-relative rules."""
        cal = HolidayCalendar.objects.create(
            name="Test",
            is_active=True,
            rules_text="EASTER | Easter Sunday | Ostersonntag\nEASTER+1 | Easter Monday | Ostermontag"
        )
        
        holidays = cal.holidays_for_year(2025)
        easter = easter_date(2025)  # April 20, 2025
        
        self.assertIn(easter, holidays)
        self.assertIn(easter + timedelta(days=1), holidays)
    
    def test_oneoff_date_parsing(self):
        """Test parsing of one-off date rules."""
        cal = HolidayCalendar.objects.create(
            name="Test",
            is_active=True,
            rules_text="2025-05-09 | Bridge Day | Fenstertag"
        )
        
        holidays_2025 = cal.holidays_for_year(2025)
        holidays_2026 = cal.holidays_for_year(2026)
        
        self.assertIn(date(2025, 5, 9), holidays_2025)
        self.assertNotIn(date(2026, 5, 9), holidays_2026)  # Only in 2025
    
    def test_only_one_active_calendar_allowed(self):
        """Test that only one calendar can be active."""
        cal1 = HolidayCalendar.objects.create(
            name="Calendar 1",
            is_active=True
        )
        
        cal2 = HolidayCalendar(
            name="Calendar 2",
            is_active=True
        )
        
        with self.assertRaises(ValidationError):
            cal2.full_clean()
    
    def test_bilingual_labels(self):
        """Test that bilingual labels work correctly."""
        cal = HolidayCalendar.objects.create(
            name="Test",
            is_active=True,
            rules_text="01-01 | New Year's Day | Neujahrstag"
        )
        
        labeled = cal.holidays_for_year_labeled(2025, lang='en')
        self.assertEqual(labeled[date(2025, 1, 1)], "New Year's Day")
        
        labeled_de = cal.holidays_for_year_labeled(2025, lang='de')
        self.assertEqual(labeled_de[date(2025, 1, 1)], "Neujahrstag")


# =========================
# PTO (Leave Year) Tests
# =========================

class EmployeeLeaveYearTestCase(EmployeeTestMixin, TestCase):
    """Test PTO year calculations and carry-over."""
    
    def setUp(self):
        super().setUp()
    
    def test_pto_label_year_default_jan1(self):
        """Test PTO year calculation with default Jan 1 reset."""
        emp = self.employee
        
        # Dates in 2025
        self.assertEqual(
            EmployeeLeaveYear.pto_label_year_for(emp, date(2025, 1, 1)),
            2025
        )
        self.assertEqual(
            EmployeeLeaveYear.pto_label_year_for(emp, date(2025, 6, 15)),
            2025
        )
        self.assertEqual(
            EmployeeLeaveYear.pto_label_year_for(emp, date(2025, 12, 31)),
            2025
        )
    
    def test_pto_label_year_custom_reset_july1(self):
        """Test PTO year with custom July 1 reset."""
        emp = self.employee
        emp.leave_reset_override = date(2025, 7, 1)
        emp.save()
        
        # Before July 1 → previous year
        self.assertEqual(
            EmployeeLeaveYear.pto_label_year_for(emp, date(2025, 6, 30)),
            2024
        )
        
        # On/after July 1 → current year
        self.assertEqual(
            EmployeeLeaveYear.pto_label_year_for(emp, date(2025, 7, 1)),
            2025
        )
        self.assertEqual(
            EmployeeLeaveYear.pto_label_year_for(emp, date(2025, 12, 31)),
            2025
        )
    
    def test_pto_carry_over(self):
        """Test that remaining PTO carries over to next year."""
        emp = self.employee
        
        # Create 2024 year with some remaining
        ly_2024 = EmployeeLeaveYear.objects.create(
            employee=emp,
            label_year=2024,
            period_start=date(2024, 1, 1),
            period_end=date(2025, 1, 1),
            entitlement_minutes=12000,  # 200 hours
            carry_in_minutes=0,
            manual_adjust_minutes=0
        )
        
        # Create a timesheet in 2024 with some leave taken
        ts_2024 = TimeSheet.objects.create(
            employee=emp,
            year=2024,
            month=12
        )
        TimeEntry.objects.create(
            timesheet=ts_2024,
            date=date(2024, 12, 15),
            kind=TimeEntry.Kind.LEAVE,
            minutes=480  # 1 day taken
        )
        
        # Create 2025 year (should carry over remaining)
        ly_2025 = EmployeeLeaveYear.ensure_for(emp, 2025)
        
        # Verify carry-over
        remaining_2024 = ly_2024.remaining_minutes
        self.assertEqual(ly_2025.carry_in_minutes, remaining_2024)
        self.assertGreater(ly_2025.carry_in_minutes, 0)
    
    def test_ensure_for_idempotent(self):
        """Test that ensure_for() is idempotent."""
        emp = self.employee
        
        ly1 = EmployeeLeaveYear.ensure_for(emp, 2025)
        ly2 = EmployeeLeaveYear.ensure_for(emp, 2025)
        
        self.assertEqual(ly1.pk, ly2.pk)


# =========================
# Employment Document Tests
# =========================

class EmploymentDocumentTestCase(EmployeeTestMixin, TestCase):
    """Test employment document functionality."""
    
    def setUp(self):
        super().setUp()
    
    def test_code_generation(self):
        """Test automatic code generation."""
        doc = EmploymentDocument.objects.create(
            employee=self.employee,
            kind=EmploymentDocument.Kind.DV,
            title="Test Contract"
        )
        
        self.assertTrue(doc.code.startswith("DV_"))
        self.assertIn("employee", doc.code.lower())
    
    def test_code_uniqueness(self):
        """Test that codes are unique."""
        doc1 = EmploymentDocument.objects.create(
            employee=self.employee,
            kind=EmploymentDocument.Kind.AA,
            title="Leave Request 1"
        )
        
        doc2 = EmploymentDocument.objects.create(
            employee=self.employee,
            kind=EmploymentDocument.Kind.AA,
            title="Leave Request 2"
        )
        
        self.assertNotEqual(doc1.code, doc2.code)
    
    def test_date_validation(self):
        """Test that end date must be >= start date."""
        doc = EmploymentDocument(
            employee=self.employee,
            kind=EmploymentDocument.Kind.AA,
            start_date=date(2025, 2, 1),
            end_date=date(2025, 1, 1)  # Before start!
        )
        
        # Should fail at database constraint level
        with self.assertRaises((ValidationError, IntegrityError)):
            doc.save()


# =========================
# Utility Function Tests
# =========================

class UtilityFunctionTestCase(TestCase):
    """Test utility functions."""
    
    def test_minutes_to_hhmm_positive(self):
        """Test minutes to H:MM conversion for positive values."""
        self.assertEqual(minutes_to_hhmm(0), "0:00")
        self.assertEqual(minutes_to_hhmm(30), "0:30")
        self.assertEqual(minutes_to_hhmm(60), "1:00")
        self.assertEqual(minutes_to_hhmm(90), "1:30")
        self.assertEqual(minutes_to_hhmm(480), "8:00")
    
    def test_minutes_to_hhmm_negative(self):
        """Test minutes to H:MM conversion for negative values."""
        self.assertEqual(minutes_to_hhmm(-30), "-0:30")
        self.assertEqual(minutes_to_hhmm(-90), "-1:30")
        self.assertEqual(minutes_to_hhmm(-480), "-8:00")


# =========================
# Integration Tests
# =========================

class TimeSheetIntegrationTestCase(EmployeeTestMixin, TestCase):
    """Test complete timesheet workflow."""
    
    def setUp(self):
        super().setUp()
    
    def test_complete_timesheet_workflow(self):
        """Test creating timesheet, adding entries, and verifying aggregates."""
        # Create timesheet
        ts = TimeSheet.objects.create(
            employee=self.employee,
            year=2025,
            month=1
        )
        
        # Verify opening saldo snapshot
        self.assertEqual(ts.opening_saldo_minutes, self.employee.saldo_minutes)
        
        # Add work entries
        TimeEntry.objects.create(
            timesheet=ts,
            date=date(2025, 1, 6),  # Monday
            kind=TimeEntry.Kind.WORK,
            start_time=dt_time(9, 0),
            end_time=dt_time(17, 0)  # 8 hours
        )
        TimeEntry.objects.create(
            timesheet=ts,
            date=date(2025, 1, 7),  # Tuesday
            kind=TimeEntry.Kind.WORK,
            minutes=480  # 8 hours
        )
        
        # Add leave
        TimeEntry.objects.create(
            timesheet=ts,
            date=date(2025, 1, 8),  # Wednesday
            kind=TimeEntry.Kind.LEAVE
            # Should auto-fill daily expected minutes
        )
        
        # Refresh and check aggregates
        ts.refresh_from_db()
        
        expected_work = 480 + 480  # 2 days
        expected_credit = self.employee.daily_expected_minutes  # 1 day
        
        self.assertEqual(ts.worked_minutes, expected_work)
        self.assertEqual(ts.credit_minutes, expected_credit)
        
        # Verify closing saldo calculation
        total_minutes = expected_work + expected_credit
        closing = ts.opening_saldo_minutes + total_minutes - ts.expected_minutes
        self.assertEqual(ts.closing_saldo_minutes, closing)
    
    def test_pto_snapshot_auto_creation(self):
        """Test that PTO snapshot is auto-created when LEAVE entry is saved."""
        ts = TimeSheet.objects.create(
            employee=self.employee,
            year=2025,
            month=6
        )
        
        # No PTO year exists yet
        self.assertEqual(
            EmployeeLeaveYear.objects.filter(employee=self.employee).count(),
            0
        )
        
        # Create LEAVE entry
        TimeEntry.objects.create(
            timesheet=ts,
            date=date(2025, 6, 15),
            kind=TimeEntry.Kind.LEAVE
        )
        
        # PTO year should be auto-created
        self.assertTrue(
            EmployeeLeaveYear.objects.filter(
                employee=self.employee,
                label_year=2025
            ).exists()
        )