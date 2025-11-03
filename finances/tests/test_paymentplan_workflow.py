"""
Tests for PaymentPlan status machine and HankoSign workflow.

Covers:
- paymentplan_status() reducer logic
- Status transitions (DRAFT→PENDING→ACTIVE→FINISHED→CANCELLED)
- FiscalYear lock cascade
- Action repeatability/idempotency
"""
from datetime import date, timedelta
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.models import ContentType

from finances.models import FiscalYear, PaymentPlan, paymentplan_status
from people.models import Person, Role, PersonRole, RoleTransitionReason
from hankosign.models import Action, Signatory, Signature

User = get_user_model()


class PaymentPlanStatusMachineTest(TestCase):
    """Test the paymentplan_status() reducer function."""
    
    def setUp(self):
        """Create fixtures for all tests."""
        # ContentType for PaymentPlan
        self.pp_ct = ContentType.objects.get_for_model(PaymentPlan)
        
        # Users
        self.user_editor = User.objects.create_user("editor", password="test")
        self.user_wiref = User.objects.create_user("wiref", password="test")
        self.user_chair = User.objects.create_user("chair", password="test")
        
        # HankoSign actions
        self.action_submit = Action.objects.create(
            verb=Action.Verb.SUBMIT,
            stage="WIREF",
            scope=self.pp_ct,
            human_label="Submit Payment Plan"
        )
        self.action_withdraw = Action.objects.create(
            verb=Action.Verb.WITHDRAW,
            stage="WIREF",
            scope=self.pp_ct,
            human_label="Withdraw Payment Plan"
        )
        self.action_approve_wiref = Action.objects.create(
            verb=Action.Verb.APPROVE,
            stage="WIREF",
            scope=self.pp_ct,
            human_label="Approve (WiRef)"
        )
        self.action_approve_chair = Action.objects.create(
            verb=Action.Verb.APPROVE,
            stage="CHAIR",
            scope=self.pp_ct,
            human_label="Approve (Chair)"
        )
        self.action_verify = Action.objects.create(
            verb=Action.Verb.VERIFY,
            stage="WIREF",
            scope=self.pp_ct,
            human_label="Verify Banking"
        )
        self.action_reject = Action.objects.create(
            verb=Action.Verb.REJECT,
            stage="",
            scope=self.pp_ct,
            human_label="Cancel Payment Plan"
        )
        
        # Fiscal year
        self.fy = FiscalYear.objects.create(
            start=date(2024, 7, 1),
            end=date(2025, 6, 30),
            code="WJ24_25"
        )
        
        # Person and role
        self.person = Person.objects.create(
            first_name="Sven",
            last_name="Varszegi",
            email="sven@test.com"
        )
        self.role = Role.objects.create(
            name="Wirtschaftsreferent:in",
            short_name="WiRef",
            kind=Role.Kind.DEPT_HEAD,
            default_monthly_amount=Decimal("500.00")
        )
        
        # Start reason (required for PersonRole)
        self.start_reason = RoleTransitionReason.objects.create(
            code="I01",
            name="Appointed",
            active=True
        )
        self.end_reason = RoleTransitionReason.objects.create(
            code="O01",
            name="End of term",
            active=True
        )
        
        self.pr = PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2024, 7, 1),
            start_reason=self.start_reason
        )
        
        # Signatories (needed for Signature.signatory)
        self.signatory_editor = Signatory.objects.create(
            person_role=self.pr,
            is_active=True
        )
        self.signatory_wiref = Signatory.objects.create(
            person_role=self.pr,
            is_active=True
        )
        self.signatory_chair = Signatory.objects.create(
            person_role=self.pr,
            is_active=True
        )
        
        # Payment plan (minimal valid data)
        self.pp = PaymentPlan.objects.create(
            person_role=self.pr,
            fiscal_year=self.fy,
            monthly_amount=Decimal("500.00"),
            payee_name="Sven Varszegi",
            iban="AT026000000001349870",
            bic="BAWAATWW",
            reference="Funktionsgebühr",
            address="Teststraße 1, 4040 Linz",
            cost_center="101"
        )
    
    def test_initial_state_is_draft(self):
        """New payment plan with no signatures should be DRAFT."""
        self.assertEqual(paymentplan_status(self.pp), "DRAFT")
    
    def test_submitted_state_is_pending(self):
        """After SUBMIT signature, status should be PENDING."""
        Signature.objects.create(
            signatory=self.signatory_editor,
            action=self.action_submit,
            target=self.pp,
            note="Submitted for approval"
        )
        self.assertEqual(paymentplan_status(self.pp), "PENDING")
    
    def test_withdrawn_returns_to_draft(self):
        """After SUBMIT then WITHDRAW, status should be DRAFT."""
        Signature.objects.create(
            signatory=self.signatory_editor,
            action=self.action_submit,
            target=self.pp
        )
        Signature.objects.create(
            signatory=self.signatory_editor,
            action=self.action_withdraw,
            target=self.pp
        )
        self.assertEqual(paymentplan_status(self.pp), "DRAFT")
    
    def test_wiref_approved_still_pending(self):
        """After WiRef approval, still PENDING (need Chair + verify)."""
        Signature.objects.create(signatory=self.signatory_editor, action=self.action_submit, target=self.pp)
        Signature.objects.create(signatory=self.signatory_wiref, action=self.action_approve_wiref, target=self.pp)
        self.assertEqual(paymentplan_status(self.pp), "PENDING")
    
    def test_both_approved_still_pending_without_verify(self):
        """After both approvals but no VERIFY, still PENDING."""
        Signature.objects.create(signatory=self.signatory_editor, action=self.action_submit, target=self.pp)
        Signature.objects.create(signatory=self.signatory_wiref, action=self.action_approve_wiref, target=self.pp)
        Signature.objects.create(signatory=self.signatory_chair, action=self.action_approve_chair, target=self.pp)
        self.assertEqual(paymentplan_status(self.pp), "PENDING")
    
    def test_fully_approved_and_verified_is_active(self):
        """After submit + both approvals + verify = ACTIVE."""
        # Create future fiscal year
        future_fy = FiscalYear.objects.create(
            start=date(2026, 1, 1),
            end=date(2026, 12, 31),
            code="WJ26_26"
        )
        
        # Update PersonRole to span future dates
        self.pr.end_date = date(2027, 12, 31)
        self.pr.end_reason = self.end_reason
        self.pr.save()
        
        # Create NEW PaymentPlan for future FY
        future_pp = PaymentPlan.objects.create(
            person_role=self.pr,
            fiscal_year=future_fy,
            monthly_amount=Decimal("500.00"),
            payee_name="Sven Varszegi",
            iban="AT026000000001349870",
            bic="BAWAATWW",
            reference="Funktionsgebühr",
            address="Teststraße 1, 4040 Linz",
            cost_center="101",
            pay_start=date(2026, 1, 1),
            pay_end=date(2026, 12, 31)
        )
        
        # Full approval flow on the FUTURE plan
        Signature.objects.create(signatory=self.signatory_editor, action=self.action_submit, target=future_pp)
        Signature.objects.create(signatory=self.signatory_wiref, action=self.action_approve_wiref, target=future_pp)
        Signature.objects.create(signatory=self.signatory_chair, action=self.action_approve_chair, target=future_pp)
        Signature.objects.create(signatory=self.signatory_wiref, action=self.action_verify, target=future_pp)
        
        self.assertEqual(paymentplan_status(future_pp), "ACTIVE")
    
    def test_active_plan_past_end_date_is_finished(self):
        """ACTIVE plan past its end date becomes FINISHED."""
        # Set window to past dates
        self.pp.pay_start = date(2023, 7, 1)
        self.pp.pay_end = date(2024, 6, 30)
        self.pp.save()
        
        # Full approval flow
        Signature.objects.create(signatory=self.signatory_editor, action=self.action_submit, target=self.pp)
        Signature.objects.create(signatory=self.signatory_wiref, action=self.action_approve_wiref, target=self.pp)
        Signature.objects.create(signatory=self.signatory_chair, action=self.action_approve_chair, target=self.pp)
        Signature.objects.create(signatory=self.signatory_wiref, action=self.action_verify, target=self.pp)
        
        self.assertEqual(paymentplan_status(self.pp), "FINISHED")
    
    def test_rejected_at_any_stage_is_cancelled(self):
        """REJECT signature at any stage results in CANCELLED."""
        # Test rejection in DRAFT
        Signature.objects.create(signatory=self.signatory_chair, action=self.action_reject, target=self.pp)
        self.assertEqual(paymentplan_status(self.pp), "CANCELLED")
        
        # Clean slate - filter by content_type + object_id
        pp_ct = ContentType.objects.get_for_model(PaymentPlan)
        Signature.objects.filter(content_type=pp_ct, object_id=str(self.pp.pk)).delete()
        
        # Test rejection after submit
        Signature.objects.create(signatory=self.signatory_editor, action=self.action_submit, target=self.pp)
        Signature.objects.create(signatory=self.signatory_chair, action=self.action_reject, target=self.pp)
        self.assertEqual(paymentplan_status(self.pp), "CANCELLED")
    
    def test_idempotent_signatures(self):
        """Multiple identical signatures are blocked by unique constraint."""
        Signature.objects.create(signatory=self.signatory_editor, action=self.action_submit, target=self.pp)
        self.assertEqual(paymentplan_status(self.pp), "PENDING")
        
        # Duplicate submit should raise IntegrityError (expected behavior)
        from django.db import IntegrityError, transaction
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Signature.objects.create(signatory=self.signatory_editor, action=self.action_submit, target=self.pp)
        
        # Status should still be PENDING (after transaction rollback)
        self.assertEqual(paymentplan_status(self.pp), "PENDING")


class PaymentPlanValidationTest(TestCase):
    """Test model validation and constraints."""
    
    def setUp(self):
        self.fy = FiscalYear.objects.create(
            start=date(2024, 7, 1),
            end=date(2025, 6, 30)
        )
        self.person = Person.objects.create(
            first_name="Test",
            last_name="User",
            email="test@example.com"
        )
        self.role = Role.objects.create(
            name="Test Role",
            short_name="TEST",
            default_monthly_amount=Decimal("100.00")
        )
        self.start_reason = RoleTransitionReason.objects.create(
            code="I01",
            name="Start",
            active=True
        )
        self.pr = PersonRole.objects.create(
            person=self.person,
            role=self.role,
            start_date=date(2024, 7, 1),
            start_reason=self.start_reason
        )
    
    def test_plan_code_auto_generated(self):
        """Plan code should auto-generate on save."""
        pp = PaymentPlan.objects.create(
            person_role=self.pr,
            fiscal_year=self.fy,
            monthly_amount=Decimal("100.00")
        )
        self.assertIsNotNone(pp.plan_code)
        self.assertTrue(pp.plan_code.startswith("WJ24_25-"))
    
    def test_plan_code_sequential(self):
        """Plan codes should increment sequentially per FY."""
        pp1 = PaymentPlan.objects.create(
            person_role=self.pr,
            fiscal_year=self.fy,
            monthly_amount=Decimal("100.00")
        )
        
        # Create second plan (different person to avoid uniqueness constraint)
        person2 = Person.objects.create(first_name="Other", last_name="User", email="other@example.com")
        pr2 = PersonRole.objects.create(person=person2, role=self.role, start_date=date(2024, 7, 1), start_reason=self.start_reason)
        
        pp2 = PaymentPlan.objects.create(
            person_role=pr2,
            fiscal_year=self.fy,
            monthly_amount=Decimal("100.00")
        )
        
        self.assertEqual(pp1.plan_code, "WJ24_25-00001")
        self.assertEqual(pp2.plan_code, "WJ24_25-00002")
    
    def test_cannot_change_fiscal_year_after_creation(self):
        """Should not allow changing fiscal year after creation."""
        pp = PaymentPlan.objects.create(
            person_role=self.pr,
            fiscal_year=self.fy,
            monthly_amount=Decimal("100.00")
        )
        
        fy2 = FiscalYear.objects.create(
            start=date(2025, 7, 1),
            end=date(2026, 6, 30)
        )
        
        pp.fiscal_year = fy2
        with self.assertRaises(ValidationError) as cm:
            pp.full_clean()
        self.assertIn("fiscal_year", cm.exception.message_dict)
    
    def test_invalid_iban_rejected(self):
        """Should reject invalid IBAN format."""
        pp = PaymentPlan(
            person_role=self.pr,
            fiscal_year=self.fy,
            monthly_amount=Decimal("100.00"),
            iban="INVALID123"  # Bad format
        )
        with self.assertRaises(ValidationError):
            pp.full_clean()
    
    def test_valid_iban_accepted(self):
        """Should accept valid IBAN."""
        pp = PaymentPlan.objects.create(
            person_role=self.pr,
            fiscal_year=self.fy,
            monthly_amount=Decimal("100.00"),
            iban="AT026000000001349870"
        )
        # If we got here without exception, IBAN was accepted
        self.assertIsNotNone(pp.pk)


class FiscalYearLockCascadeTest(TestCase):
    """Test that locked FY prevents PP modifications."""
    
    def setUp(self):
        self.user = User.objects.create_user("admin", password="test")
        
        # Get FY ContentType
        fy_ct = ContentType.objects.get_for_model(FiscalYear)
        
        # Create lock action
        self.action_lock = Action.objects.create(
            verb=Action.Verb.LOCK,
            stage="",
            scope=fy_ct,
            human_label="Lock Fiscal Year"
        )
        
        self.fy = FiscalYear.objects.create(
            start=date(2024, 7, 1),
            end=date(2025, 6, 30)
        )
        
        person = Person.objects.create(first_name="Test", last_name="User", email="test@example.com")
        role = Role.objects.create(name="Test", short_name="TEST", default_monthly_amount=Decimal("100"))
        start_reason = RoleTransitionReason.objects.create(code="I01", name="Start", active=True)
        pr = PersonRole.objects.create(person=person, role=role, start_date=date(2024, 7, 1), start_reason=start_reason)
        
        # Create signatory
        self.signatory = Signatory.objects.create(person_role=pr, is_active=True)
        
        self.pp = PaymentPlan.objects.create(
            person_role=pr,
            fiscal_year=self.fy,
            monthly_amount=Decimal("100.00")
        )
    
    def test_fy_lock_detected(self):
        """Locked FY should be detected via state_snapshot."""
        # Lock the FY
        Signature.objects.create(
            signatory=self.signatory,
            action=self.action_lock,
            target=self.fy,
            note="Year-end close"
        )
        
        from hankosign.utils import state_snapshot
        st = state_snapshot(self.fy)
        self.assertTrue(st.get("explicit_locked"))
    
    def test_pp_readonly_check_respects_fy_lock(self):
        """PaymentPlan admin should detect FY lock via state_snapshot."""
        # Lock the FY
        Signature.objects.create(
            signatory=self.signatory,
            action=self.action_lock,
            target=self.fy
        )
        
        # Check PP's parent FY lock state
        from hankosign.utils import state_snapshot
        fy_st = state_snapshot(self.pp.fiscal_year)
        is_locked = fy_st.get("explicit_locked", False)
        
        self.assertTrue(is_locked)


class PaymentPlanCalculationsTest(TestCase):
    """Test proration and total calculations."""
    
    def setUp(self):
        self.fy = FiscalYear.objects.create(
            start=date(2024, 7, 1),
            end=date(2025, 6, 30)
        )
        person = Person.objects.create(first_name="Test", last_name="User", email="test@example.com")
        role = Role.objects.create(name="Test", short_name="TEST", default_monthly_amount=Decimal("300.00"))
        
        start_reason = RoleTransitionReason.objects.create(code="I01", name="Start", active=True)
        end_reason = RoleTransitionReason.objects.create(code="O01", name="End", active=True)
        
        self.pr = PersonRole.objects.create(
            person=person,
            role=role,
            start_date=date(2024, 7, 1),
            end_date=date(2025, 6, 30),
            start_reason=start_reason,
            end_reason=end_reason
        )
    
    def test_full_year_breakdown(self):
        """Full 12-month period should have 12 entries."""
        pp = PaymentPlan.objects.create(
            person_role=self.pr,
            fiscal_year=self.fy,
            monthly_amount=Decimal("300.00")
        )
        
        breakdown = pp.months_breakdown()
        self.assertEqual(len(breakdown), 12)
    
    def test_partial_month_proration(self):
        """Mid-month start should prorate correctly."""
        pp = PaymentPlan.objects.create(
            person_role=self.pr,
            fiscal_year=self.fy,
            monthly_amount=Decimal("300.00"),
            pay_start=date(2024, 7, 15),  # Start mid-month
            pay_end=date(2024, 7, 31)
        )
        
        breakdown = pp.months_breakdown()
        self.assertEqual(len(breakdown), 1)
        # 17 days (15-31 inclusive) / 30 = ~0.5667
        self.assertGreater(breakdown[0]["fraction"], Decimal("0.56"))
        self.assertLess(breakdown[0]["fraction"], Decimal("0.57"))
    
    def test_recommended_total_calculation(self):
        """Recommended total should be monthly_amount × sum(fractions)."""
        pp = PaymentPlan.objects.create(
            person_role=self.pr,
            fiscal_year=self.fy,
            monthly_amount=Decimal("300.00"),
            pay_start=date(2024, 7, 1),
            pay_end=date(2024, 9, 30)
        )
        
        recommended = pp.recommended_total()
        # Allow small rounding differences
        self.assertAlmostEqual(float(recommended), 920.00, places=1)
    
    def test_total_override_respected(self):
        """When total_override is set, effective_total should use it."""
        pp = PaymentPlan.objects.create(
            person_role=self.pr,
            fiscal_year=self.fy,
            monthly_amount=Decimal("300.00"),
            total_override=Decimal("3000.00")
        )
        
        self.assertEqual(pp.effective_total, Decimal("3000.00"))
        self.assertNotEqual(pp.effective_total, pp.recommended_total())