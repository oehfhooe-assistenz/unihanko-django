# core/views.py
from django.shortcuts import render
from django.contrib.flatpages.models import FlatPage
from django.contrib.admin.views.decorators import staff_member_required
from django.utils import timezone

def home(request):
    ctx = {
        "flat_about":   FlatPage.objects.filter(url="/pages/about/").first(),
        "flat_privacy": FlatPage.objects.filter(url="/pages/privacy/").first(),
        "flat_contact": FlatPage.objects.filter(url="/pages/contact/").first(),
    }
    return render(request, "core/home.html", ctx)

# core/views.py
from datetime import timedelta

from django.contrib.admin.models import LogEntry, ADDITION, CHANGE, DELETION
from django.contrib.admin.sites import site
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

@staff_member_required
def admin_cockpit(request):
    """
    Admin landing cockpit:
    - KPIs: dict with keys people / assignments / fiscal_years (None when no perm)
    - Alerts: list of {when, title, url, level?}
    - Recent: last 10 LogEntry rows for this user
    """
    # --- KPIs (permission-aware; provide keys even if None) ---
    kpis = {"people": None, "assignments": None, "fiscal_years": None}
    if request.user.has_perm("people.view_person"):
        from people.models import Person, PersonRole
        kpis["people"] = Person.objects.count()
        # Only show assignments if the user may view them
        if request.user.has_perm("people.view_personrole"):
            kpis["assignments"] = PersonRole.objects.count()
    if request.user.has_perm("finances.view_fiscalyear"):
        from finances.models import FiscalYear
        kpis["fiscal_years"] = FiscalYear.objects.count()

    # --- Alerts (Timeline) ---
    alerts = []
    today = timezone.localdate()

    if request.user.has_perm("people.view_personrole"):
        soon = today + timedelta(days=14)
        base_pr = reverse("admin:people_personrole_changelist")
        alerts += [
            {
                "when": today,
                "title": _("Upcoming starts (≤14 days)"),
                "url": f"{base_pr}?start_date__gte={today}&start_date__lte={soon}",
            },
            {
                "when": today,
                "title": _("Upcoming ends (≤14 days)"),
                "url": f"{base_pr}?end_date__gte={today}&end_date__lte={soon}",
            },
        ]

    if request.user.has_perm("finances.view_fiscalyear"):
        from finances.models import FiscalYear
        fy = FiscalYear.objects.filter(is_active=True).first()
        if fy and fy.end and fy.end <= today + timedelta(days=45):
            alerts.append({
                "when": fy.end,
                "title": _("Active fiscal year ends soon: %(code)s") % {"code": fy.display_code()},
                "url": reverse("admin:finances_fiscalyear_change", args=[fy.pk]),
            })

    # --- Recent actions (manual; no template tag) ---
    logs = (
        LogEntry.objects.filter(user=request.user)
        .select_related("content_type")
        .order_by("-action_time")[:10]
    )
    recent = []
    for e in logs:
        if e.action_flag == ADDITION:
            label = _("Added")
        elif e.action_flag == CHANGE:
            label = _("Changed")
        elif e.action_flag == DELETION:
            label = _("Deleted")
        else:
            label = _("Action")

        url = None
        if e.content_type_id and e.object_id and e.action_flag != DELETION:
            url = f"/admin/{e.content_type.app_label}/{e.content_type.model}/{e.object_id}/change/"

        recent.append({
            "time": e.action_time,
            "label": label,
            "object": e.object_repr,
            "url": url,
        })

    ctx = {
        "page_title": _("Cockpit"),
        "kpis": kpis,
        "alerts": alerts,
        "recent": recent,
        "now": timezone.now(),
    }
    ctx.update(site.each_context(request))  # keep Jazzmin sidebar/menu
    return render(request, "admin/cockpit.html", ctx)
