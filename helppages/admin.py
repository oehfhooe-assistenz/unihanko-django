# File: helppages/admin.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from markdownx.admin import MarkdownxModelAdmin
from core.admin_mixins import HistoryGuardMixin, with_help_widget
from .models import HelpPage
from simple_history.admin import SimpleHistoryAdmin
from core.admin_mixins import log_deletions

@log_deletions
@with_help_widget
@admin.register(HelpPage)
class HelpPageAdmin(
    SimpleHistoryAdmin,
    MarkdownxModelAdmin,
    HistoryGuardMixin
    ):
    list_display = ('content_type', 'get_title', 'author', 'is_active', 'updated_at')
    list_filter = ('is_active', 'content_type__app_label', 'show_legend')
    search_fields = ('title_de', 'title_en', 'content_de', 'content_en', 'author')
    readonly_fields = ('created_at', 'updated_at')

    
    fieldsets = (
        (_("Target"), {
            'fields': ('content_type',),
        }),
        (_("Metadata"), {
            'fields': ('author', 'help_contact', 'is_active', 'show_legend'),
        }),
        (_("Titles"), {
            'fields': (('title_de', 'title_en'),),
        }),
        (_("Quick Reference (Always Visible)"), {
            'fields': (('legend_de'), ('legend_en'),),
            'description': _('Short text explaining status badges, icons, etc.'),
        }),
        (_("Full Help Content (Accordion)"), {
            'fields': (('content_de'), ('content_en'),),
            'description': _('Detailed help text. Use AI to translate between languages!'),
        }),
        (_("System"), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    
    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj:
            ro.append('content_type')
        return ro
    
    def get_title(self, obj):
        """Show current language title in list."""
        return obj.get_title()
    get_title.short_description = _("Title")
    

    def has_delete_permission(self, request, obj=None):
        return False