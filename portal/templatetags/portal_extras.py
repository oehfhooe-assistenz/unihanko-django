# portal/templatetags/portal_extras.py
from django import template

register = template.Library()

@register.filter
def lookup(dictionary, key):
    """
    Template filter to get dictionary value by key.
    Usage: {{ dict|lookup:key }}
    
    This allows accessing dictionary values in Django templates,
    which is needed for accessing forms by plan ID in the payment list template.
    """
    if dictionary and hasattr(dictionary, 'get'):
        return dictionary.get(key)
    return None


@register.filter
def status_class(status):
    """
    Convert payment plan status to CSS class.
    Usage: {{ plan.status|status_class }}
    
    Converts status strings like 'DRAFT' to CSS classes like 'status-draft'
    """
    if status:
        return f"status-{status.lower()}"
    return "status-unknown"


@register.filter
def stage_class(stage):
    """
    Convert ECTS request stage to CSS class.
    Usage: {{ request.stage|stage_class }}
    """
    if stage:
        return f"stage-{stage.lower()}"
    return "stage-unknown"


@register.inclusion_tag('portal/includes/status_indicator.html')
def show_status_indicator(status, description=""):
    """
    Template tag to show a consistent status indicator.
    Usage: {% show_status_indicator plan.status "Payment plan status" %}
    """
    return {
        'status': status,
        'description': description,
        'css_class': status_class(status) if status else 'status-unknown'
    }


@register.filter
def mask_iban(iban, visible_chars=8):
    """
    Mask IBAN for privacy, showing only first and last few characters.
    Usage: {{ plan.iban|mask_iban:8 }}
    """
    if not iban:
        return ""
    
    if len(iban) <= visible_chars:
        return iban
    
    visible_start = visible_chars // 2
    visible_end = visible_chars - visible_start
    
    masked_length = len(iban) - visible_chars
    masked = "•" * masked_length
    
    return f"{iban[:visible_start]}{masked}{iban[-visible_end:]}" if visible_end > 0 else f"{iban[:visible_start]}{masked}"


@register.filter 
def currency_format(value):
    """
    Format currency values consistently.
    Usage: {{ plan.monthly_amount|currency_format }}
    """
    if value is None:
        return "€ 0.00"
    try:
        return f"€ {float(value):.2f}"
    except (ValueError, TypeError):
        return "€ 0.00"