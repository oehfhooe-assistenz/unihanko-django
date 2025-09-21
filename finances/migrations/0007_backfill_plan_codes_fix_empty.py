from django.db import migrations, transaction
from django.db.models import Q
import re

def backfill_codes_fix(apps, schema_editor):
    PaymentPlan = apps.get_model("finances", "PaymentPlan")
    FiscalYear = apps.get_model("finances", "FiscalYear")

    def next_code(prefix, existing_codes):
        max_num = 0
        for c in existing_codes:
            m = re.match(rf"^{re.escape(prefix)}(\d+)$", c or "")
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"{prefix}{max_num + 1:05d}"

    # Work per FY so sequences are compact and deterministic
    fy_ids = (
        PaymentPlan.objects
        .filter(Q(plan_code__isnull=True) | Q(plan_code=""))
        .exclude(fiscal_year_id=None)
        .values_list("fiscal_year_id", flat=True).distinct()
    )

    for fy_id in fy_ids:
        with transaction.atomic():
            fy = FiscalYear.objects.select_for_update().get(pk=fy_id)
            prefix = f"{fy.code}-"

            # existing codes for this FY (avoid collisions)
            existing = list(
                PaymentPlan.objects
                .filter(fiscal_year_id=fy_id, plan_code__startswith=prefix)
                .values_list("plan_code", flat=True)
            )

            # oldest first → earlier plans get smaller numbers
            qs = (
                PaymentPlan.objects
                .filter(fiscal_year_id=fy_id)
                .filter(Q(plan_code__isnull=True) | Q(plan_code=""))
                .order_by("created_at", "id")
            )

            for pp in qs:
                code = next_code(prefix, existing)
                pp.plan_code = code
                pp.save(update_fields=["plan_code"])
                existing.append(code)

class Migration(migrations.Migration):

    dependencies = [
        ("finances", "0006_backfill_plan_codes"),
    ]

    operations = [
        migrations.RunPython(backfill_codes_fix, migrations.RunPython.noop),
    ]
