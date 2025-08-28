from django.contrib import admin
from .models import Person

@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "email")
    search_fields = ("first_name", "last_name", "email")

# Register your models here.
