import json
from pathlib import Path
from django.conf import settings
from django.http import HttpResponse, Http404

from reportbro import Report  # from reportbro-lib

def _load_template(name: str) -> dict:
    tpl_path = Path(settings.BASE_DIR) / "reports" / name
    if not tpl_path.exists():
        raise Http404(f"Report template not found: {tpl_path}")
    return json.loads(tpl_path.read_text(encoding="utf-8"))

def people_pdf_smoketest(request):
    import json, logging
    from django.http import HttpResponse
    from reportbro import Report
    definition = _load_template("people_hello.json")
    try:
        report = Report(definition, {})
        pdf_bytes = report.generate_pdf()
    except Exception as e:
        # show the real problem instead of a broken "PDF"
        logging.exception("ReportBro failed")
        return HttpResponse(f"ReportBro error:\n{e}", content_type="text/plain", status=500)

    # sanity: PDF files start with %PDF
    if not pdf_bytes.startswith(b"%PDF"):
        # something’s off (likely an HTML error page)
        head = pdf_bytes[:300]
        return HttpResponse(b"Not a PDF. First bytes:\n\n" + head, content_type="text/plain", status=500)

    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = 'inline; filename="people_smoketest.pdf"'
    return resp

