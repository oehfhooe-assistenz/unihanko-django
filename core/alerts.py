# core/alerts.py
from datetime import timedelta
from django.utils import timezone
from django.urls import reverse

def build_alerts(user):
    alerts = []
    today = timezone.localdate()
    soon14 = today + timedelta(days=14)
    soon45 = today + timedelta(days=45)

    # PersonRole starts in ≤14d
    if user.has_perm("people.view_personrole"):
        from people.models import PersonRole
        qs = PersonRole.objects.filter(start_date__gte=today, start_date__lte=soon14)
        if qs.exists():
            url = (
                reverse("admin:people_personrole_changelist")
                + f"?start_date__gte={today}&start_date__lte={soon14}"
            )
            alerts.append({
                "text": f"{qs.count()} Start(s) in den nächsten 14 Tagen",
                "url": url,
                "level": "info",
            })

        # PersonRole ends in ≤14d
        qe = PersonRole.objects.filter(end_date__gte=today, end_date__lte=soon14)
        if qe.exists():
            url = (
                reverse("admin:people_personrole_changelist")
                + f"?end_date__gte={today}&end_date__lte={soon14}"
            )
            alerts.append({
                "text": f"{qe.count()} Ende(n) in den nächsten 14 Tagen",
                "url": url,
                "level": "warning",
            })

    # FiscalYear end in ≤45d
    if user.has_perm("finances.view_fiscalyear"):
        from finances.models import FiscalYear
        fy = FiscalYear.objects.filter(end__gte=today, end__lte=soon45)
        if fy.exists():
            url = (
                reverse("admin:finances_fiscalyear_changelist")
                + f"?end__gte={today}&end__lte={soon45}"
            )
            alerts.append({
                "text": f"{fy.count()} Wirtschaftsjahr(e) enden in ≤45 Tagen",
                "url": url,
                "level": "warning",
            })

    return alerts
