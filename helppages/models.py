# File: helppages/models.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _, get_language
from markdownx.models import MarkdownxField
from simple_history.models import HistoricalRecords

class HelpPage(models.Model):
    """Help content for admin pages, with DE/EN support."""
    
    content_type = models.OneToOneField(
        ContentType,
        on_delete=models.CASCADE,
        verbose_name=_("Target (App + Model)"),
    )
    
    # Titles (bilingual)
    title_de = models.CharField(_("Title (German)"), max_length=200, default="Hilfe")
    title_en = models.CharField(_("Title (English)"), max_length=200, default="Help")
    
    # Metadata
    author = models.CharField(_("Author"), max_length=100, blank=True)
    help_contact = models.CharField(_("Contact"), max_length=150, blank=True)
    
    # Legends (bilingual)
    legend_de = MarkdownxField(_("Legend (German)"), blank=True, default='')
    legend_en = MarkdownxField(_("Legend (English)"), blank=True, default='')
    
    # Content (bilingual)
    content_de = MarkdownxField(_("Help Content (German)"), default="-")
    content_en = MarkdownxField(_("Help Content (English)"), default="-")
    
    # Settings
    is_active = models.BooleanField(_("Active"), default=True)
    show_legend = models.BooleanField(_("Show Legend"), default=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Help Page")
        verbose_name_plural = _("Help Pages")
        ordering = ['content_type__app_label', 'content_type__model']
    
    def __str__(self):
        return f"{self.content_type}: {self.get_title()}"
    
    def get_title(self):
        """Get title in current language with fallback."""
        try:
            lang = get_language() or 'de'.lower()
            if lang and lang.startswith('de'):
                return self.title_de or self.title_en or "-"
            else:
                return self.title_en or self.title_de or "-"
        except:
            # Fallback if get_language() fails
            return self.title_de or self.title_en or "Help"
    
    def get_legend(self):
        """Get legend in current language with fallback."""
        try:
            lang = get_language() or 'de'.lower()
            if lang and lang.startswith('de'):
                return self.legend_de if self.legend_de else self.legend_en
            else:
                return self.legend_en if self.legend_en else self.legend_de
        except:
            return self.legend_de or self.legend_en or ''
    
    def get_content(self):
        """Get content in current language with fallback."""
        try:
            lang = get_language() or 'de'.lower()
            if lang and lang.startswith('de'):
                return self.content_de or self.content_en or '-'
            else:
                return self.content_en or self.content_de or '-'
        except:
            return self.content_de or self.content_en or '-'
        

    def clean(self):
        super().clean()
        if self.pk is None or self._state.adding:
            if HelpPage.objects.filter(content_type=self.content_type).exists():
                from django.core.exceptions import ValidationError
                raise ValidationError({
                    "content_type": _("A help page for this model already exists.")
                })
    
    @property
    def app_label(self):
        return self.content_type.app_label
    
    @property
    def model_name(self):
        return self.content_type.model