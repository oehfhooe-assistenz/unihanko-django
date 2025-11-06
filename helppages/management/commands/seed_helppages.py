from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from helppages.models import HelpPage

class Command(BaseCommand):
    help = 'Create placeholder HelpPage entries for all ContentTypes'
    
    def handle(self, *args, **options):
        created = 0
        existed = 0
        
        for ct in ContentType.objects.all():
            obj, was_created = HelpPage.objects.get_or_create(
                content_type=ct,
                defaults={
                    'title_de': f"Hilfe: {ct.model_class()._meta.verbose_name_plural if ct.model_class() else ct.model}",
                    'title_en': f"Help: {ct.model_class()._meta.verbose_name_plural if ct.model_class() else ct.model}",
                    'content_de': '-',
                    'content_en': '-',
                    'legend_de': '',
                    'legend_en': '',
                    'is_active': False,
                }
            )
            
            if was_created:
                created += 1
                self.stdout.write(f"  ✓ Created: {ct.app_label}.{ct.model}")
            else:
                existed += 1
        
        self.stdout.write(self.style.SUCCESS(
            f"\n✓ Done! Created {created} new help pages. {existed} already existed."
        ))