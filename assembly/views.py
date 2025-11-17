from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .models import Session, SessionItem, Vote, Mandate
from .forms import SessionItemProtocolForm


@staff_member_required
def protocol_editor(request, session_id=None):
    """📝 PROTOKOL-KUN Mk. 1"""
    session = None
    items = []
    annotations_by_item = {}
    is_locked = False
    
    if session_id:
        session = get_object_or_404(Session, pk=session_id)
        items = session.items.all().order_by('order')
        
        # Check if session is locked (submitted or approved)
        from hankosign.utils import state_snapshot
        st = state_snapshot(session)
        is_locked = st.get('submitted', False) or st.get('locked', False) or 'CHAIR' in st.get('approved', set())
        
        # Load annotations
        from django.contrib.contenttypes.models import ContentType
        try:
            from annotations.models import Annotation
            
            item_ct = ContentType.objects.get_for_model(SessionItem)
            item_ids = [item.pk for item in items]
            
            annotations_qs = Annotation.objects.filter(
                content_type=item_ct,
                object_id__in=item_ids
            ).select_related('created_by').order_by('-created_at')
            
            for annotation in annotations_qs:
                annotations_by_item.setdefault(annotation.object_id, []).append(annotation)
        except ImportError:
            pass
    
    context = {
        'session': session,
        'items': items,
        'annotations_by_item': annotations_by_item,
        'all_sessions': Session.objects.all().order_by('-session_date')[:20],
        'is_locked': is_locked,  # ← Add this
    }
    
    return render(request, 'assembly/protocol_editor.html', context)


@staff_member_required
@require_http_methods(["POST"])
@transaction.atomic
def protocol_save_item(request, session_id, item_id=None):
    """Save or create a session item via AJAX."""
    session = get_object_or_404(Session, pk=session_id)
    
    if item_id:
        item = get_object_or_404(SessionItem, pk=item_id, session=session)
    else:
        item = SessionItem(session=session)
    
    form = SessionItemProtocolForm(request.POST, instance=item)
    
    if form.is_valid():
        item = form.save(commit=False)
        
        if not item.order:
            max_order = SessionItem.objects.filter(session=session).count()
            item.order = max_order + 1
        
        item.save()
        
        # Handle named votes if voting_mode is NAMED
        if item.kind == SessionItem.Kind.RESOLUTION and item.voting_mode == SessionItem.VotingMode.NAMED:
            # Clear existing votes
            Vote.objects.filter(item=item).delete()
            
            # Create new votes from form data
            for key, value in request.POST.items():
                if key.startswith('vote_') and value:
                    mandate_id = key.replace('vote_', '')
                    try:
                        mandate = Mandate.objects.get(pk=mandate_id)
                        Vote.objects.create(
                            item=item,
                            mandate=mandate,
                            vote=value
                        )
                    except Mandate.DoesNotExist:
                        pass
        
        return JsonResponse({
            'success': True,
            'item_id': item.pk,
            'item_code': item.item_code,
            'message': str(_('Item saved successfully'))
        })
    else:
        return JsonResponse({
            'success': False,
            'errors': form.errors.as_json()
        }, status=400)


@staff_member_required
@require_http_methods(["POST"])
@transaction.atomic
def protocol_delete_item(request, session_id, item_id):
    """Delete a session item and auto-renumber."""
    from django.db.models import F
    
    session = get_object_or_404(Session, pk=session_id)
    item = get_object_or_404(SessionItem, pk=item_id, session=session)
    
    item_code = item.item_code
    deleted_order = item.order
    
    item.delete()
    
    # Auto-renumber
    SessionItem.objects.filter(
        session=session,
        order__gt=deleted_order
    ).update(order=F('order') - 1)
    
    return JsonResponse({
        'success': True,
        'message': str(_('Item {code} deleted').format(code=item_code))
    })


@staff_member_required
@require_http_methods(["POST"])
@transaction.atomic
def protocol_reorder_items(request, session_id):
    """Reorder session items."""
    session = get_object_or_404(Session, pk=session_id)
    
    import json
    item_ids = json.loads(request.body)
    
    for index, item_id in enumerate(item_ids, start=1):
        SessionItem.objects.filter(pk=item_id, session=session).update(order=index)
    
    return JsonResponse({
        'success': True,
        'message': str(_('Items reordered successfully'))
    })


@staff_member_required
@require_http_methods(["GET"])
def protocol_insert_at(request, session_id, insert_after_order):
    """Prepare to insert item after specific order position."""
    from django.db.models import F
    
    session = get_object_or_404(Session, pk=session_id)
    
    SessionItem.objects.filter(
        session=session,
        order__gt=insert_after_order
    ).update(order=F('order') + 1)
    
    new_order = insert_after_order + 1
    
    return JsonResponse({
        'success': True,
        'new_order': new_order,
        'message': str(_('Ready to insert item at position {order}').format(order=new_order))
    })


@staff_member_required
@require_http_methods(["GET"])
def protocol_get_item(request, session_id, item_id):
    """Get item data as JSON for editing."""
    session = get_object_or_404(Session, pk=session_id)
    item = get_object_or_404(SessionItem, pk=item_id, session=session)
    
    # Build item data
    item_data = {
        'id': item.pk,
        'kind': item.kind,
        'title': item.title,
        'order': item.order,
        'content': item.content or '',
        'subject': item.subject or '',
        'discussion': item.discussion or '',
        'outcome': item.outcome or '',
        'voting_mode': item.voting_mode,
        'votes_for': item.votes_for,
        'votes_against': item.votes_against,
        'votes_abstain': item.votes_abstain,
        'passed': item.passed,
        'elected_person_text_reference': item.elected_person_text_reference or '',
        'elected_role_text_reference': item.elected_role_text_reference or '',
        'notes': item.notes or '',
        'named_votes': {}
    }
    
    # Get named votes if applicable
    if item.voting_mode == SessionItem.VotingMode.NAMED:
        for vote in item.named_votes.all():
            item_data['named_votes'][vote.mandate_id] = vote.vote
    
    return JsonResponse({
        'success': True,
        'item': item_data
    })