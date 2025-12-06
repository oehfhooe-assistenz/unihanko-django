# File: annotations/admin.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.contrib import admin
#from django.contrib.contenttypes.admin import GenericStackedInline
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from core.admin_mixins import with_help_widget
from .models import Annotation
from core.admin_mixins import log_deletions
from django_admin_inline_paginator_plus.admin import GenericTabularInlinePaginated

class AnnotationInline(GenericTabularInlinePaginated):
    """
    Generic inline for annotations that works with ANY model.
    Add this to ANY model admin to enable annotations:
    
    Example:
        from annotations.admin import AnnotationInline
        
        @admin.register(YourModel)
        class YourModelAdmin(admin.ModelAdmin):
            inlines = [AnnotationInline]
    
    """
    model = Annotation
    ct_field = "content_type"
    ct_fk_field = "object_id"
    extra = 1
    per_page = 3
    pagination_key = "annotations-x"
    fields = ('annotation_type', 'text', 'created_by_display', 'created_at_display')
    readonly_fields = ('created_by_display', 'created_at_display')
    
    # Custom CSS for compact display
    class Media:
        css = {
            'all': ('annotations/admin_inline.css',)
        }
    
    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        
        # Store original form class
        OriginalForm = formset.form
        
        # Store request in closure for access in form __init__
        request_user = request.user
        
        # Create wrapper that makes saved annotations readonly
        class ConditionalReadonlyForm(OriginalForm):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)

                if 'text' in self.fields:
                    from django import forms
                    self.fields['text'].widget = forms.Textarea(attrs={
                        'rows': 3,
                        'style': 'resize: none; width: 100%;'
                    })
                
                # Hide SYSTEM type from non-superusers
                if 'annotation_type' in self.fields and not request_user.is_superuser:
                    # Filter out SYSTEM from choices
                    choices = [
                        (value, label) 
                        for value, label in self.fields['annotation_type'].choices 
                        if value != 'SYSTEM'
                    ]
                    self.fields['annotation_type'].choices = choices

                # If this annotation is already saved, make it readonly
                if self.instance and self.instance.pk:
                    if 'annotation_type' in self.fields:
                        display_value = self.instance.get_annotation_type_display()
                        self.fields['annotation_type'].prepare_value = lambda value: display_value
                        self.fields['annotation_type'].widget = forms.TextInput(attrs={
                            'readonly': 'readonly',
                            'style': 'background: transparent !important; border: none !important; cursor: default;'
                        })
                        self.fields['annotation_type'].disabled = True
                        self.fields['annotation_type'].required = False

                    if 'text' in self.fields:
                        self.fields['text'].disabled = True
                        self.fields['text'].required = False
                        self.fields['text'].widget = forms.Textarea(attrs={
                            'rows': 5,
                            'style': 'background: transparent !important; border: none !important; resize: none; width: 100%; cursor: default;'
                    })
                
            def save(self, commit=True):
                """Ensure created_by is set before saving"""
                instance = super().save(commit=False)
                
                # Set created_by if this is a new annotation
                if not instance.pk and not instance.created_by:
                    instance.created_by = request_user
                
                if commit:
                    instance.save()
                
                return instance
        
        formset.form = ConditionalReadonlyForm
        return formset
    
    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if not instance.created_by:
                instance.created_by = request.user
            instance.save()
        formset.save_m2m()
    
    @admin.display(description=_("Created by"))
    def created_by_display(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.username
        return format_html('<span style="color: #FF6B35;">🤖 SYSTEM</span>')
    
    @admin.display(description=_("Created at"))
    def created_at_display(self, obj):
        if obj.pk:
            return obj.created_at.strftime('%d.%m.%Y %H:%M')
        return "—"
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@log_deletions
@with_help_widget
@admin.register(Annotation)
class AnnotationAdmin(admin.ModelAdmin):
    """
    Admin for managing all annotations across the system.
    Usually accessed only by superusers for overview/cleanup.
    """
    list_display = ('annotation_type', 'content_object_display', 'text_preview', 
                    'created_by', 'created_at')
    list_filter = ('annotation_type', 'created_at', 'content_type')
    search_fields = ('text',)
    readonly_fields = ('content_type', 'object_id', 'created_by', 'created_at', 'updated_at')
    date_hierarchy = 'created_at'
    
    fieldsets = (
        (_("Annotation"), {
            'fields': ('annotation_type', 'text')
        }),
        (_("Attached to"), {
            'fields': ('content_type', 'object_id')
        }),
        (_("Metadata"), {
            'fields': ('created_by', 'created_at', 'updated_at')
        }),
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('created_by', 'content_type')
    
    @admin.display(description=_("Attached to"))
    def content_object_display(self, obj):
        if obj.content_object:
            return f"{obj.content_type.model}: {obj.content_object}"
        return f"{obj.content_type.model} #{obj.object_id}"
    
    @admin.display(description=_("Text"))
    def text_preview(self, obj):
        if len(obj.text) > 50:
            return obj.text[:50] + "..."
        return obj.text
    
    def has_add_permission(self, request):
        # Annotations should be added via inlines, not directly
        return False
    
    def get_model_perms(self, request):
        """
        Hide from sidebar for non-superusers.
        Annotations should be managed via inlines.
        """
        if not request.user.is_superuser:
            return {}
        return super().get_model_perms(request)