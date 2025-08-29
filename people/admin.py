from core.pdf import render_pdf_response
from django_object_actions import DjangoObjectActions
from django.contrib import admin
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from simple_history.admin import SimpleHistoryAdmin
from .models import Person

class PersonResource(resources.ModelResource):
    class Meta:
        model = Person
        fields = ("id", "last_name", "first_name", "email")  # order & selection
        export_order = ("id", "last_name", "first_name", "email")

@admin.register(Person)
class PersonAdmin(DjangoObjectActions, ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [PersonResource]
    list_display = ("last_name", "first_name", "email")
    search_fields = ("first_name", "last_name", "email")

    change_actions = ("print_pdf",)

    def print_pdf(self, request, obj):
        return render_pdf_response("people/person_pdf.html", {"p": obj}, request, f"person_{obj.id}.pdf")
    print_pdf.label = "Print PDF"
    print_pdf.short_description = "Generate a PDF for this person"
    print_pdf.attrs = {"class": "btn btn-block btn-outline-secondary btn-sm"}

    @admin.action(description="Export selected to PDF")
    def export_selected_pdf(self, request, queryset):
        rows = queryset.order_by("last_name", "first_name")
        return render_pdf_response("people/people_list_pdf.html", {"rows": rows}, request, "people_selected.pdf")

    actions = ["export_selected_pdf"]

# Register your models here.
