# File: core/pdf.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from weasyprint import HTML
from urllib.parse import quote
from django.utils.http import http_date
import time

def render_pdf_response(template, context, request, filename, download=True, print_ref=None):
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
    # RFC 6266 / 5987: add filename* for UTF-8 and better browser support
    safe = filename.replace('"', '')  # keep it boring
    resp["Content-Disposition"] = (
        f'{disp}; filename="{safe}"; filename*=UTF-8\'\'{quote(safe)}'
    )
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Cache-Control"] = "private, max-age=10, must-revalidate"
    resp["Expires"] = http_date(time.time() + 180) 
    return resp
