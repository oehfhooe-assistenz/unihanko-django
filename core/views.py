# core/views.py
from django.shortcuts import render
from django.contrib.flatpages.models import FlatPage
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.sites.shortcuts import get_current_site
from django.http import Http404, HttpResponse

def home(request):
    ctx = {
        "flat_about":   FlatPage.objects.filter(url="/pages/about/").first(),
        "flat_privacy": FlatPage.objects.filter(url="/pages/privacy/").first(),
        "flat_contact": FlatPage.objects.filter(url="/pages/contact/").first(),
    }
    return render(request, "core/home.html", ctx)

@staff_member_required
def admin_help_flatpage(request, app_label: str, model_name: str):
    """Return the model-specific help if present; otherwise fall back to /admin/help/."""
    site = get_current_site(request)

    wanted_url = f"/admin/help/{app_label}/{model_name}/"
    page = FlatPage.objects.filter(url=wanted_url, sites=site).first()

    # choose which template flavor to render
    template = "admin/help_fragment.html" if request.GET.get("fragment") == "1" else "admin/help_flatpage.html"

    if page:
        ctx = {"page": page, "app_label": app_label, "model_name": model_name, "fallback_from": None}
        return render(request, template, ctx)

    # Fallback to the general index
    index = FlatPage.objects.filter(url="/admin/help/", sites=site).first()
    if index:
        ctx = {"page": index, "app_label": app_label, "model_name": model_name, "fallback_from": wanted_url}
        return render(request, template, ctx)

    # Last-resort: a tiny inline message for the modal (don’t 404 the overlay)
    if request.GET.get("fragment") == "1":
        return HttpResponse("<div class='uh-help-body'>No help content yet.</div>")

    # For full-page requests, a real 404 is fine
    raise Http404(f"No help page at '{wanted_url}', and no index at '/admin/help/'.")