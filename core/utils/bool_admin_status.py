from django.utils.html import format_html

def boolean_status_span(value: bool, *, true_label: str, false_label: str,
                        true_code: str = "ok", false_code: str = "off"):
    """
    Return <span class="js-state" data-state="...">Label</span> for a boolean.
    The code is machine-readable; CSS/JS can decorate rows globally.
    """
    label = true_label if value else false_label
    code  = true_code if value else false_code
    return format_html('<span class="js-state" data-state="{}">{}</span>', code, label)

def row_state_attr_for_boolean(value: bool, *, true_code: str = "ok", false_code: str = "off"):
    # Whatever your global hook expects (data-state / data-row-state etc.)
    return {"data-state": (true_code if value else false_code)}
