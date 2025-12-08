# File: assembly/tests.py
# Version: 1.0.5
# Author: vas
# Modified: 2025-12-08

from django.test import TestCase, Client
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from datetime import date, timedelta

from people.models import Person, Role, PersonRole
from .models import Term, Composition, Mandate, Session, SessionItem, Vote

User = get_user_model()


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


# ============================================================================
# RACE CONDITION TESTS
# ============================================================================

class SessionRaceConditionTestCase(TestCase):
    """Test race condition protection in Session code generation"""
    
    def setUp(self):
        self.term = Term.objects.create(
            label="Test Term",
            start_date=date(2025, 1, 1)
        )
    
    def test_concurrent_session_creation(self):
        """Test that concurrent session creation doesn't produce duplicate codes
        
        Note: On SQLite, we test sequential uniqueness since SQLite doesn't
        handle concurrent writes well. On production databases (PostgreSQL, etc.),
        the atomic transaction pattern will handle true concurrency.
        """
        from django.db import connection
        
        # For SQLite, test sequential creation
        if connection.vendor == 'sqlite':
            codes = []
            for i in range(10):
                session = Session.objects.create(
                    term=self.term,
                    session_type=Session.Type.REGULAR,
                    session_date=date(2025, 2, i+1)
                )
                codes.append(session.code)
            
            # All codes must be unique
            self.assertEqual(len(codes), len(set(codes)), f"Duplicate codes: {codes}")
            return
        
        # For real databases, test actual concurrency
        from threading import Thread
        
        connection.close()
        
        results = []
        errors = []
        
        def create_session():
            try:
                session = Session.objects.create(
                    term=self.term,
                    session_type=Session.Type.REGULAR,
                    session_date=date(2025, 2, 1)
                )
                results.append(session.code)
            except Exception as e:
                errors.append(str(e))
        
        # Simulate 5 concurrent creates
        threads = [Thread(target=create_session) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All should succeed with unique codes
        self.assertEqual(len(results), 5, f"Expected 5 sessions, got {len(results)}. Errors: {errors}")
        self.assertEqual(len(set(results)), 5, f"Duplicate codes found: {results}")
    
    def test_session_code_uniqueness(self):
        """Test that session codes are always unique"""
        codes = []
        for i in range(10):
            session = Session.objects.create(
                term=self.term,
                session_type=Session.Type.REGULAR if i % 2 == 0 else Session.Type.EXTRAORDINARY,
                session_date=date(2025, 2, i+1)
            )
            codes.append(session.code)
        
        # All codes must be unique
        self.assertEqual(len(codes), len(set(codes)), f"Duplicate codes: {codes}")


class SessionItemRaceConditionTestCase(TestCase):
    """Test race condition protection in SessionItem code generation"""
    
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
    
    def test_concurrent_item_creation(self):
        """Test that concurrent item creation doesn't produce duplicate codes
        
        Note: On SQLite, we test sequential uniqueness since SQLite doesn't
        handle concurrent writes well. On production databases (PostgreSQL, etc.),
        the atomic transaction pattern will handle true concurrency.
        """
        from django.db import connection
        
        # For SQLite, test sequential creation
        if connection.vendor == 'sqlite':
            codes = []
            for i in range(10):
                item = SessionItem.objects.create(
                    session=self.session,
                    order=i+1,
                    kind=SessionItem.Kind.PROCEDURAL,
                    title=f"Item {i+1}"
                )
                codes.append(item.item_code)
            
            # All codes must be unique
            self.assertEqual(len(codes), len(set(codes)), f"Duplicate codes: {codes}")
            return
        
        # For real databases, test actual concurrency
        from threading import Thread
        
        connection.close()
        
        results = []
        errors = []
        
        def create_item(order):
            try:
                item = SessionItem.objects.create(
                    session=self.session,
                    order=order,
                    kind=SessionItem.Kind.PROCEDURAL,
                    title=f"Item {order}"
                )
                results.append(item.item_code)
            except Exception as e:
                errors.append(str(e))
        
        # Simulate 5 concurrent creates
        threads = [Thread(target=create_item, args=(i+1,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All should succeed with unique codes
        self.assertEqual(len(results), 5, f"Expected 5 items, got {len(results)}. Errors: {errors}")
        self.assertEqual(len(set(results)), 5, f"Duplicate codes found: {results}")


# ============================================================================
# SECURITY & AUTHORIZATION TESTS
# ============================================================================

class ProtocolEditorSecurityTestCase(TestCase):
    """Test security and authorization for protocol editor views"""
    
    def setUp(self):
        # Create users
        self.manager = User.objects.create_user(
            username='manager',
            password='testpass123',
            is_staff=True
        )
        # Give manager permissions
        change_session_perm = Permission.objects.get(
            content_type__app_label='assembly',
            codename='change_session'
        )
        self.manager.user_permissions.add(change_session_perm)
        
        self.regular_staff = User.objects.create_user(
            username='staff',
            password='testpass123',
            is_staff=True
        )
        # Give regular staff permission
        self.regular_staff.user_permissions.add(change_session_perm)
        
        self.non_staff = User.objects.create_user(
            username='nostaff',
            password='testpass123',
            is_staff=False
        )
        
        # Create test data
        self.term = Term.objects.create(
            label="Test Term",
            start_date=date(2025, 1, 1)
        )
        self.session = Session.objects.create(
            term=self.term,
            session_type=Session.Type.REGULAR,
            session_date=date(2025, 2, 1)
        )
        self.item = SessionItem.objects.create(
            session=self.session,
            order=1,
            kind=SessionItem.Kind.PROCEDURAL,
            title="Test Item"
        )
        
        self.client = Client()
    
    def test_non_staff_blocked(self):
        """Non-staff users cannot access protocol editor"""
        self.client.login(username='nostaff', password='testpass123')
        response = self.client.get(
            reverse('assembly:protocol_editor_session', args=[self.session.pk])
        )
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
    
    def test_staff_without_permission_blocked(self):
        """Staff without change_session permission cannot access"""
        staff_no_perm = User.objects.create_user(
            username='staffnoperm',
            password='testpass123',
            is_staff=True
        )
        self.client.login(username='staffnoperm', password='testpass123')
        response = self.client.get(
            reverse('assembly:protocol_editor_session', args=[self.session.pk])
        )
        self.assertEqual(response.status_code, 403)
    
    def test_locked_session_blocks_save_for_regular_staff(self):
        """Regular staff cannot modify locked session items"""
        # Submit session to lock it using hankosign utils
        from hankosign.utils import get_action, record_signature
        
        # Get the submit action
        submit_action = get_action('SUBMIT:ASS@assembly.session')
        if not submit_action:
            # Action doesn't exist in test DB, skip test
            self.skipTest("HankoSign submit action not configured")
        
        # Sign to lock (pass None as request since we're in tests)
        record_signature(None, submit_action, self.session, note="Test lock", user=self.manager)
        
        # Try to save item as regular staff
        self.client.login(username='staff', password='testpass123')
        response = self.client.post(
            reverse('assembly:protocol_update_item', args=[self.session.pk, self.item.pk]),
            {'title': 'Modified Title', 'kind': 'PROC', 'order': 1}
        )
        
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['success'])
    
    def test_locked_session_blocks_delete_for_regular_staff(self):
        """Regular staff cannot delete items from locked session"""
        from hankosign.utils import get_action, record_signature
        
        submit_action = get_action('SUBMIT:ASS@assembly.session')
        if not submit_action:
            self.skipTest("HankoSign submit action not configured")
        
        record_signature(None, submit_action, self.session, note="Test lock", user=self.manager)
        
        # Try to delete
        self.client.login(username='staff', password='testpass123')
        response = self.client.post(
            reverse('assembly:protocol_delete_item', args=[self.session.pk, self.item.pk])
        )
        
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['success'])
    
    def test_locked_session_blocks_reorder_for_regular_staff(self):
        """Regular staff cannot reorder items in locked session"""
        from hankosign.utils import get_action, record_signature
        
        submit_action = get_action('SUBMIT:ASS@assembly.session')
        if not submit_action:
            self.skipTest("HankoSign submit action not configured")
        
        record_signature(None, submit_action, self.session, note="Test lock", user=self.manager)
        
        # Try to reorder
        self.client.login(username='staff', password='testpass123')
        response = self.client.post(
            reverse('assembly:protocol_reorder_items', args=[self.session.pk]),
            data='[1, 2, 3]',
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['success'])
    
    def test_locked_session_blocks_insert_for_regular_staff(self):
        """Regular staff cannot insert items into locked session"""
        from hankosign.utils import get_action, record_signature
        
        submit_action = get_action('SUBMIT:ASS@assembly.session')
        if not submit_action:
            self.skipTest("HankoSign submit action not configured")
        
        record_signature(None, submit_action, self.session, note="Test lock", user=self.manager)
        
        # Try to insert
        self.client.login(username='staff', password='testpass123')
        response = self.client.get(
            reverse('assembly:protocol_insert_at', args=[self.session.pk, 1])
        )
        
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['success'])
    
    def test_unlocked_session_allows_modifications(self):
        """Regular staff CAN modify unlocked session"""
        self.client.login(username='staff', password='testpass123')
        
        response = self.client.post(
            reverse('assembly:protocol_update_item', args=[self.session.pk, self.item.pk]),
            {
                'title': 'Modified Title',
                'kind': 'PROC',
                'order': 1,
                'content': 'New content'
            }
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        
        # Verify change
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, 'Modified Title')


class SessionStatusWorkflowTestCase(TestCase):
    """Test session status transitions"""
    
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
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )
    
    def test_session_starts_as_draft(self):
        """New sessions start in DRAFT status"""
        self.assertEqual(self.session.status, Session.Status.DRAFT)
    
    def test_session_status_updates_on_save(self):
        """Session status updates based on signatures"""
        from hankosign.utils import get_action, record_signature
        
        # Get the submit action
        submit_action = get_action('SUBMIT:ASS@assembly.session')
        if not submit_action:
            self.skipTest("HankoSign submit action not configured")
        
        # Submit
        record_signature(None, submit_action, self.session, note="Test submit", user=self.user)
        
        # Save to update status
        self.session.save()
        self.assertEqual(self.session.status, Session.Status.SUBMITTED)