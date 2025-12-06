# File: hankosign/models.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from __future__ import annotations
from django.db import models

import hmac, hashlib, secrets
from dataclasses import dataclass
from typing import Optional, Tuple

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from simple_history.models import HistoricalRecords

from people.models import Role, PersonRole


class Action(models.Model):
    class Verb(models.TextChoices):
        SUBMIT = "SUBMIT", _("Submit")
        VERIFY = "VERIFY", _("Verify")
        APPROVE = "APPROVE", _("Approve")
        RELEASE = "RELEASE", _("Release/Print")
        WITHDRAW = "WITHDRAW", _("Withdraw")
        REJECT = "REJECT", _("Reject")
        LOCK = "LOCK", _("Lock")
        UNLOCK = "UNLOCK", _("Unlock")

    verb = models.CharField(_("Verb"), max_length=20, choices=Verb.choices)
    stage = models.CharField(
        _("Stage code"),
        max_length=32,
        blank=True,
        help_text=_("Optional: e.g. WIREF, CHAIR …"),
    )
    scope = models.ForeignKey(
        ContentType, on_delete=models.PROTECT, related_name="hankosign_actions", verbose_name=_("Scope (model)")
    )

    human_label = models.CharField(_("Label"), max_length=160)
    comment = models.TextField(_("Comment/help"), blank=True)

    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    is_repeatable = models.BooleanField(
        _("Repeatable"),
        default=False,
        help_text=_("This action may be performed multiple times on the same object."),
    )
    require_distinct_signer = models.BooleanField(
        _("Require distinct signer"),
        default=False,
        help_text=_("The same person cannot perform multiple gated stages on the same object."),
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Action")
        verbose_name_plural = _("Actions")
        unique_together = (("verb", "stage", "scope"),)
        indexes = [models.Index(fields=["scope", "verb", "stage"])]

    def __str__(self) -> str:
        return f"{self.action_code} — {self.human_label}"

    @property
    def action_code(self) -> str:
        return f"{self.verb}:{self.stage or '-'}@{self.scope.app_label}.{self.scope.model}"
    
    def clean(self):
        super().clean()
        if self.pk is None or self._state.adding:
            exists = Action.objects.filter(
                verb=self.verb,
                stage=self.stage or "",
                scope=self.scope
            ).exists()
            if exists:
                raise ValidationError({
                    "__all__": _("An action with this verb/stage/scope combination already exists.")
                })


class Policy(models.Model):
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="hankosign_policies", verbose_name=_("Role"))
    
    action = models.ForeignKey(Action, on_delete=models.PROTECT, related_name="policies", verbose_name=_("Action"), null=True, blank=True)

    actions = models.ManyToManyField(
        Action, related_name="policies_m2m", blank=True, verbose_name=_("Additional actions")
    )

    notes = models.CharField(_("Notes"), max_length=240, blank=True)

    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    history = HistoricalRecords()
    _actions_ids_pending = None  # transient
    class Meta:
        verbose_name = _("Policy")
        verbose_name_plural = _("Policies")
        unique_together = (("role", "action"),)
        indexes = [
            models.Index(fields=["role", "action"]),
            models.Index(fields=["role"]),  # helps when filtering policies by role
        ]

    def set_pending_actions(self, ids):
        # call this from the admin form if you want belt+suspenders
        self._actions_ids_pending = [int(x) for x in ids if x]

    def __str__(self) -> str:
        if self.action_id:
            return f"{self.role} → {self.action.action_code}"
        return f"{self.role} → {self.actions.count()} actions"

    def save(self, *args, **kwargs):
        # run full validation; clean() will read _actions_ids_pending
        self.full_clean()
        super().save(*args, **kwargs)
        # after we have a PK, if we had pending M2M, write them now
        if self._actions_ids_pending is not None:
            self.actions.set(self._actions_ids_pending)
            self._actions_ids_pending = None

    def clean(self):
        super().clean()
        has_fk = bool(self.action_id)
        m2m_pending = getattr(self, "_actions_ids_pending", None)
        has_m2m = bool(m2m_pending) or (self.pk and self.actions.exists())

        # Only enforce after we either have an FK, or pending, or the instance already exists.
        if not (has_fk or has_m2m):
            if self.pk is None and m2m_pending is None:
                # allow first save; admin/form will pass pending, scripts can set then save_m2m later
                return
        if has_fk and has_m2m:
            raise ValidationError({"actions": _("Use either the legacy FK *or* the list, not both.")})
        if not has_fk and not has_m2m:
            raise ValidationError({"actions": _("Pick at least one Action (legacy FK or the list).")})
        
        if self.action_id and self.role_id:
            exists = Policy.objects.filter(
                role=self.role,
                action=self.action
            ).exclude(pk=self.pk).exists()
            if exists:
                raise ValidationError({
                    "__all__": _("A policy for this role and action already exists.")
                })



def _default_base_key() -> str:
    return secrets.token_hex(32)


class Signatory(models.Model):
    """
    Person-capability for signing/authorizing actions.
    """

    person_role = models.ForeignKey(
        PersonRole, on_delete=models.PROTECT, related_name="signatories", verbose_name=_("Assignment")
    )

    is_active = models.BooleanField(_("Active"), default=True)
    is_verified = models.BooleanField(_("Verified (specimen on file)"), default=False)

    name_override = models.CharField(_("Printed name (override)"), max_length=160, blank=True)
    base_key = models.CharField(_("Signer secret"), max_length=64, default=_default_base_key, editable=False)

    pdf_specimen = models.FileField(
        _("Signature specimen (PDF)"), upload_to="signatures/specimen/%Y/%m/", null=True, blank=True
    )

    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Signatory")
        verbose_name_plural = _("Signatories")

    def __str__(self) -> str:
        return self.display_name
    
    @property
    def user(self):
        return getattr(self.person_role.person, "user", None)

    @property
    def display_name(self) -> str:
        if self.name_override:
            return self.name_override
        p = self.person_role.person
        return f"{p.first_name} {p.last_name}"

from django.db.models import Q
class Signature(models.Model):
    """Immutable record of a performed action on an object."""
    signatory = models.ForeignKey(Signatory, on_delete=models.PROTECT, related_name="signatures", verbose_name=_("Signatory"))
    is_repeatable = models.BooleanField(default=False, editable=False)
    # Target object (generic)
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.CharField(max_length=64)
    target = GenericForeignKey("content_type", "object_id")

    # Action snapshot
    action = models.ForeignKey(Action, on_delete=models.PROTECT, related_name="signatures")
    verb = models.CharField(max_length=20)                       # copy of Action.verb
    stage = models.CharField(max_length=32, blank=True)          # copy of Action.stage
    scope_ct = models.ForeignKey(ContentType, on_delete=models.PROTECT, related_name="+")  # copy of Action.scope

    # Metadata
    at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=240, blank=True)
    payload = models.JSONField(null=True, blank=True)

    # Computed immutable signature id
    signature_id = models.CharField(max_length=64, editable=False, db_index=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Signature")
        verbose_name_plural = _("Signatures")
        constraints = [
            models.UniqueConstraint(
                fields=["content_type", "object_id", "verb", "stage"],
                condition=Q(is_repeatable=False),
                name="uq_sig_nonrepeat_per_object_verb_stage",
            )
        ]
        ordering = ("-at", "-id")
        indexes = [
            models.Index(fields=["at"]),
            models.Index(fields=["-at"]),
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["verb", "stage"]),
            models.Index(fields=["content_type", "object_id", "verb", "stage",])
        ]

    def __str__(self) -> str:
        return f"{self.verb}/{self.stage or '-'} on {self.content_type.app_label}.{self.content_type.model}#{self.object_id}"

    def clean(self):
        super().clean()
        if self.action and self.scope_ct_id and self.action.scope_id != self.scope_ct_id:
            raise ValidationError({"action": _("Action scope doesn't match signature scope.")})

    def save(self, *args, **kwargs):
        # Fill snapshot fields if missing (first save)
        if not self.pk:
            self.verb = self.verb or self.action.verb
            self.stage = self.stage or self.action.stage
            self.scope_ct_id = self.scope_ct_id or self.action.scope_id

            # Compute HMAC over stable tuple
            msg = "|".join(
                [
                    self.verb,
                    self.stage or "",
                    f"{self.content_type_id}",
                    str(self.object_id),
                ]
            ).encode("utf-8")
            key = f"{settings.HANKOSIGN_SECRET}:{self.signatory.base_key}".encode("utf-8")
            self.signature_id = hmac.new(key, msg, hashlib.sha256).hexdigest()
        super().save(*args, **kwargs)
