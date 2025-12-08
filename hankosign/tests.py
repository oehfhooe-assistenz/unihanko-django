# File: hankosign/tests.py
# Version: 1.0.2
# Author: vas
# Modified: 2025-12-08

from django.test import TestCase, TransactionTestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.utils import timezone
from datetime import timedelta
from unittest.mock import Mock, patch
import threading

from people.models import Person, Role, PersonRole
from hankosign.models import Action, Policy, Signatory, Signature
from hankosign.utils import (
    can_act, record_signature, sign_once, state_snapshot, 
    object_status, resolve_signatory, get_action
)

User = get_user_model()


class HankoSignTestMixin:
    """Mixin to set up common test fixtures."""
    
    def setUp(self):
        super().setUp()
        
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        
        # Create person and role
        self.person = Person.objects.create(
            first_name='Test',
            last_name='User',
            email='test@example.com',
            user=self.user
        )
        
        self.role = Role.objects.create(
            name='Test Role'
        )
        
        self.person_role = PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date='2025-01-01'
        )
        
        # Create signatory
        self.signatory = Signatory.objects.create(
            person_role=self.person_role,
            is_active=True,
            is_verified=True
        )
        
        # Create a dummy model to sign (use Person as target)
        self.target_obj = self.person
        
        # Create actions
        ct = ContentType.objects.get_for_model(Person)
        
        self.submit_action = Action.objects.create(
            verb='SUBMIT',
            stage='',
            scope=ct,
            human_label='Submit for review',
            is_repeatable=False
        )
        
        self.approve_action = Action.objects.create(
            verb='APPROVE',
            stage='WIREF',
            scope=ct,
            human_label='Approve (WiRef)',
            is_repeatable=False
        )
        
        self.approve_chair_action = Action.objects.create(
            verb='APPROVE',
            stage='CHAIR',
            scope=ct,
            human_label='Approve (Chair)',
            is_repeatable=False,
            require_distinct_signer=True
        )
        
        self.reject_action = Action.objects.create(
            verb='REJECT',
            stage='',
            scope=ct,
            human_label='Reject',
            is_repeatable=False
        )
        
        self.repeatable_action = Action.objects.create(
            verb='VERIFY',
            stage='',
            scope=ct,
            human_label='Verify',
            is_repeatable=True
        )
        
        # Create policies
        self.policy_submit = Policy.objects.create(
            role=self.role,
            action=self.submit_action
        )
        
        self.policy_approve = Policy.objects.create(
            role=self.role,
            action=self.approve_action
        )
        
        self.policy_repeatable = Policy.objects.create(
            role=self.role,
            action=self.repeatable_action
        )
        
        # Mock request
        self.factory = RequestFactory()
        self.request = self.factory.get('/')
        self.request.user = self.user
        self.request.META = {'REMOTE_ADDR': '127.0.0.1'}


class ActionModelTest(HankoSignTestMixin, TestCase):
    """Test Action model validation and constraints."""
    
    def test_action_code_property(self):
        """Test action_code property formats correctly."""
        self.assertEqual(
            self.submit_action.action_code,
            f"SUBMIT:-@people.person"
        )
        self.assertEqual(
            self.approve_action.action_code,
            f"APPROVE:WIREF@people.person"
        )
    
    def test_duplicate_action_prevented(self):
        """Test that duplicate actions are prevented."""
        ct = ContentType.objects.get_for_model(Person)
        
        with self.assertRaises(ValidationError) as ctx:
            Action.objects.create(
                verb='SUBMIT',
                stage='',
                scope=ct,
                human_label='Duplicate submit'
            )
        
        self.assertIn('already exists', str(ctx.exception))
    
    def test_action_str(self):
        """Test string representation."""
        self.assertIn('SUBMIT', str(self.submit_action))
        self.assertIn('Submit for review', str(self.submit_action))


class PolicyModelTest(HankoSignTestMixin, TestCase):
    """Test Policy model validation."""
    
    def test_duplicate_policy_prevented(self):
        """Test that duplicate policies are prevented."""
        with self.assertRaises(ValidationError) as ctx:
            Policy.objects.create(
                role=self.role,
                action=self.submit_action
            )
        
        self.assertIn('already exists', str(ctx.exception))
    
    def test_policy_requires_action(self):
        """Test that policy requires at least one action."""
        policy = Policy(role=self.role)
        # First save is allowed (for admin flow)
        policy.save()
        
        # But second save without action should fail
        with self.assertRaises(ValidationError) as ctx:
            policy.save()
        
        self.assertIn('Pick at least one Action', str(ctx.exception))
    
    def test_policy_str(self):
        """Test string representation."""
        self.assertIn('Test Role', str(self.policy_submit))
        self.assertIn('SUBMIT', str(self.policy_submit))


class SignatoryTest(HankoSignTestMixin, TestCase):
    """Test Signatory model."""
    
    def test_display_name(self):
        """Test display name defaults to person name."""
        self.assertEqual(self.signatory.display_name, 'Test User')
    
    def test_display_name_override(self):
        """Test name override."""
        self.signatory.name_override = 'Custom Name'
        self.signatory.save()
        self.assertEqual(self.signatory.display_name, 'Custom Name')
    
    def test_base_key_generated(self):
        """Test that base_key is auto-generated."""
        self.assertTrue(len(self.signatory.base_key) == 64)


class AuthorizationTest(HankoSignTestMixin, TestCase):
    """Test authorization logic (can_act function)."""
    
    def test_authorized_user_can_act(self):
        """Test that authorized user can perform action."""
        ok, reason, sig, action, pol = can_act(
            self.user, 
            self.submit_action, 
            self.target_obj
        )
        
        self.assertTrue(ok)
        self.assertIsNone(reason)
        self.assertEqual(sig, self.signatory)
        self.assertEqual(action, self.submit_action)
        self.assertEqual(pol, self.policy_submit)
    
    def test_unauthenticated_user_cannot_act(self):
        """Test that unauthenticated user cannot act."""
        anon_user = Mock()
        anon_user.is_authenticated = False
        
        ok, reason, sig, action, pol = can_act(
            anon_user,
            self.submit_action,
            self.target_obj
        )
        
        self.assertFalse(ok)
        self.assertIn('No active signatory', str(reason))
    
    def test_unverified_signatory_cannot_act(self):
        """Test that unverified signatory cannot act."""
        self.signatory.is_verified = False
        self.signatory.save()
        
        ok, reason, sig, action, pol = can_act(
            self.user,
            self.submit_action,
            self.target_obj
        )
        
        self.assertFalse(ok)
        self.assertIn('not verified', str(reason))
    
    def test_unauthorized_role_cannot_act(self):
        """Test that role without policy cannot act."""
        other_role = Role.objects.create(name='Other Role')
        self.person_role.role = other_role
        self.person_role.save()
        
        ok, reason, sig, action, pol = can_act(
            self.user,
            self.submit_action,
            self.target_obj
        )
        
        self.assertFalse(ok)
        self.assertIn('not authorized', str(reason))
    
    def test_unknown_action_fails(self):
        """Test that unknown action code fails."""
        ok, reason, sig, action, pol = can_act(
            self.user,
            'UNKNOWN:STAGE@people.person',
            self.target_obj
        )
        
        self.assertFalse(ok)
        self.assertIn('Unknown action', str(reason))
    
    def test_separation_of_duties_enforced(self):
        """Test that same signatory cannot sign multiple stages."""
        # Create policy for chair approval
        Policy.objects.create(
            role=self.role,
            action=self.approve_chair_action
        )
        
        # First signature (WIREF)
        record_signature(
            self.request,
            self.user,
            self.approve_action,
            self.target_obj
        )
        
        # Try second signature (CHAIR) - should fail
        ok, reason, sig, action, pol = can_act(
            self.user,
            self.approve_chair_action,
            self.target_obj
        )
        
        self.assertFalse(ok)
        self.assertIn('different signatory', str(reason))


class SignatureCreationTest(HankoSignTestMixin, TestCase):
    """Test signature creation logic."""
    
    def test_create_signature(self):
        """Test basic signature creation."""
        sig = record_signature(
            self.request,
            self.user,
            self.submit_action,
            self.target_obj,
            note='Test note'
        )
        
        self.assertIsNotNone(sig)
        self.assertEqual(sig.signatory, self.signatory)
        self.assertEqual(sig.verb, 'SUBMIT')
        self.assertEqual(sig.stage, '')
        self.assertEqual(sig.note, 'Test note')
        self.assertTrue(len(sig.signature_id) > 0)
    
    def test_signature_id_is_hmac(self):
        """Test that signature_id is HMAC hash."""
        sig = record_signature(
            self.request,
            self.user,
            self.submit_action,
            self.target_obj
        )
        
        # HMAC SHA256 produces 64 hex characters
        self.assertEqual(len(sig.signature_id), 64)
        self.assertTrue(all(c in '0123456789abcdef' for c in sig.signature_id))
    
    def test_ip_address_captured(self):
        """Test that IP address is captured."""
        sig = record_signature(
            self.request,
            self.user,
            self.submit_action,
            self.target_obj
        )
        
        self.assertEqual(sig.ip_address, '127.0.0.1')
    
    def test_non_repeatable_enforced(self):
        """Test that non-repeatable actions cannot be repeated."""
        # First signature succeeds
        sig1 = record_signature(
            self.request,
            self.user,
            self.submit_action,
            self.target_obj
        )
        self.assertIsNotNone(sig1)
        
        # Second signature fails
        with self.assertRaises(PermissionDenied) as ctx:
            record_signature(
                self.request,
                self.user,
                self.submit_action,
                self.target_obj
            )
        
        self.assertIn('already been performed', str(ctx.exception))
    
    def test_repeatable_actions_allowed(self):
        """Test that repeatable actions can be repeated."""
        # First signature
        sig1 = record_signature(
            self.request,
            self.user,
            self.repeatable_action,
            self.target_obj
        )
        
        # Mock timezone.now() to be 11 seconds later (outside dedupe window)
        future_time = timezone.now() + timedelta(seconds=11)
        with patch('hankosign.utils.timezone.now', return_value=future_time):
            # Second signature succeeds and creates new record
            sig2 = record_signature(
                self.request,
                self.user,
                self.repeatable_action,
                self.target_obj
            )
        
        self.assertIsNotNone(sig2)
        self.assertNotEqual(sig1.id, sig2.id)
    
    def test_soft_dedupe_window(self):
        """Test that duplicate submissions within 10s are ignored."""
        # First signature
        sig1 = record_signature(
            self.request,
            self.user,
            self.repeatable_action,
            self.target_obj
        )
        
        # Immediate duplicate returns same signature
        sig2 = record_signature(
            self.request,
            self.user,
            self.repeatable_action,
            self.target_obj
        )
        
        self.assertEqual(sig1.id, sig2.id)
    
    def test_unauthorized_signature_fails(self):
        """Test that signature without authorization fails."""
        # Remove policy
        self.policy_submit.delete()
        
        with self.assertRaises(PermissionDenied):
            record_signature(
                self.request,
                self.user,
                self.submit_action,
                self.target_obj
            )


class StateSnapshotTest(HankoSignTestMixin, TestCase):
    """Test state snapshot logic."""
    
    def test_empty_state(self):
        """Test state snapshot for object with no signatures."""
        state = state_snapshot(self.target_obj)
        
        self.assertFalse(state['submitted'])
        self.assertEqual(state['approved'], set())
        self.assertFalse(state['rejected'])
        self.assertFalse(state['final'])
        self.assertFalse(state['locked'])
    
    def test_submitted_state(self):
        """Test submitted state after SUBMIT signature."""
        record_signature(
            self.request,
            self.user,
            self.submit_action,
            self.target_obj
        )
        
        state = state_snapshot(self.target_obj)
        
        self.assertTrue(state['submitted'])
        self.assertTrue(state['locked'])
    
    def test_approved_state(self):
        """Test approved state tracking."""
        # Submit first
        record_signature(
            self.request,
            self.user,
            self.submit_action,
            self.target_obj
        )
        
        # Approve
        record_signature(
            self.request,
            self.user,
            self.approve_action,
            self.target_obj
        )
        
        state = state_snapshot(self.target_obj)
        
        self.assertIn('WIREF', state['approved'])
        self.assertTrue(state['locked'])
    
    def test_rejected_state(self):
        """Test rejected state."""
        record_signature(
            self.request,
            self.user,
            self.submit_action,
            self.target_obj
        )
        
        # Add policy for reject
        Policy.objects.create(
            role=self.role,
            action=self.reject_action
        )
        
        record_signature(
            self.request,
            self.user,
            self.reject_action,
            self.target_obj
        )
        
        state = state_snapshot(self.target_obj)
        
        self.assertTrue(state['rejected'])
    
    def test_required_approvals(self):
        """Test that required approvals are detected from Actions."""
        state = state_snapshot(self.target_obj)
        
        # Should detect WIREF and CHAIR as required (from Action configs)
        self.assertIn('WIREF', state['required'])
        self.assertIn('CHAIR', state['required'])


class ObjectStatusTest(HankoSignTestMixin, TestCase):
    """Test object_status function."""
    
    def test_draft_status(self):
        """Test draft status for unsigned object."""
        status = object_status(self.target_obj)
        
        self.assertEqual(status['code'], 'draft')
        self.assertEqual(status['label'], 'Draft')
    
    def test_submitted_status(self):
        """Test submitted status."""
        record_signature(
            self.request,
            self.user,
            self.submit_action,
            self.target_obj
        )
        
        status = object_status(self.target_obj)
        
        self.assertEqual(status['code'], 'submitted')
    
    def test_approved_tier1_status(self):
        """Test tier1 approval status."""
        record_signature(
            self.request,
            self.user,
            self.submit_action,
            self.target_obj
        )
        
        record_signature(
            self.request,
            self.user,
            self.approve_action,
            self.target_obj
        )
        
        status = object_status(self.target_obj)
        
        self.assertEqual(status['code'], 'approved-tier1')
    
    def test_rejected_status(self):
        """Test rejected status takes precedence."""
        record_signature(
            self.request,
            self.user,
            self.submit_action,
            self.target_obj
        )
        
        Policy.objects.create(
            role=self.role,
            action=self.reject_action
        )
        
        record_signature(
            self.request,
            self.user,
            self.reject_action,
            self.target_obj
        )
        
        status = object_status(self.target_obj)
        
        self.assertEqual(status['code'], 'rejected')


class IdempotencyTest(HankoSignTestMixin, TestCase):
    """Test sign_once idempotency."""
    
    def test_sign_once_creates_signature(self):
        """Test that sign_once creates signature."""
        self.request.GET = {'rid': 'test123'}
        
        sig = sign_once(
            self.request,
            self.submit_action,
            self.target_obj,
            note='Test'
        )
        
        self.assertIsNotNone(sig)
        self.assertEqual(sig.verb, 'SUBMIT')
    
    def test_sign_once_prevents_duplicates(self):
        """Test that sign_once with same RID doesn't duplicate."""
        self.request.GET = {'rid': 'test123'}
        
        sig1 = sign_once(
            self.request,
            self.repeatable_action,
            self.target_obj
        )
        
        # Same RID should return same signature
        sig2 = sign_once(
            self.request,
            self.repeatable_action,
            self.target_obj
        )
        
        self.assertEqual(sig1.id, sig2.id)


class UtilityFunctionTest(HankoSignTestMixin, TestCase):
    """Test utility functions."""
    
    def test_resolve_signatory(self):
        """Test resolve_signatory finds active signatory."""
        sig = resolve_signatory(self.user)
        
        self.assertEqual(sig, self.signatory)
    
    def test_resolve_signatory_inactive(self):
        """Test that inactive signatory is not resolved."""
        self.signatory.is_active = False
        self.signatory.save()
        
        sig = resolve_signatory(self.user)
        
        self.assertIsNone(sig)
    
    def test_get_action_by_code(self):
        """Test get_action parses action code."""
        action = get_action('APPROVE:WIREF@people.person')
        
        self.assertEqual(action, self.approve_action)
    
    def test_get_action_with_dash(self):
        """Test get_action handles empty stage with dash."""
        action = get_action('SUBMIT:-@people.person')
        
        self.assertEqual(action, self.submit_action)
    
    def test_get_action_invalid_code(self):
        """Test get_action returns None for invalid code."""
        action = get_action('INVALID')
        
        self.assertIsNone(action)


class ConcurrentSignatureTest(HankoSignTestMixin, TransactionTestCase):
    """Test concurrent signature attempts (requires PostgreSQL)."""
    
    def test_concurrent_non_repeatable_signature(self):
        """Test that only one concurrent signature succeeds."""
        if 'sqlite' in connection.vendor:
            self.skipTest("SQLite doesn't support true concurrency")
        
        results = {'created': [], 'errors': []}
        barrier = threading.Barrier(2)
        
        def attempt_signature(thread_id):
            try:
                barrier.wait()  # Sync both threads
                sig = record_signature(
                    self.request,
                    self.user,
                    self.submit_action,
                    self.target_obj
                )
                results['created'].append((thread_id, sig.id))
            except PermissionDenied:
                results['errors'].append(thread_id)
        
        t1 = threading.Thread(target=attempt_signature, args=(1,))
        t2 = threading.Thread(target=attempt_signature, args=(2,))
        
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        # Exactly one succeeds, one fails
        self.assertEqual(len(results['created']), 1)
        self.assertEqual(len(results['errors']), 1)
        
        # Only one signature in DB
        ct = ContentType.objects.get_for_model(Person)
        count = Signature.objects.filter(
            content_type=ct,
            object_id=self.target_obj.pk,
            verb='SUBMIT'
        ).count()
        self.assertEqual(count, 1)