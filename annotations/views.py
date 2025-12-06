# File: annotations/views.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.shortcuts import get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from .utils import HankoSignAction
from .models import Annotation


@staff_member_required
@require_http_methods(["POST"])
@transaction.atomic
def add_annotation(request):
    """
    AJAX endpoint to add an annotation to any object.
    
    POST params:
        - content_type_id: ID of the ContentType
        - object_id: ID of the specific object
        - text: Annotation text
        - annotation_type: Optional, defaults to USER
    
    Returns JSON:
        {
            "success": true,
            "annotation_id": 123,
            "message": "Annotation added"
        }
    """
    content_type_id = request.POST.get('content_type_id')
    object_id = request.POST.get('object_id')
    text = request.POST.get('text', '').strip()
    annotation_type = request.POST.get('annotation_type', Annotation.AnnotationType.USER)
    
    if not all([content_type_id, object_id, text]):
        return JsonResponse({
            'success': False,
            'message': str(_('Missing required fields'))
        }, status=400)
    
    try:
        content_type = get_object_or_404(ContentType, pk=content_type_id)
        
        annotation = Annotation.objects.create(
            content_type=content_type,
            object_id=object_id,
            annotation_type=annotation_type,
            text=text,
            created_by=request.user
        )
        
        return JsonResponse({
            'success': True,
            'annotation_id': annotation.pk,
            'message': str(_('Annotation added successfully'))
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


@staff_member_required
@require_http_methods(["POST"])
@transaction.atomic
def delete_annotation(request, annotation_id):
    """
    AJAX endpoint to delete an annotation.
    Only the creator or superuser can delete.
    """
    annotation = get_object_or_404(Annotation, pk=annotation_id)
    
    # Permission check: creator or superuser
    if annotation.created_by != request.user and not request.user.is_superuser:
        return JsonResponse({
            'success': False,
            'message': str(_('You do not have permission to delete this annotation'))
        }, status=403)
    
    annotation.delete()
    
    return JsonResponse({
        'success': True,
        'message': str(_('Annotation deleted'))
    })


def create_system_annotation(content_object, text_or_action, annotation_type=None, user=None):
    """
    Helper function to create system annotations programmatically.
    
    Supports two modes:
    1. **HankoSign action** (recommended for workflow events):
       Pass a HankoSignAction constant and user
       
    2. **Custom text** (for anything else):
       Pass a custom text string
    
    Args:
        content_object: Any Django model instance
        text_or_action: Either:
            - HankoSignAction constant (e.g., "LOCK", "SUBMIT")
            - Custom text string
        annotation_type: Optional Annotation.AnnotationType, defaults to SYSTEM
        user: Django User object (required for HankoSign actions, optional for custom)
    
    Returns:
        Created Annotation instance
    
    Examples:
        # Standard HankoSign workflow actions (bilingual)
        create_system_annotation(session, "SUBMIT", user=request.user)
        # → "[HS] Eingereicht durch / Submitted by Sven Varszegi"
        
        create_system_annotation(fiscal_year, "LOCK", user=request.user)
        # → "[HS] Gesperrt durch / Locked by Sven Varszegi"
        
        create_system_annotation(session, "APPROVE", user=request.user)
        # → "[HS] Genehmigt durch / Approved by Sven Varszegi"
        
        # Custom text (for non-workflow events)
        create_system_annotation(session, "Protocol finalized and sent to KoKo")
        # → "Protocol finalized and sent to KoKo"
        
        create_system_annotation(session, f"Edited by {user.get_full_name()}", user=user)
        # → "Edited by Sven Varszegi"
    """
    if annotation_type is None:
        annotation_type = Annotation.AnnotationType.SYSTEM
    
    # Try to interpret as HankoSign action first
    hs_text = HankoSignAction.get_text(text_or_action, user)
    if hs_text:
        # It's a recognized HankoSign action constant
        text = hs_text
    else:
        # It's custom text - use as-is
        text = text_or_action
    
    content_type = ContentType.objects.get_for_model(content_object)
    
    return Annotation.objects.create(
        content_type=content_type,
        object_id=content_object.pk,
        annotation_type=annotation_type,
        text=text,
        created_by=user if user else None
    )