from __future__ import annotations
from typing import Tuple, Optional, Union

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from .models import Action, Policy, Signatory, Signature

User = get_user_model()


def resolve_signatory(user: User) -> Optional[Signatory]:
    """
    Resolve the active Signatory for a given Django user via Person -> PersonRole.
    Assumes Person has a OneToOne to auth.User (people.Person.user).
    """
    if not user or not user.is_authenticated:
        return None

    return (
        Signatory.objects
        .filter(
            is_active=True,
            person_role__person__user=user,
        )
        .select_related("person_role", "person_role__person")
        .order_by("-updated_at")   # pick a stable winner if multiple exist
        .first()
    )


def get_action(action_ref: Union[str, Action]) -> Optional[Action]:
    if isinstance(action_ref, Action):
        return action_ref
    try:
        s = action_ref.strip()
        verb_stage, scope_str = s.split("@", 1)
        verb, stage = verb_stage.split(":", 1)
        app_label, model = scope_str.split(".", 1)
        ct = ContentType.objects.get(app_label=app_label.strip(), model=model.strip().lower())
        return Action.objects.get(
            verb=verb.strip().upper(),
            stage=(stage.strip().upper() if stage.strip() != "-" else ""),
            scope=ct,
        )
    except Exception:
        return None


def can_act(user: User, action_ref: Union[str, Action], obj) -> Tuple[bool, Optional[str], Optional[Signatory], Optional[Action]]:
    """
    Returns (ok, reason, signatory, action)
    - Requires signatory.is_active and is_verified
    - Requires a Policy: role→action matching signatory.person_role.role
    - Enforces per-Action/Policy distinct signer if configured
    """
    action = get_action(action_ref) if not isinstance(action_ref, Action) else action_ref
    if not action:
        return False, _("Unknown action."), None, None

    sig = resolve_signatory(user)
    if not sig:
        return False, _("No active signatory is linked to your account."), None, action
    if not sig.is_verified:
        return False, _("Your signatory is not verified (specimen missing)."), sig, action

    role = sig.person_role.role
    pol = Policy.objects.filter(role=role, action=action).first()
    if not pol:
        return False, _("You are not authorized to perform this action."), sig, action

    # Optional separation-of-duties
    if pol.require_distinct_signer:
        ct = ContentType.objects.get_for_model(obj.__class__)
        # Consider any earlier signature on this object with the same scope
        prior = Signature.objects.filter(
            content_type=ct, object_id=str(obj.pk), scope_ct=action.scope
        ).exclude(signatory=sig)
        if not prior.exists():
            return False, _("This action requires a different signatory than earlier stages."), sig, action

    return True, None, sig, action


def record_signature(user: User, action_ref: Union[str, Action], obj, *, note: str = "", payload=None) -> Signature:
    ok, reason, sig, action = can_act(user, action_ref, obj)
    if not ok:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied(reason or "Not allowed.")

    ct = ContentType.objects.get_for_model(obj.__class__)
    return Signature.objects.create(
        signatory=sig,
        content_type=ct,
        object_id=str(obj.pk),
        action=action,
        verb=action.verb,
        stage=action.stage,
        scope_ct=action.scope,
        note=note or "",
        payload=payload or {},
    )

from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext as _t
from .models import Signature

def render_signatures_box(obj):
    if not obj or not getattr(obj, "pk", None):
        return _t("— save first to see signatures —")

    ct = ContentType.objects.get_for_model(obj.__class__)
    rows = (
        Signature.objects
        .filter(content_type=ct, object_id=str(obj.pk))
        .select_related("signatory", "signatory__person_role", "signatory__person_role__person")
        .order_by("at", "id")
    )

    ctx = {
        "has_rows": rows.exists(),
        "rows": [
            {
                "verb": s.verb,
                "stage": s.stage or "",
                "code": f"{s.verb}/{s.stage or '-'}",
                "when": s.at,
                "who": s.signatory.display_name,
                "sig_id_short": (s.signature_id or "")[:12],
                "sig_id": s.signature_id,
                "note": s.note or "",
            }
            for s in rows
        ],
        # let the template pick colors similar to PTO box
        "title": _("Signatures / Authorizations"),
    }
    html = render_to_string("hankosign/signature_box.html", ctx)
    return mark_safe(html)
