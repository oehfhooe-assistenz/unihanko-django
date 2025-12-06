# File: annotations/templatetags/annotation_tags.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django import template
from django.contrib.contenttypes.models import ContentType
from annotations.models import Annotation

register = template.Library()


@register.simple_tag
def get_annotations_for(obj, annotation_type=None):
    """
    Get all annotations for a given object.
    
    Usage in template:
        {% load annotation_tags %}
        {% get_annotations_for session_item as annotations %}
        {% for annotation in annotations %}
            {{ annotation.text }}
        {% endfor %}
    
    Or with type filter:
        {% get_annotations_for session_item "USER" as annotations %}
    """
    content_type = ContentType.objects.get_for_model(obj)
    annotations = Annotation.objects.filter(
        content_type=content_type,
        object_id=obj.pk
    ).select_related('created_by')
    
    if annotation_type:
        annotations = annotations.filter(annotation_type=annotation_type)
    
    return annotations


@register.simple_tag
def get_content_type_id(obj):
    """
    Get ContentType ID for an object (useful for AJAX calls).
    
    Usage:
        {% get_content_type_id session_item as ct_id %}
        <input type="hidden" name="content_type_id" value="{{ ct_id }}">
    """
    content_type = ContentType.objects.get_for_model(obj)
    return content_type.pk


@register.filter
def annotation_count(obj):
    """
    Count annotations for an object.
    
    Usage:
        {{ session_item|annotation_count }}
    """
    content_type = ContentType.objects.get_for_model(obj)
    return Annotation.objects.filter(
        content_type=content_type,
        object_id=obj.pk
    ).count()