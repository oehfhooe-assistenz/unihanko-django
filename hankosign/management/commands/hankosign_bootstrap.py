from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType

from hankosign.models import Action


class Command(BaseCommand):
    help = "Create common HankoSign Actions."

    def handle(self, *args, **options):
        created = 0

        def ensure(verb, stage, model):
            nonlocal created
            ct = ContentType.objects.get_for_model(model)
            obj, made = Action.objects.get_or_create(
                verb=verb, stage=stage, scope=ct,
                defaults={"human_label": f"{verb}/{stage or '-'} for {ct.app_label}.{ct.model}"}
            )
            if made:
                created += 1

        # Import here to avoid circulars if apps load order differs
        from employees.models import TimeSheet, EmploymentDocument

        ensure("SUBMIT", "", TimeSheet)
        ensure("APPROVE", "WIREF", TimeSheet)
        ensure("APPROVE", "CHAIR", TimeSheet)

        ensure("SUBMIT", "", EmploymentDocument)
        ensure("APPROVE", "WIREF", EmploymentDocument)

        self.stdout.write(self.style.SUCCESS(f"Bootstrap complete. Created {created} actions."))
