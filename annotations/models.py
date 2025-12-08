# File: annotations/models.py
# Version: 1.0.5
# Author: vas
# Modified: 2025-12-08

from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class Annotation(models.Model):
    """
    Generic annotations/remarks that can attach to any model.
    Used for collaboration, corrections, and system event logging.
    
    Examples:
    - User comments on SessionItems, PaymentPlans, etc.
    - System annotations when HankoSign actions occur
    - Correction notes for data issues
    """
    
    class AnnotationType(models.TextChoices):
        USER = "USER", _("User Comment")
        SYSTEM = "SYSTEM", _("System Event")
        CORRECTION = "CORRECTION", _("Correction")
        INFO = "INFO", _("Information")
    
    # Generic relation - can point to ANY model
    content_type = models.ForeignKey(
        ContentType, 
        on_delete=models.CASCADE,
        verbose_name=_("Content type"),
        help_text=_("The type of object this annotation is attached to")
    )
    object_id = models.PositiveIntegerField(
        verbose_name=_("Object ID"),
        help_text=_("The ID of the specific object")
    )
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Annotation content
    annotation_type = models.CharField(
        _("Type"),
        max_length=20, 
        choices=AnnotationType.choices, 
        default=AnnotationType.USER
    )
    text = models.TextField(_("Text"))
    
    # Metadata
    created_by = models.ForeignKey(
        User, 
        on_delete=models.PROTECT,
        null=True, blank=True,
        verbose_name=_("Created by"),
        help_text=_("User who created this annotation (null for system annotations)")
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
        ]
        verbose_name = _("Annotation")
        verbose_name_plural = _("Annotations")
    

    def __str__(self):
        if self.created_by:
            creator = self.created_by.get_full_name() or self.created_by.username
        else:
            creator = "SYSTEM"
        return f"{self.get_annotation_type_display()} by {creator} at {self.created_at:%Y-%m-%d %H:%M}"
    
    @property
    def is_system(self):
        """Is this a system-generated annotation?"""
        return self.annotation_type == self.AnnotationType.SYSTEM