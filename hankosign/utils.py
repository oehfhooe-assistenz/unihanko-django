# hankosign/utils.py
from __future__ import annotations
from typing import Tuple, Optional, Union

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from django.db.models import Max
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q, Case, When, IntegerField
from .models import Action, Policy, Signatory, Signature
User = get_user_model()
from django.core.cache import cache


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
    # Prefer exact FK hits over M2M (so old policies behave predictably)
    qs = (Policy.objects
          .filter(role=role)
          .filter(Q(action=action) | Q(actions=action))
          .annotate(_direct=Case(
              When(action=action, then=1),
              default=0,
              output_field=IntegerField(),
          ))
          .order_by("-_direct", "-updated_at"))

    pol = qs.first()
    if not pol:
        return False, _("You are not authorized to perform this action."), sig, action, None

    # Separation-of-duties check (if enabled)
    if action.require_distinct_signer:
        ct = ContentType.objects.get_for_model(obj.__class__)
        # earlier signatures on the same object & same scope (any verb/stage)
        prior_any = Signature.objects.filter(
            content_type=ct, object_id=str(obj.pk), scope_ct=action.scope
        )
        # If this same signatory has already signed any earlier stage in this scope, block
        if prior_any.filter(signatory=sig).exists():
            return False, _("A different signatory is required for this stage."), sig, action, pol

    return True, None, sig, action, pol

import logging
logger = logging.getLogger('hankosign')
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
    if not action.is_repeatable:
        exists = Signature.objects.filter(
            content_type=ct, object_id=str(obj.pk),
            verb=action.verb, stage=action.stage,
        ).exists()
        if exists:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied(_("This action has already been performed."))

    # Soft dedupe window: same signatory, same verb/stage/object within N seconds
    window = timezone.now() - timedelta(seconds=10)
    recent = Signature.objects.filter(
        content_type=ct, object_id=str(obj.pk),
        verb=action.verb, stage=action.stage,
        signatory=sig,
        at__gte=window,
    ).exists()
    if recent:
        # swallow as a no-op; return the latest row for convenience
        return (Signature.objects
                .filter(content_type=ct, object_id=str(obj.pk),
                        verb=action.verb, stage=action.stage, signatory=sig)
                .order_by("-at", "-id")
                .first())
    signum = Signature.objects.create(
        signatory=sig,
        content_type=ct,
        object_id=str(obj.pk),
        action=action,
        verb=action.verb,
        stage=action.stage,
        scope_ct=action.scope,
        note=note or "",
        payload=payload or {},
        is_repeatable=bool(action.is_repeatable),  # snapshot
    )
    logger.info(
        f"Signature recorded: {signum.verb}/{signum.stage} "
        f"on {signum.content_type.model}#{signum.object_id} "
        f"by {signum.signatory.display_name} "
    )
    return signum


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


# last occurrence for a verb (optionally limited to certain stages)
def _last(obj, verb: str, stages: set[str] | None = None):
    ct = _scope_ct(obj)
    qs = Signature.objects.filter(content_type=ct, object_id=str(obj.pk), verb=verb)
    if stages is not None:
        qs = qs.filter(stage__in=list(stages))
    row = qs.order_by("-at", "-id").first()
    return row.at if row else None


# which stages have at least one signature for this verb on this object
def _stages(obj, verb: str) -> set[str]:
    ct = _scope_ct(obj)
    return set(
        Signature.objects
        .filter(content_type=ct, object_id=str(obj.pk), verb=verb)
        .exclude(stage="")
        .values_list("stage", flat=True)
        .distinct()
    )


# state snapshot machine (for deltas use model-specific reducer methods)
def state_snapshot(obj) -> dict:
    """
    Universal snapshot:
      - 'submitted' => last SUBMIT is after last WITHDRAW (any stage)
      - 'approved'  => set of stages that approved (from data)
      - 'rejected'  => ANY REJECT signature exists (boolean)
      - 'required'  => set of approval stages required (from configured Actions)
      - 'final'     => all required approvals present
      - 'locked'    => simple lock rule (submitted or any approved or final)
    """
    if not obj or not getattr(obj, "pk", None):
        return {
            "submitted": False,
            "approved": set(),
            "rejected": False,  # ← Changed to boolean
            "required": set(),
            "final": False,
            "locked": False
        }

    ct = _scope_ct(obj)

    # What approvals are required for this model (configuration-driven)?
    required = set(
        Action.objects
        .filter(scope=ct, verb=Action.Verb.APPROVE)
        .values_list("stage", flat=True)
    )

    # Facts from signatures
    t_submit   = _last(obj, "SUBMIT")
    t_withdraw = _last(obj, "WITHDRAW")
    t_lock = _last(obj, "LOCK")
    t_unlock = _last(obj, "UNLOCK")
    submitted  = bool(t_submit and (not t_withdraw or t_submit > t_withdraw))
    explicit_locked = bool(t_lock and (not t_unlock or t_lock > t_unlock))

    approved = _stages(obj, "APPROVE")
    
    # Check if ANY REJECT signature exists (regardless of stage)
    rejected = Signature.objects.filter(
        content_type=ct,
        object_id=str(obj.pk),
        verb="REJECT"
    ).exists()  # ← Boolean instead of set

    final = bool(required) and required.issubset(approved)

    locked = explicit_locked or submitted or bool(approved) or final

    return {
        "submitted": submitted,
        "approved": approved,
        "rejected": rejected,  # ← Now boolean
        "required": required,
        "final": final,
        "locked": locked,
        "explicit_locked": explicit_locked,
    }


def object_status(obj, *, final_stage="CHAIR", tier1_stage="WIREF"):
    """
    Return a normalized status for any HankoSign-driven object.

    Priority (highest → lowest):
      locked > final-approved > final-rejected > tier1-rejected > tier1-approved > submitted > draft

    Args:
      final_stage: stage name that means the 'final' approver (default "CHAIR")
      tier1_stage: stage name for the first approver tier (default "WIREF")

    Returns:
      dict(code=str, label=str)

    Codes (stable for CSS/data-state):
      draft | submitted | approved-tier1 | final | rejected-tier1 | rejected-final | locked
    """
    st = state_snapshot(obj)

    approved = st.get("approved", set()) or set()
    rejected = st.get("rejected", set()) or set()

    # 1) explicit lock always wins
    if st.get("explicit_locked"):
        return {"code": "locked", "label": _("Locked")}

    # 2) final approve / reject
    if final_stage in approved or st.get("final"):
        return {"code": "final", "label": _("Final")}
    if final_stage in rejected:
        return {"code": "rejected-final", "label": _("Rejected (Final)")}

    # 3) tier1 approve / reject
    if tier1_stage in rejected:
        return {"code": "rejected-tier1", "label": _("Rejected (WiRef)")}
    if tier1_stage in approved:
        return {"code": "approved-tier1", "label": _("Approved (WiRef)")}

    # 4) submitted vs draft
    if st.get("submitted"):
        return {"code": "submitted", "label": _("Submitted")}

    return {"code": "draft", "label": _("Draft")}


def object_status_span(obj, *, final_stage="CHAIR", tier1_stage="WIREF"):
    """
    Convenience for admin list columns: emits the <span> your CSS targets.
    """
    s = object_status(obj, final_stage=final_stage, tier1_stage=tier1_stage)
    # NOTE: keep 'js-state' and 'data-state' stable across modules
    from django.utils.html import format_html
    return format_html(
        '<span class="js-state" data-state="{}">{}</span>',
        s["code"], s["label"]
    )


# ---------- Attestation Seal helpers (PDF) ----------
# Human label for each verb/stage you currently use
_ACTION_LABELS = {
    ("SUBMIT",   "ASS"):   _("Submit"),
    ("WITHDRAW", "ASS"):   _("Withdraw"),
    ("APPROVE",  "WIREF"): _("Approve (WiRef)"),
    ("REJECT",   "WIREF"): _("Reject (WiRef)"),
    ("APPROVE",  "CHAIR"): _("Approve (Chair)"),
    ("REJECT",   "CHAIR"): _("Reject (Chair)"),
    ("LOCK",     ""):      _("Lock"),
    ("UNLOCK",   ""):      _("Unlock"),

    # Finances module (PaymentPlan)
    ("SUBMIT",   "WIREF"): _("Submit (WiRef)"),
    ("WITHDRAW", "WIREF"): _("Withdraw (WiRef)"),
    ("VERIFY",   "WIREF"): _("Verify banking"),
    ("REJECT",   ""):      _("Cancel/Terminate"),
    ("RELEASE",  ""):      _("Print/Release"),
}


def action_display(sig: Signature) -> str:
    """Return the human label for a signature's action."""
    stage = (sig.stage or "").upper()
    return _ACTION_LABELS.get((sig.verb.upper(), stage),
                              f"{sig.verb.title()} ({stage or '-'})")


def _short_sig_id(sig: Signature) -> str:
    """
    Produce a stable short token for display.
    Prefer Signature.signature_id (if present), else fall back to DB id.
    We take the last 8 hex chars and format XXXX-XXXX.
    """
    base = (getattr(sig, "signature_id", None) or str(sig.id) or "").replace("-", "")
    # ensure we have hex-ish chars; fallback to whole string if very short
    s = "".join(ch for ch in base if ch.isalnum()).upper()
    if len(s) < 8:
        return s or "—"
    tail = s[-8:]
    return f"{tail[:4]}-{tail[4:]}"


def seal_signatures_context(obj, *, tz=None) -> list[dict]:
    """
    Return a list of signatures for the HankoSign Attestation Seal.
    Each item has: who, action, when, sig_id_short.
    """
    if not obj or not getattr(obj, "pk", None):
        return []

    ct = ContentType.objects.get_for_model(obj.__class__)
    rows = (
        Signature.objects
        .filter(content_type=ct, object_id=str(obj.pk))
        .select_related("signatory", "signatory__person_role", "signatory__person_role__person", "action")
        .order_by("at", "id")
    )

    out = []
    for s in rows:
        who = getattr(s.signatory, "display_name", None) or _("(unknown)")
        verb = (s.verb or "").upper()
        stage = (s.stage or "").upper()
        action_label = f"{verb}/{stage or '-'}"
        when_str = timezone.localtime(s.at, tz or timezone.get_current_timezone()).strftime("%Y-%m-%d %H:%M") if s.at else "—"
        sig_id_short = (s.signature_id or str(s.id) or "")[:12]
        out.append({
            "who": who,
            "action": action_label,
            "when": when_str,
            "sig_id_short": sig_id_short,
        })
    return out


# --- request-id (rid) helpers + idempotent sign ---
# Tiny JS you can reuse on DAO links to append a unique rid per click
RID_JS = (
    "this.href = this.href + (this.href.indexOf('?')>-1?'&':'?') + "
    "'rid=' + (Date.now().toString(36) + Math.random().toString(36).slice(2));"
)


def get_rid(request) -> Optional[str]:
    rid = (request.GET.get("rid") or "").strip()
    return rid or None


def _once_key(*, user_id: int, obj, action, rid: Optional[str]) -> str:
    ct = ContentType.objects.get_for_model(obj.__class__)
    base = f"{action.verb}:{action.stage or '-'}@{action.scope_id}"
    return f"hs:once:{base}:{user_id}:{ct.id}:{obj.pk}:{rid or 'no-rid'}"


def sign_once(
    request,
    action_ref: Union[str, Action],
    obj,
    *,
    note: str = "",
    payload=None,
    window_seconds: int = 10,
) -> Optional[Signature]:
    """
    Idempotent signer for GET-able actions.
    - Uses a per-click rid + cache key to ensure a single insert.
    - Falls back to your normal dedupe in record_signature.
    Returns the Signature (if created) or the latest matching row (if swallowed).
    """
    # Resolve & authorize first
    ok, reason, sig, action, pol = can_act(request.user, action_ref, obj)
    if not ok:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied(reason or "Not allowed.")

    # Gate on (user, obj, action, rid)
    key = _once_key(user_id=request.user.id, obj=obj, action=action, rid=get_rid(request))
    if cache.add(key, 1, window_seconds):
        # First hit within window → perform the real write
        return record_signature(request.user, action, obj, note=note, payload=payload)

    # Not first → no-op; hand back the latest row for convenience
    ct = ContentType.objects.get_for_model(obj.__class__)
    return (
        Signature.objects
        .filter(content_type=ct, object_id=str(obj.pk), verb=action.verb, stage=action.stage, signatory=sig)
        .order_by("-at", "-id")
        .first()
    )