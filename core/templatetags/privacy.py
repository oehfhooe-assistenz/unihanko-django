# File: core/templatetags/privacy.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django import template
from core.utils.privacy import mask_iban as _mask_iban

register = template.Library()

@register.filter(name="mask_iban")
def mask_iban_filter(value, args="6,4"):
    """
    Usage: {{ pp.iban|mask_iban }} or {{ pp.iban|mask_iban:"8,4" }}
    """
    try:
        head, tail = (int(x) for x in (args.split(",") + ["6", "4"])[:2])
    except Exception:
        head, tail = 6, 4
    return _mask_iban(value, head=head, tail=tail)
