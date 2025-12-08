# File: annotations/tests.py
# Version: 1.0.1
# Author: vas
# Modified: 2025-12-08

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.contrib.auth.models import Permission
from people.models import Person
from .models import Annotation
from .views import create_system_annotation
from .utils import HankoSignAction

User = get_user_model()


class AnnotationSecurityTestCase(TestCase):
    """
    Critical security tests for annotations module.
    Tests IDOR protection, permission checks, and authorization.
    """
    
    def setUp(self):
        """Set up test users and objects."""
        # Create test users
        self.superuser = User.objects.create_superuser(
            username='admin',
            email='admin@test.com',
            password='testpass123'
        )
        
        # Staff user with people permissions
        self.staff_with_perms = User.objects.create_user(
            username='staff_people',
            email='staff1@test.com',
            password='testpass123',
            is_staff=True
        )
        # Give change_person permission
        perm = Permission.objects.get(
            content_type__app_label='people',
            codename='change_person'
        )
        self.staff_with_perms.user_permissions.add(perm)
        
        # Staff user WITHOUT people permissions
        self.staff_no_perms = User.objects.create_user(
            username='staff_other',
            email='staff2@test.com',
            password='testpass123',
            is_staff=True
        )
        # Give some other permission but NOT people
        other_perm = Permission.objects.get(
            content_type__app_label='auth',
            codename='change_user'
        )
        self.staff_no_perms.user_permissions.add(other_perm)
        
        # Regular user (not staff)
        self.regular_user = User.objects.create_user(
            username='regular',
            email='regular@test.com',
            password='testpass123',
            is_staff=False
        )
        
        # Create test object (Person)
        self.test_person = Person.objects.create(
            first_name='Test',
            last_name='Person',
            email='test.person@test.com'
        )
        
        self.client = Client()
    
    def test_idor_protection_no_permission(self):
        """
        CRITICAL: User without permission cannot annotate objects.
        This is the main IDOR vulnerability test.
        """
        self.client.login(username='staff_other', password='testpass123')
        
        content_type = ContentType.objects.get_for_model(Person)
        
        response = self.client.post(reverse('annotations:add'), {
            'content_type_id': content_type.id,
            'object_id': self.test_person.id,
            'text': 'Attempting IDOR attack',
            'annotation_type': 'USER'
        })
        
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['success'])
        
        # Verify annotation was NOT created
        annotation_count = Annotation.objects.filter(
            content_type=content_type,
            object_id=self.test_person.id
        ).count()
        self.assertEqual(annotation_count, 0)
    
    def test_annotation_allowed_with_permission(self):
        """User WITH correct permission can annotate objects."""
        self.client.login(username='staff_people', password='testpass123')
        
        content_type = ContentType.objects.get_for_model(Person)
        
        response = self.client.post(reverse('annotations:add'), {
            'content_type_id': content_type.id,
            'object_id': self.test_person.id,
            'text': 'Valid annotation',
            'annotation_type': 'USER'
        })
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        
        # Verify annotation was created
        annotation = Annotation.objects.get(
            content_type=content_type,
            object_id=self.test_person.id
        )
        self.assertEqual(annotation.text, 'Valid annotation')
        self.assertEqual(annotation.created_by, self.staff_with_perms)
    
    def test_superuser_can_annotate_anything(self):
        """Superuser can annotate any object."""
        self.client.login(username='admin', password='testpass123')
        
        content_type = ContentType.objects.get_for_model(Person)
        
        response = self.client.post(reverse('annotations:add'), {
            'content_type_id': content_type.id,
            'object_id': self.test_person.id,
            'text': 'Superuser annotation',
            'annotation_type': 'USER'
        })
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
    
    def test_non_staff_blocked(self):
        """Non-staff users cannot use annotation endpoints."""
        self.client.login(username='regular', password='testpass123')
        
        content_type = ContentType.objects.get_for_model(Person)
        
        response = self.client.post(reverse('annotations:add'), {
            'content_type_id': content_type.id,
            'object_id': self.test_person.id,
            'text': 'Should be blocked',
            'annotation_type': 'USER'
        })
        
        # @staff_member_required redirects to login
        self.assertEqual(response.status_code, 302)
    
    def test_invalid_object_id(self):
        """Request with non-existent object ID fails."""
        self.client.login(username='staff_people', password='testpass123')
        
        content_type = ContentType.objects.get_for_model(Person)
        
        response = self.client.post(reverse('annotations:add'), {
            'content_type_id': content_type.id,
            'object_id': 99999,  # Doesn't exist
            'text': 'Test',
            'annotation_type': 'USER'
        })
        
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()['success'])
    
    def test_system_type_restricted_to_superuser(self):
        """
        CRITICAL: Non-superusers cannot create SYSTEM annotations.
        Should be downgraded to USER type.
        """
        self.client.login(username='staff_people', password='testpass123')
        
        content_type = ContentType.objects.get_for_model(Person)
        
        response = self.client.post(reverse('annotations:add'), {
            'content_type_id': content_type.id,
            'object_id': self.test_person.id,
            'text': 'Attempting SYSTEM type',
            'annotation_type': 'SYSTEM'  # Should be downgraded
        })
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        
        # Verify it was downgraded to USER
        annotation = Annotation.objects.get(
            content_type=content_type,
            object_id=self.test_person.id
        )
        self.assertEqual(annotation.annotation_type, Annotation.AnnotationType.USER)
    
    def test_superuser_can_create_system_annotations(self):
        """Superuser CAN create SYSTEM annotations."""
        self.client.login(username='admin', password='testpass123')
        
        content_type = ContentType.objects.get_for_model(Person)
        
        response = self.client.post(reverse('annotations:add'), {
            'content_type_id': content_type.id,
            'object_id': self.test_person.id,
            'text': 'System annotation',
            'annotation_type': 'SYSTEM'
        })
        
        self.assertEqual(response.status_code, 200)
        
        annotation = Annotation.objects.get(
            content_type=content_type,
            object_id=self.test_person.id
        )
        self.assertEqual(annotation.annotation_type, Annotation.AnnotationType.SYSTEM)
    
    def test_invalid_annotation_type(self):
        """Invalid annotation type defaults to USER."""
        self.client.login(username='staff_people', password='testpass123')
        
        content_type = ContentType.objects.get_for_model(Person)
        
        response = self.client.post(reverse('annotations:add'), {
            'content_type_id': content_type.id,
            'object_id': self.test_person.id,
            'text': 'Test',
            'annotation_type': 'INVALID_TYPE'
        })
        
        self.assertEqual(response.status_code, 200)
        
        annotation = Annotation.objects.get(
            content_type=content_type,
            object_id=self.test_person.id
        )
        self.assertEqual(annotation.annotation_type, Annotation.AnnotationType.USER)
    
    def test_missing_required_fields(self):
        """Request with missing fields fails validation."""
        self.client.login(username='staff_people', password='testpass123')
        
        # Missing text
        response = self.client.post(reverse('annotations:add'), {
            'content_type_id': 1,
            'object_id': 1,
        })
        
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])


class AnnotationDeleteTestCase(TestCase):
    """Tests for annotation deletion authorization."""
    
    def setUp(self):
        """Set up test users and annotations."""
        self.user1 = User.objects.create_user(
            username='user1',
            password='testpass123',
            is_staff=True
        )
        self.user2 = User.objects.create_user(
            username='user2',
            password='testpass123',
            is_staff=True
        )
        self.superuser = User.objects.create_superuser(
            username='admin',
            password='testpass123'
        )
        
        self.test_person = Person.objects.create(
            first_name='Test',
            last_name='Person',
            email='test@test.com'
        )
        
        content_type = ContentType.objects.get_for_model(Person)
        
        # Create annotation by user1
        self.annotation = Annotation.objects.create(
            content_type=content_type,
            object_id=self.test_person.id,
            annotation_type=Annotation.AnnotationType.USER,
            text='Test annotation',
            created_by=self.user1
        )
        
        self.client = Client()
    
    def test_creator_can_delete_own_annotation(self):
        """Annotation creator can delete their own annotation."""
        self.client.login(username='user1', password='testpass123')
        
        response = self.client.post(
            reverse('annotations:delete', args=[self.annotation.id])
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        
        # Verify deleted
        self.assertFalse(Annotation.objects.filter(id=self.annotation.id).exists())
    
    def test_non_creator_cannot_delete(self):
        """Non-creator cannot delete someone else's annotation."""
        self.client.login(username='user2', password='testpass123')
        
        response = self.client.post(
            reverse('annotations:delete', args=[self.annotation.id])
        )
        
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['success'])
        
        # Verify NOT deleted
        self.assertTrue(Annotation.objects.filter(id=self.annotation.id).exists())
    
    def test_superuser_can_delete_any_annotation(self):
        """Superuser can delete any annotation."""
        self.client.login(username='admin', password='testpass123')
        
        response = self.client.post(
            reverse('annotations:delete', args=[self.annotation.id])
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        
        # Verify deleted
        self.assertFalse(Annotation.objects.filter(id=self.annotation.id).exists())


class SystemAnnotationHelperTestCase(TestCase):
    """Tests for create_system_annotation helper function."""
    
    def setUp(self):
        """Set up test objects."""
        self.user = User.objects.create_user(
            username='testuser',
            first_name='Test',
            last_name='User'
        )
        
        self.test_person = Person.objects.create(
            first_name='Test',
            last_name='Person',
            email='test@test.com'
        )
    
    def test_hankosign_action_with_user(self):
        """HankoSign action creates bilingual annotation."""
        annotation = create_system_annotation(
            self.test_person,
            HankoSignAction.LOCK,
            user=self.user
        )
        
        self.assertEqual(annotation.annotation_type, Annotation.AnnotationType.SYSTEM)
        self.assertIn('[HS]', annotation.text)
        self.assertIn('Gesperrt durch', annotation.text)
        self.assertIn('Locked by', annotation.text)
        self.assertIn('Test User', annotation.text)
        self.assertEqual(annotation.created_by, self.user)
    
    def test_custom_text_annotation(self):
        """Custom text creates annotation as-is."""
        custom_text = "Protocol finalized and sent to KoKo"
        
        annotation = create_system_annotation(
            self.test_person,
            custom_text,
            user=self.user
        )
        
        self.assertEqual(annotation.text, custom_text)
        self.assertEqual(annotation.annotation_type, Annotation.AnnotationType.SYSTEM)
        self.assertEqual(annotation.created_by, self.user)
    
    def test_system_annotation_without_user(self):
        """System annotation can be created without user."""
        annotation = create_system_annotation(
            self.test_person,
            "Automated system event"
        )
        
        self.assertEqual(annotation.text, "Automated system event")
        self.assertIsNone(annotation.created_by)
    
    def test_custom_annotation_type(self):
        """Can specify custom annotation type."""
        annotation = create_system_annotation(
            self.test_person,
            "Important correction",
            annotation_type=Annotation.AnnotationType.CORRECTION,
            user=self.user
        )
        
        self.assertEqual(annotation.annotation_type, Annotation.AnnotationType.CORRECTION)
    
    def test_all_hankosign_actions(self):
        """All HankoSign action types work correctly."""
        actions = [
            HankoSignAction.LOCK,
            HankoSignAction.UNLOCK,
            HankoSignAction.APPROVE,
            HankoSignAction.REJECT,
            HankoSignAction.VERIFY,
            HankoSignAction.RELEASE,
            HankoSignAction.SUBMIT,
            HankoSignAction.WITHDRAW,
        ]
        
        for action in actions:
            annotation = create_system_annotation(
                self.test_person,
                action,
                user=self.user
            )
            
            self.assertIn('[HS]', annotation.text)
            self.assertIn('Test User', annotation.text)


class AnnotationModelTestCase(TestCase):
    """Tests for Annotation model."""
    
    def setUp(self):
        """Set up test objects."""
        self.user = User.objects.create_user(username='testuser')
        self.test_person = Person.objects.create(
            first_name='Test',
            last_name='Person',
            email='test@test.com'
        )
    
    def test_annotation_str(self):
        """Annotation __str__ includes type, creator, and date."""
        content_type = ContentType.objects.get_for_model(Person)
        
        annotation = Annotation.objects.create(
            content_type=content_type,
            object_id=self.test_person.id,
            annotation_type=Annotation.AnnotationType.USER,
            text='Test',
            created_by=self.user
        )
        
        str_repr = str(annotation)
        self.assertIn('User Comment', str_repr)
        self.assertIn('testuser', str_repr)
    
    def test_system_annotation_str(self):
        """System annotation shows SYSTEM instead of user."""
        content_type = ContentType.objects.get_for_model(Person)
        
        annotation = Annotation.objects.create(
            content_type=content_type,
            object_id=self.test_person.id,
            annotation_type=Annotation.AnnotationType.SYSTEM,
            text='System event',
            created_by=None
        )
        
        str_repr = str(annotation)
        self.assertIn('SYSTEM', str_repr)
    
    def test_is_system_property(self):
        """is_system property correctly identifies system annotations."""
        content_type = ContentType.objects.get_for_model(Person)
        
        user_annotation = Annotation.objects.create(
            content_type=content_type,
            object_id=self.test_person.id,
            annotation_type=Annotation.AnnotationType.USER,
            text='User comment',
            created_by=self.user
        )
        
        system_annotation = Annotation.objects.create(
            content_type=content_type,
            object_id=self.test_person.id,
            annotation_type=Annotation.AnnotationType.SYSTEM,
            text='System event'
        )
        
        self.assertFalse(user_annotation.is_system)
        self.assertTrue(system_annotation.is_system)