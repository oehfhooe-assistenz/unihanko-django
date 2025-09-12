# core/pdf.py
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from weasyprint import HTML

def render_pdf_response(template, context, request, filename, download=False, print_ref=None):
    # enrich context (available in base.html)
    ctx = {
        **(context or {}),
        "request": request,                 # lets templates read {{ request.user.email }}
        "now": timezone.localtime(),        # {{ now|date:"Y-m-d H:i" }}
        "print_ref": print_ref,             # optional extra line in the hero header
    }

    html = render_to_string(template, ctx, request=request)
    pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()

    resp = HttpResponse(pdf, content_type="application/pdf")
    disp = "attachment" if download else "inline"
    resp["Content-Disposition"] = f'{disp}; filename="{filename}"'
    return resp
