# File: core/admin.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.contrib import admin
from django.contrib.flatpages.admin import FlatPageAdmin
from django.contrib.flatpages.models import FlatPage
from markdownx.widgets import AdminMarkdownxWidget
from django import forms


class FlatPageForm(forms.ModelForm):
    """Custom form to use MarkdownX for content field"""
    content = forms.CharField(widget=AdminMarkdownxWidget)
    
    class Meta:
        model = FlatPage
        fields = '__all__'


class CustomFlatPageAdmin(FlatPageAdmin):
    """FlatPage admin with MarkdownX editor"""
    form = FlatPageForm


# Unregister the default and register custom
admin.site.unregister(FlatPage)
admin.site.register(FlatPage, CustomFlatPageAdmin)

