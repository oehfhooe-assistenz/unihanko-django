# core/pdf.py (make a new module)
from django.http import HttpResponse
from django.template.loader import render_to_string
from weasyprint import HTML

def render_pdf_response(template, context, request, filename, download=False):
    html = render_to_string(template, context)
    pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
    resp = HttpResponse(pdf, content_type="application/pdf")
    disp = "attachment" if download else "inline"
    resp["Content-Disposition"] = f'{disp}; filename="{filename}"'
    return resp
