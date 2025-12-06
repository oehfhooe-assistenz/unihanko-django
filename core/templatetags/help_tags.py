# File: core/templatetags/help_tags.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django import template
from django.utils.safestring import mark_safe
from django.contrib.contenttypes.models import ContentType
from helppages.models import HelpPage
import markdown

register = template.Library()

@register.simple_tag(takes_context=True)
def render_admin_help(context):
    """Render help accordion + legend for current admin page."""
    request = context.get('request')
    if not request:
        return ''
    
    # Extract app_label and model_name
    path_parts = request.path.strip('/').split('/')
    if len(path_parts) < 3 or path_parts[0] != 'admin':
        return ''
    
    app_label = path_parts[1]
    model_name = path_parts[2]
    
    # Get ContentType
    try:
        ct = ContentType.objects.get(app_label=app_label, model=model_name)
    except ContentType.DoesNotExist:
        return ''
    
    # Get HelpPage
    try:
        help_page = HelpPage.objects.get(content_type=ct, is_active=True)
    except HelpPage.DoesNotExist:
        return ''
    
    # Get language-specific content
    title = help_page.get_title()
    legend_text = help_page.get_legend()
    content_text = help_page.get_content()
    
    # Render markdown to HTML
    md = markdown.Markdown(extensions=[
        'markdown.extensions.extra',
        'markdown.extensions.nl2br',
        'markdown.extensions.sane_lists',
    ])
    
    legend_html = md.convert(legend_text) if legend_text else ''
    md.reset()  # Reset for second conversion
    content_html = md.convert(content_text) if content_text else ''
    
    from django.template.loader import render_to_string
    return mark_safe(render_to_string(
        "helppages/help_widget.html",
        {
            'help': help_page,
            'title': title,  # Language-aware title
            'legend_html': legend_html,
            'content_html': content_html,
        }
    ))