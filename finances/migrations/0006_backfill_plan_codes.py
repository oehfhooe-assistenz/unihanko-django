from django.db import migrations, transaction
import re

def backfill_codes(apps, schema_editor):
    PaymentPlan = apps.get_model("finances", "PaymentPlan")
    FiscalYear = apps.get_model("finances", "FiscalYear")

    def next_code(prefix, existing_codes):
        max_num = 0
        for c in existing_codes:
            m = re.match(rf"^{re.escape(prefix)}(\d+)$", c or "")
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"{prefix}{max_num + 1:05d}"

    # Process per FY so sequences are compact/readable
    fy_ids = (
        PaymentPlan.objects.exclude(fiscal_year_id=None)
        .values_list("fiscal_year_id", flat=True).distinct()
    )

    for fy_id in fy_ids:
        with transaction.atomic():
            fy = FiscalYear.objects.select_for_update().get(pk=fy_id)
            prefix = f"{fy.code}-"

            # existing plan codes for this FY (so we don't collide)
            existing = list(
                PaymentPlan.objects.filter(
                    fiscal_year_id=fy_id, plan_code__startswith=prefix
                ).values_list("plan_code", flat=True)
            )

            # oldest first = smaller numbers for earlier plans
            qs = PaymentPlan.objects.filter(
                fiscal_year_id=fy_id, plan_code__isnull=True
            ).order_by("created_at", "id")

            for pp in qs:
                code = next_code(prefix, existing)
                pp.plan_code = code
                pp.save(update_fields=["plan_code"])
                existing.append(code)

class Migration(migrations.Migration):

    dependencies = [
        ("finances", "0005_add_plan_code_field"),  # <-- set to the exact filename of your first migration
    ]

    operations = [
        migrations.RunPython(backfill_codes, migrations.RunPython.noop),
    ]
