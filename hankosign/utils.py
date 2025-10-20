# hankosign/utils.py
from __future__ import annotations
from typing import Tuple, Optional, Union

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from django.db.models import Max

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
        .order_by("-updated_at")
        .first()
    )


def get_action(action_ref: Union[str, Action]) -> Optional[Action]:
    """
    Accept an Action instance or a code like 'VERB:STAGE@app_label.model'.
    Use '-' for empty stage.
    """
    if isinstance(action_ref, Action):
        return action_ref
    try:
        s = (action_ref or "").strip()
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


def can_act(
    user: User,
    action_ref: Union[str, Action],
    obj,
) -> Tuple[bool, Optional[str], Optional[Signatory], Optional[Action], Optional[Policy]]:
    """
    Returns (ok, reason, signatory, action, policy)

    - Requires a verified active signatory mapped to the user
    - Requires a Policy(role -> action)
    - Enforces separation of duties if Policy.require_distinct_signer is True
    """
    action = get_action(action_ref) if not isinstance(action_ref, Action) else action_ref
    if not action:
        return False, _("Unknown action."), None, None, None

    sig = resolve_signatory(user)
    if not sig:
        return False, _("No active signatory is linked to your account."), None, action, None
    if not sig.is_verified:
        return False, _("Your signatory is not verified (specimen missing)."), sig, action, None

    role = sig.person_role.role
    pol = Policy.objects.filter(role=role, action=action).first()
    if not pol:
        return False, _("You are not authorized to perform this action."), sig, action, None

    # Separation-of-duties check (if enabled)
    if pol.require_distinct_signer:
        ct = ContentType.objects.get_for_model(obj.__class__)
        # earlier signatures on the same object & same scope (any verb/stage)
        prior_any = Signature.objects.filter(
            content_type=ct, object_id=str(obj.pk), scope_ct=action.scope
        )
        # If this same signatory has already signed any earlier stage in this scope, block
        if prior_any.filter(signatory=sig).exists():
            return False, _("A different signatory is required for this stage."), sig, action, pol

    return True, None, sig, action, pol


def record_signature(
    user: User,
    action_ref: Union[str, Action],
    obj,
    *,
    note: str = "",
    payload=None,
) -> Signature:
    ok, reason, sig, action, pol = can_act(user, action_ref, obj)
    if not ok:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied(reason or "Not allowed.")

    ct = ContentType.objects.get_for_model(obj.__class__)

    # For non-repeatable policies: REFUSE repeats
    if not pol.is_repeatable:
        exists = Signature.objects.filter(
            content_type=ct, object_id=str(obj.pk),
            verb=action.verb, stage=action.stage,
        ).exists()
        if exists:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied(_("This action has already been performed."))

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
        is_repeatable=bool(pol.is_repeatable),  # snapshot
    )


# ---------- read-only signature box (admin widget helper) ----------

def render_signatures_box(obj):
    from django.utils.translation import gettext as _t
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
        "title": _("HankoSign Workflow Control"),
    }
    html = render_to_string("hankosign/signature_box.html", ctx)
    return mark_safe(html)


# ---------- tiny helpers you use in admin ----------

def _scope_ct(obj):
    return ContentType.objects.get_for_model(obj.__class__)

def has_sig(obj, verb: str, stage: str) -> bool:
    return Signature.objects.filter(
        content_type=_scope_ct(obj),
        object_id=str(obj.pk),
        verb=verb,
        stage=stage,
    ).exists()

def sig_time(obj, verb: str, stage: str):
    s = (
        Signature.objects
        .filter(content_type=_scope_ct(obj), object_id=str(obj.pk), verb=verb, stage=stage)
        .order_by("at", "id")
        .first()
    )
    return s.at if s else None

# NEW: last occurrence for a verb (optionally limited to certain stages)
def _last(obj, verb: str, stages: set[str] | None = None):
    ct = _scope_ct(obj)
    qs = Signature.objects.filter(content_type=ct, object_id=str(obj.pk), verb=verb)
    if stages is not None:
        qs = qs.filter(stage__in=list(stages))
    row = qs.order_by("-at", "-id").first()
    return row.at if row else None

# NEW: which stages have at least one signature for this verb on this object
def _stages(obj, verb: str) -> set[str]:
    ct = _scope_ct(obj)
    return set(
        Signature.objects
        .filter(content_type=ct, object_id=str(obj.pk), verb=verb)
        .exclude(stage="")
        .values_list("stage", flat=True)
        .distinct()
    )

# REPLACE your old state_snapshot with this universal version
def state_snapshot(obj) -> dict:
    """
    Universal snapshot:
      - 'submitted' => last SUBMIT is after last WITHDRAW (any stage)
      - 'approved'  => set of stages that approved (from data)
      - 'rejected'  => set of stages that rejected (from data)
      - 'required'  => set of approval stages required (from configured Actions)
      - 'final'     => all required approvals present
      - 'locked'    => simple lock rule (submitted or any approved or final)
    """
    if not obj or not getattr(obj, "pk", None):
        return {"submitted": False, "approved": set(), "rejected": set(), "required": set(), "final": False, "locked": False}

    ct = _scope_ct(obj)

    # What approvals are required for this model (configuration-driven)?
    required = set(
        Action.objects
        .filter(scope=ct, verb=Action.Verb.APPROVE)
        .values_list("stage", flat=True)
    )

    # Facts from signatures
    t_submit   = _last(obj, "SUBMIT")     # any stage
    t_withdraw = _last(obj, "WITHDRAW")   # any stage
    t_lock = _last(obj, "LOCK")
    t_unlock = _last(obj, "UNLOCK")
    submitted  = bool(t_submit and (not t_withdraw or t_submit > t_withdraw))
    explicit_locked = bool(t_lock and (not t_unlock or t_lock > t_unlock))

    approved = _stages(obj, "APPROVE")
    rejected = _stages(obj, "REJECT")

    final = bool(required) and required.issubset(approved)

    locked = explicit_locked or submitted or bool(approved) or final

    return {
        "submitted": submitted,
        "approved": approved,
        "rejected": rejected,
        "required": required,
        "final": final,
        "locked": locked,
        "explicit_locked": explicit_locked,
    }