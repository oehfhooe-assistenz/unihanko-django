# people/migrations/0008_add_start_end_reason_and_copy.py
from django.db import migrations, models
import django.db.models.deletion

def forwards_copy_reason(apps, schema_editor):
    PR = apps.get_model("people", "PersonRole")
    # Copy old 'reason' into either start_reason or end_reason
    # Rule: end_date is NULL => start_reason, else => end_reason
    for pr in PR.objects.all().only("id", "end_date", "reason_id"):
        if not pr.reason_id:
            continue
        if pr.end_date is None:
            PR.objects.filter(pk=pr.pk).update(start_reason_id=pr.reason_id)
        else:
            PR.objects.filter(pk=pr.pk).update(end_reason_id=pr.reason_id)

def backwards_copy_reason(apps, schema_editor):
    PR = apps.get_model("people", "PersonRole")
    # If rolling back: prefer end_reason if present, else start_reason
    for pr in PR.objects.all().only("id", "start_reason_id", "end_reason_id"):
        old = pr.end_reason_id or pr.start_reason_id
        if old:
            PR.objects.filter(pk=pr.pk).update(reason_id=old)

class Migration(migrations.Migration):

    dependencies = [
        ("people", "0007_alter_historicalperson_uuid_alter_person_uuid"),
    ]

    operations = [
        # New fields on live table
        migrations.AddField(
            model_name="personrole",
            name="start_reason",
            field=models.ForeignKey(
                to="people.roletransitionreason",
                on_delete=django.db.models.deletion.SET_NULL,
                null=True, blank=True,
                related_name="assignments_started",
                verbose_name="Start reason",
                help_text="Why this assignment started (e.g. Eintritt).",
            ),
        ),
        migrations.AddField(
            model_name="personrole",
            name="end_reason",
            field=models.ForeignKey(
                to="people.roletransitionreason",
                on_delete=django.db.models.deletion.SET_NULL,
                null=True, blank=True,
                related_name="assignments_ended",
                verbose_name="End reason",
                help_text="Why this assignment ended (e.g. Austritt). Required when an end date is set.",
            ),
        ),

        # Same fields on history table for simple_history
        migrations.AddField(
            model_name="historicalpersonrole",
            name="start_reason",
            field=models.ForeignKey(
                to="people.roletransitionreason",
                on_delete=django.db.models.deletion.DO_NOTHING,
                db_constraint=False,
                null=True, blank=True,
                related_name="+",
                verbose_name="Start reason",
                help_text="Why this assignment started (e.g. Eintritt).",
            ),
        ),
        migrations.AddField(
            model_name="historicalpersonrole",
            name="end_reason",
            field=models.ForeignKey(
                to="people.roletransitionreason",
                on_delete=django.db.models.deletion.DO_NOTHING,
                db_constraint=False,
                null=True, blank=True,
                related_name="+",
                verbose_name="End reason",
                help_text="Why this assignment ended (e.g. Austritt). Required when an end date is set.",
            ),
        ),

        # Copy data from old 'reason'
        migrations.RunPython(forwards_copy_reason, backwards_copy_reason),
        # NOTE: We DO NOT remove 'reason' here, and we DO NOT add constraints yet.
    ]
