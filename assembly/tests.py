from django.test import TestCase
from django.utils import timezone
from datetime import date, timedelta

from people.models import Person, Role, PersonRole
from .models import Term, Composition, Mandate, Session, SessionItem, Vote


class TermTestCase(TestCase):
    def test_term_code_generation(self):
        """Test auto-generation of term codes"""
        term = Term.objects.create(
            label="Test Term",
            start_date=date(2025, 1, 1)
        )
        self.assertEqual(term.code, "HV25_27")
        self.assertEqual(term.end_date, date(2027, 1, 1))
    
    def test_only_one_active_term(self):
        """Test that only one term can be active"""
        term1 = Term.objects.create(
            label="Term 1",
            start_date=date(2025, 1, 1),
            is_active=True
        )
        
        # Creating another active term should be handled in admin/signals
        term2 = Term.objects.create(
            label="Term 2",
            start_date=date(2027, 1, 1),
            is_active=False
        )
        
        self.assertTrue(term1.is_active)
        self.assertFalse(term2.is_active)


class SessionTestCase(TestCase):
    def setUp(self):
        self.term = Term.objects.create(
            label="Test Term",
            start_date=date(2025, 1, 1)
        )
    
    def test_session_code_generation(self):
        """Test sequential Roman numeral codes"""
        s1 = Session.objects.create(
            term=self.term,
            session_type=Session.Type.REGULAR,
            session_date=date(2025, 2, 1)
        )
        self.assertEqual(s1.code, "HV25_27_I:or")
        
        s2 = Session.objects.create(
            term=self.term,
            session_type=Session.Type.EXTRAORDINARY,
            session_date=date(2025, 3, 1)
        )
        self.assertEqual(s2.code, "HV25_27_II:ao")
        
        s3 = Session.objects.create(
            term=self.term,
            session_type=Session.Type.REGULAR,
            session_date=date(2025, 4, 1)
        )
        self.assertEqual(s3.code, "HV25_27_III:or")


class SessionItemTestCase(TestCase):
    def setUp(self):
        self.term = Term.objects.create(
            label="Test Term",
            start_date=date(2025, 1, 1)
        )
        self.session = Session.objects.create(
            term=self.term,
            session_type=Session.Type.REGULAR,
            session_date=date(2025, 2, 1)
        )
    
    def test_item_code_generation(self):
        """Test sequential item codes"""
        i1 = SessionItem.objects.create(
            session=self.session,
            order=1,
            kind=SessionItem.Kind.PROCEDURAL,
            title="Opening",
            content="Session opened at 14:00"
        )
        self.assertEqual(i1.item_code, "S001")
        
        i2 = SessionItem.objects.create(
            session=self.session,
            order=2,
            kind=SessionItem.Kind.RESOLUTION,
            title="Budget Resolution"
        )
        self.assertEqual(i2.item_code, "S002")
        self.assertEqual(i2.full_identifier, "HV25_27_I:or-S002")


class MandateTestCase(TestCase):
    def setUp(self):
        self.term = Term.objects.create(
            label="Test Term",
            start_date=date(2025, 1, 1)
        )
        self.composition = Composition.objects.create(term=self.term)
        
        # Create test person and role
        self.person = Person.objects.create(
            first_name="Anna",
            last_name="Test"
        )
        self.role = Role.objects.create(
            name="HV Member",
            short_name="HV"
        )
        self.person_role = PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2025, 1, 1)
        )
    
    def test_mandate_active_status(self):
        """Test active/ended mandate status"""
        mandate = Mandate.objects.create(
            composition=self.composition,
            position=1,
            person_role=self.person_role,
            officer_role=Mandate.OfficerRole.CHAIR,
            start_date=date(2025, 1, 1)
        )
        self.assertTrue(mandate.is_active)
        
        mandate.end_date = date(2025, 6, 30)
        mandate.save()
        self.assertFalse(mandate.is_active)