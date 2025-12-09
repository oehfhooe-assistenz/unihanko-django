# HANKOSIGN.md

**Module:** `hankosign`  
**Purpose:** Digital signature workflow system with HMAC-based cryptographic attestation  
**Version:** 1.0.3 (models), 1.0.5 (utils), 1.0.1 (admin)  
**Dependencies:** people (Person, Role, PersonRole), ContentType framework

---

## 1. Overview

HankoSign is a cryptographic digital signature system that powers approval workflows throughout UniHanko. It provides:

- **Action definitions** - Configurable workflow verbs (SUBMIT, APPROVE, REJECT, etc.) with optional stages
- **Policy-based authorization** - Role-to-action mappings for permission control
- **Cryptographic signatures** - HMAC-SHA256 attestation with immutable audit trail
- **Separation of duties** - Enforces distinct signers across workflow stages
- **Idempotency** - Prevents duplicate signatures with request ID tracking
- **State machine helpers** - Query current workflow status (draft, submitted, approved, etc.)

The name "HankoSign" references Japanese hanko (判子) - personal seal stamps used for official signatures.

---

## 2. Models

### 2.1 Action

**Purpose:** Define a workflow action with verb, optional stage, and target model scope.

**Verb Enum:**

```python
class Verb(models.TextChoices):
    SUBMIT = "SUBMIT", _("Submit")
    VERIFY = "VERIFY", _("Verify")
    APPROVE = "APPROVE", _("Approve")
    RELEASE = "RELEASE", _("Release/Print")
    WITHDRAW = "WITHDRAW", _("Withdraw")
    REJECT = "REJECT", _("Reject")
    LOCK = "LOCK", _("Lock")
    UNLOCK = "UNLOCK", _("Unlock")
```

**Fields:**
- `verb`: CharField(20) - action verb (from Verb enum)
- `stage`: CharField(32) blank - optional stage identifier (e.g., WIREF, CHAIR, ASS)
- `scope`: ForeignKey(ContentType, PROTECT) - target model for this action
- `human_label`: CharField(160) - display label for UI
- `comment`: TextField blank - help text/description
- `is_repeatable`: BooleanField default=False - allow multiple signatures on same object
- `require_distinct_signer`: BooleanField default=False - enforce different signatory per stage
- `created_at`, `updated_at`: DateTimeField auto

**Constraints:**
- unique_together: (verb, stage, scope) - each action is uniquely identified by this tuple

**Indexes:**
- (scope, verb, stage)

**Properties:**

```python
@property
def action_code(self) -> str
```
Format: `VERB:STAGE@app_label.model` (e.g., `APPROVE:WIREF@employees.paymentplan`)  
Stage uses `-` if empty.

**Save Behavior:**

On creation:
- Atomic check with select_for_update() to prevent duplicates
- Raises ValidationError if (verb, stage, scope) combination exists

**History:** simple_history tracked

**Delete Policy:** No delete permission (immutable once created)

**Example Actions:**
```
SUBMIT:ASS@assembly.resolution
APPROVE:WIREF@finances.paymentplan
APPROVE:CHAIR@finances.paymentplan
LOCK:-@finances.fiscalyear
RELEASE:-@employees.timesheet
```

---

### 2.2 Policy

**Purpose:** Map roles to actions, granting authorization for workflow operations.

**Fields:**
- `role`: ForeignKey(Role, PROTECT) - role receiving permission
- `action`: ForeignKey(Action, PROTECT) nullable - legacy FK (single action)
- `actions`: ManyToManyField(Action) - modern M2M (multiple actions)
- `notes`: CharField(240) blank - optional notes
- `created_at`, `updated_at`: DateTimeField auto

**Constraints:**
- unique_together: (role, action) - for legacy FK usage

**Indexes:**
- (role, action) - for FK queries
- (role) - for filtering by role

**Transient Attribute:**
- `_actions_ids_pending`: Temporary storage for M2M IDs during form save

**Methods:**

```python
def set_pending_actions(self, ids)
```
Store M2M action IDs temporarily before first save (called by admin form).

```python
def clean(self)
```
Validation:
- Must have either FK action OR M2M actions (not both, not neither)
- Legacy FK and M2M are mutually exclusive
- Exception: On initial save without M2M data (allows admin workflow)

```python
def save(self, *args, **kwargs)
```
1. Calls full_clean() to validate FK/M2M rules
2. On creation with FK: Atomic duplicate check
3. After save with PK: Writes pending M2M if set

**History:** simple_history tracked

**Delete Policy:** No delete permission (immutable once created)

**Usage Pattern:**
- Old: One Policy per role-action pair (via FK)
- New: One Policy per role with multiple actions (via M2M)

---

### 2.3 Signatory

**Purpose:** Person-capability for signing/authorizing actions, linked to PersonRole assignment.

**Fields:**
- `person_role`: ForeignKey(PersonRole, PROTECT) - assignment providing signing authority
- `is_active`: BooleanField default=True - currently authorized
- `is_verified`: BooleanField default=False - specimen signature on file
- `name_override`: CharField(160) blank - custom printed name (overrides person name)
- `base_key`: CharField(64) default=secrets.token_hex(32) - secret key for HMAC (non-editable)
- `pdf_specimen`: FileField nullable upload_to="signatures/specimen/%Y/%m/" - signature specimen PDF
- `created_at`, `updated_at`: DateTimeField auto

**Properties:**

```python
@property
def user(self)
```
Returns associated Django user via person_role.person.user (or None).

```python
@property
def display_name(self) -> str
```
Returns name_override if set, otherwise "{first_name} {last_name}" from person.

**History:** simple_history tracked

**Delete Policy:** No delete permission (audit trail preservation)

**Readonly After Creation:** person_role (scope immutable)

**Security:**
- `base_key` is randomly generated on creation
- Combined with `HANKOSIGN_SECRET` setting for HMAC computation
- Never displayed in UI (editable=False)

---

### 2.4 Signature

**Purpose:** Immutable record of a performed action on an object with cryptographic attestation.

**Fields:**

**Signatory:**
- `signatory`: ForeignKey(Signatory, PROTECT) - who signed
- `is_repeatable`: BooleanField default=False editable=False - snapshot of action repeatability

**Target Object (Generic):**
- `content_type`: ForeignKey(ContentType, PROTECT) - target model type
- `object_id`: CharField(64) - target object ID
- `target`: GenericForeignKey - convenience accessor

**Action Snapshot:**
- `action`: ForeignKey(Action, PROTECT) - action definition
- `verb`: CharField(20) - copy of action.verb
- `stage`: CharField(32) blank - copy of action.stage
- `scope_ct`: ForeignKey(ContentType, PROTECT) - copy of action.scope

**Metadata:**
- `at`: DateTimeField auto_now_add - when signature created
- `note`: CharField(240) blank - optional note/reason
- `payload`: JSONField nullable - additional structured data
- `ip_address`: GenericIPAddressField nullable - IP from which signature created (audit)

**Cryptographic Attestation:**
- `signature_id`: CharField(64) indexed editable=False - HMAC-SHA256 hex digest

**Constraints:**

UniqueConstraint (for non-repeatable actions):
- Fields: (content_type, object_id, verb, stage)
- Condition: is_repeatable=False
- Name: uq_sig_nonrepeat_per_object_verb_stage

**Indexes:**
- (at), (-at) - temporal queries
- (content_type, object_id) - target lookups
- (verb, stage) - action type queries
- (content_type, object_id, verb, stage) - composite workflow queries

**Ordering:** (-at, -id) - newest first

**Methods:**

```python
def clean(self)
```
Validates action.scope matches signature scope_ct.

```python
def save(self, *args, **kwargs)
```
On first save:
1. Snapshots action fields: verb, stage, scope_ct, is_repeatable
2. Computes HMAC signature_id:

```python
msg = f"{verb}|{stage or ''}|{content_type_id}|{object_id}".encode("utf-8")
key = f"{settings.HANKOSIGN_SECRET}:{signatory.base_key}".encode("utf-8")
signature_id = hmac.new(key, msg, hashlib.sha256).hexdigest()
```

**History:** simple_history tracked

**CRUD Policy:**
- No add (use utils.record_signature)
- No change (immutable)
- No delete (audit trail preservation)

**String Representation:**
```
APPROVE/WIREF on finances.paymentplan#123
```

---

## 3. Core Utilities (utils.py)

### 3.1 Signatory Resolution

```python
def resolve_signatory(user: User) -> Optional[Signatory]
```

**Purpose:** Find active Signatory for authenticated Django user.

**Logic:**
1. Requires authenticated user
2. Filters Signatory by:
   - is_active=True
   - person_role.person.user = user
3. Orders by -updated_at
4. Returns first match or None

**Used By:** All authorization functions

---

### 3.2 Action Resolution

```python
def get_action(action_ref: Union[str, Action]) -> Optional[Action]
```

**Purpose:** Resolve Action from instance or code string.

**Input Formats:**
- Action instance → returns as-is
- String code: `VERB:STAGE@app_label.model`
  - Example: `APPROVE:WIREF@finances.paymentplan`
  - Stage `-` treated as empty string

**Returns:** Action or None

**Error Handling:** Returns None on any parse/lookup failure

---

### 3.3 Authorization Check

```python
def can_act(
    user: User,
    action_ref: Union[str, Action],
    obj,
) -> Tuple[bool, Optional[str], Optional[Signatory], Optional[Action], Optional[Policy]]
```

**Purpose:** Comprehensive authorization check before signature.

**Returns:** (ok, reason, signatory, action, policy)

**Validation Steps:**

1. **Action exists:** Resolve action_ref
2. **Signatory exists:** User has active Signatory via resolve_signatory()
3. **Signatory verified:** is_verified=True (specimen on file)
4. **Policy exists:** Role has Policy granting this action
   - Prefers exact FK match over M2M
   - Orders by: direct FK (priority 1), then -updated_at
5. **Separation of duties:** If action.require_distinct_signer=True:
   - Checks for prior signatures on same object & scope
   - Blocks if this signatory already signed any stage in this scope

**Error Messages:**
- "Unknown action."
- "No active signatory is linked to your account."
- "Your signatory is not verified (specimen missing)."
- "You are not authorized to perform this action."
- "A different signatory is required for this stage."

---

### 3.4 Record Signature

```python
def record_signature(
    request,
    user: User,
    action_ref: Union[str, Action],
    obj,
    *,
    note: str = "",
    payload=None,
) -> Signature
```

**Purpose:** Create signature after authorization check (atomic).

**Process:**

1. **Authorization:** Calls can_act(), raises PermissionDenied if failed
2. **Repeatability check (non-repeatable actions):**
   - Atomic query with select_for_update()
   - Blocks if signature already exists for (content_type, object_id, verb, stage)
   - Raises PermissionDenied: "This action has already been performed."
3. **Soft dedupe window (10 seconds):**
   - Prevents double-clicks
   - Same signatory, same verb/stage/object within 10s → returns existing signature (no-op)
4. **IP extraction:**
   - Tries HTTP_X_FORWARDED_FOR first (proxy-aware)
   - Falls back to REMOTE_ADDR
   - Splits comma-separated X-Forwarded-For, takes first
5. **Signature creation:** Atomic Signature.objects.create()
6. **Logging:** logs to `unihanko.hankosign` logger

**Returns:** Created Signature (or existing if within dedupe window)

**Raises:** PermissionDenied with localized message

---

### 3.5 Idempotent Signing (GET-safe)

```python
def sign_once(
    request,
    action_ref: Union[str, Action],
    obj,
    *,
    note: str = "",
    payload=None,
    window_seconds: int = 10,
) -> Optional[Signature]
```

**Purpose:** Idempotent signature for GET-able actions (like PDF print).

**Mechanism:**
1. **Authorization:** Calls can_act()
2. **Cache key generation:**
```python
key = f"hs:once:{verb}:{stage or '-'}@{scope_id}:{user_id}:{ct_id}:{obj_pk}:{rid or 'no-rid'}"
```
3. **Cache gate:** cache.add(key, 1, window_seconds)
   - First hit → calls record_signature()
   - Subsequent hits → returns latest existing signature (no-op)

**Returns:** Signature (created or existing)

**Use Case:** PDF print actions that must be idempotent for page refreshes.

**Requires:** Request ID (rid) for per-click uniqueness (see RID_JS helper).

---

### 3.6 Request ID Helpers

**RID_JS:**

JavaScript snippet to append unique rid parameter on link click:

```javascript
this.href = this.href + (this.href.indexOf('?')>-1?'&':'?') + 
'rid=' + (Date.now().toString(36) + Math.random().toString(36).slice(2));
```

Usage in admin actions:
```python
print_action.attrs = {
    "onclick": RID_JS,
}
```

**get_rid():**

```python
def get_rid(request) -> Optional[str]
```

Extracts rid from request.GET, returns None if missing/empty.

---

### 3.7 State Snapshot

```python
def state_snapshot(obj) -> dict
```

**Purpose:** Compute current workflow state from signatures.

**Returns:**

```python
{
    "submitted": bool,        # SUBMIT exists and no later WITHDRAW
    "approved": set[str],     # Stages with APPROVE signatures
    "rejected": bool,         # ANY REJECT signature exists
    "required": set[str],     # Stages required by Action config
    "final": bool,            # All required approvals present
    "locked": bool,           # Simple lock (submitted or approved or final)
    "explicit_locked": bool,  # LOCK exists and no later UNLOCK
}
```

**Logic:**

1. **submitted:** last SUBMIT > last WITHDRAW (or no WITHDRAW)
2. **explicit_locked:** last LOCK > last UNLOCK (or no UNLOCK)
3. **approved:** Set of stages with APPROVE signatures (excludes empty stage)
4. **rejected:** ANY REJECT signature exists (boolean, stage-agnostic)
5. **required:** Stages from Action config (verb=APPROVE, scope=obj's model)
6. **final:** required ⊆ approved (all required approvals obtained)
7. **locked:** explicit_locked OR submitted OR approved OR final

**Use Case:** Query current state without domain-specific logic.

---

### 3.8 Object Status (Normalized)

```python
def object_status(obj, *, final_stage="CHAIR", tier1_stage="WIREF") -> dict
```

**Purpose:** Normalized status for any HankoSign-driven object.

**Priority (highest → lowest):**
1. Explicit locked
2. Rejected (any stage)
3. Final approved
4. Tier1 approved
5. Submitted
6. Draft

**Returns:**

```python
{
    "code": str,  # stable for CSS/data-state
    "label": str  # localized display
}
```

**Codes:**
- `draft` - No submission
- `submitted` - Submitted, awaiting approval
- `approved-tier1` - First tier approved (e.g., WIREF)
- `final` - Final stage approved (e.g., CHAIR)
- `rejected` - Rejected at any stage
- `locked` - Explicitly locked (year-end close, etc.)

**Labels:** Localized via gettext

---

### 3.9 Object Status Span (Admin Helper)

```python
def object_status_span(obj, *, final_stage="CHAIR", tier1_stage="WIREF")
```

**Purpose:** Admin list column helper - emits HTML span with data-state.

**Output:**
```html
<span class="js-state" data-state="final">Final</span>
```

**CSS Targeting:**
```css
.js-state[data-state="draft"] { color: gray; }
.js-state[data-state="submitted"] { color: orange; }
.js-state[data-state="approved-tier1"] { color: blue; }
.js-state[data-state="final"] { color: green; }
.js-state[data-state="rejected"] { color: red; }
.js-state[data-state="locked"] { color: darkred; }
```

---

### 3.10 Signature Queries

**has_sig():**

```python
def has_sig(obj, verb: str, stage: str) -> bool
```

Check if signature exists for (obj, verb, stage).

**sig_time():**

```python
def sig_time(obj, verb: str, stage: str) -> Optional[datetime]
```

Get timestamp of first signature for (obj, verb, stage).

**_last():**

```python
def _last(obj, verb: str, stages: set[str] | None = None) -> Optional[datetime]
```

Get timestamp of last signature for verb, optionally filtered by stages.

**_stages():**

```python
def _stages(obj, verb: str) -> set[str]
```

Get set of stages that have signatures for this verb (excludes empty stage).

---

### 3.11 Render Signatures Box

```python
def render_signatures_box(obj)
```

**Purpose:** Admin widget showing signature audit trail.

**Template:** `hankosign/signature_box.html`

**Context:**
```python
{
    "has_rows": bool,
    "rows": [
        {
            "verb": str,
            "stage": str,
            "code": str,          # "VERB/STAGE"
            "when": datetime,
            "who": str,           # signatory display name
            "sig_id_short": str,  # first 12 chars of HMAC
            "sig_id": str,        # full HMAC
            "note": str,
        },
        ...
    ],
    "title": "HankoSign Workflow Control",
}
```

**Ordering:** Chronological (at, id)

**Returns:** mark_safe HTML or "— save first to see signatures —"

---

### 3.12 PDF Attestation Seal

```python
def seal_signatures_context(obj, *, tz=None) -> list[dict]
```

**Purpose:** Signature data for PDF attestation seals.

**Returns:**

```python
[
    {
        "who": str,           # signatory display name
        "action": str,        # "VERB/STAGE"
        "when": str,          # YYYY-MM-DD HH:MM
        "sig_id_short": str,  # first 12 chars
    },
    ...
]
```

**Ordering:** Chronological

**Use Case:** Include in PDF context for tamper-evident attestation section.

---

### 3.13 Action Display Labels

**_ACTION_LABELS:**

Mapping of (verb, stage) → human labels for common actions:

```python
{
    ("SUBMIT",   "ASS"):   "Submit",
    ("WITHDRAW", "ASS"):   "Withdraw",
    ("APPROVE",  "WIREF"): "Approve (WiRef)",
    ("REJECT",   "WIREF"): "Reject (WiRef)",
    ("APPROVE",  "CHAIR"): "Approve (Chair)",
    ("REJECT",   "CHAIR"): "Reject (Chair)",
    ("LOCK",     ""):      "Lock",
    ("UNLOCK",   ""):      "Unlock",
    ("SUBMIT",   "WIREF"): "Submit (WiRef)",
    ("VERIFY",   "WIREF"): "Verify banking",
    ("REJECT",   ""):      "Cancel/Terminate",
    ("RELEASE",  ""):      "Print/Release",
}
```

**action_display():**

```python
def action_display(sig: Signature) -> str
```

Returns human label for signature, falls back to titlecased format.

**_short_sig_id():**

```python
def _short_sig_id(sig: Signature) -> str
```

Returns last 8 hex chars of signature_id formatted as XXXX-XXXX.

---

## 4. Admin Interface

### 4.1 Action Admin

**Registration:** `@admin.register(Action)`

**List Display:**
- human_label, verb, stage, scope, is_repeatable, require_distinct_signer, action_code, updated_at

**Filters:**
- verb, stage, scope, is_repeatable, require_distinct_signer

**Search:**
- human_label

**Readonly:**
- created_at, updated_at

**Readonly After Creation:**
- verb, stage, scope (identity immutable)

**Fieldsets:**

1. **Definition:** verb, stage, scope, human_label, comment
2. **Behavior:** is_repeatable, require_distinct_signer
3. **System:** created_at, updated_at

**Permissions:**
- No delete (immutable action definitions)

**History:** simple_history tracked

---

### 4.2 Policy Admin

**Registration:** `@admin.register(Policy)`

**Form:** `PolicyAdminForm`

Custom validation:
- Ensures either FK action OR M2M actions (not both, not neither)
- Passes M2M IDs to model via set_pending_actions()

**List Display:**
- role, actions_display, actions_count, updated_at

**Filters:**
- actions__verb, actions__stage, actions__scope

**Search:**
- role__name, action__human_label, actions__human_label

**Autocomplete:**
- role, action

**Filter Horizontal:**
- actions (M2M widget)

**Fieldsets:**

1. **Grant:** role, action, actions
2. **Notes:** notes
3. **System:** created_at, updated_at

**Computed Displays:**

```python
@admin.display
def actions_display(obj)
```
Shows comma-separated action labels from M2M or FK.

```python
@admin.display
def actions_count(obj)
```
Shows M2M actions count.

**Readonly After Creation:**
- role, action (FK action immutable, M2M actions editable)

**Permissions:**
- No delete (immutable policy grants)

**Queryset Optimization:**
- Prefetches actions, selects role + action

**History:** simple_history tracked

---

### 4.3 Signatory Admin

**Registration:** `@admin.register(Signatory)`

**List Display:**
- display_name, user_display, person_role, verified_text, updated_at, active_text

**Filters:**
- is_active, is_verified, person_role__role

**Search:**
- person_role person names, user username

**Autocomplete:**
- person_role

**Readonly:**
- created_at, updated_at, base_key, user_display

**Readonly After Creation:**
- person_role (scope immutable)

**Fieldsets:**

1. **Scope:** person_role, user_display, name_override
2. **Status:** is_active, is_verified, pdf_specimen
3. **System:** base_key, created_at, updated_at

**Inline:**
- SignatureInline (paginated, per_page=10, readonly, no add/delete)

**Object Actions:**
- print_specimen

**Computed Displays:**

```python
@admin.display
def active_text(obj)
```
Returns boolean status span: Active (green) / Inactive (gray).

```python
@admin.display
def verified_text(obj)
```
Returns "OK" if is_verified, else "NOT OK".

```python
@admin.display
def user_display(obj)
```
Returns user.username or "—".

**Row Attributes:**
- data-state based on is_active (for CSS targeting)

**Object Action:**

```python
@safe_admin_action
def print_specimen(request, obj)
```
- Template: hankosign/specimen_pdf.html
- Filename: `SPECIMEN_{lastname}_{date}.pdf`
- Context: signatory, person, role, person_role, org, date
- No HankoSign tracking (blank form)

**Permissions:**
- No delete (audit trail preservation)

**History:** simple_history tracked

---

### 4.4 Signature Admin

**Registration:** `@admin.register(Signature)`

**List Display:**
- at, signatory, verb, stage, content_type, object_id, signature_id

**Filters:**
- verb, stage, content_type

**Search:**
- signature_id, object_id, signatory names

**All Readonly:**
- signatory, content_type, object_id, action, verb, stage, scope_ct, at, note, payload, signature_id, ip_address

**Fieldsets:**

1. **Target:** content_type, object_id
2. **Action:** action, verb, stage, scope_ct
3. **Signer:** signatory
4. **Result:** signature_id, at, note, payload, ip_address

**Permissions:**
- No add (use utils.record_signature)
- No change (immutable audit log)
- No delete (permanent record)

**Visibility:**
- Hidden from sidebar for non-superusers
- Superusers: full read-only access

**History:** simple_history tracked

---

### 4.5 SignatureInline

**Usage:** Embedded in Signatory admin

**Type:** StackedInlinePaginated

**Config:**
- per_page: 10
- pagination_key: "signature"
- can_delete: False
- No add permission

**Fields (readonly):**
- at, verb, stage, content_type, object_id, signature_id, note, ip_address

**Ordering:** -at (newest first)

---

## 5. Workflow Patterns

### 5.1 Standard Assembly Workflow

**Actions:**
```
SUBMIT:ASS@assembly.resolution
APPROVE:WIREF@assembly.resolution
APPROVE:CHAIR@assembly.resolution
```

**Flow:**
1. Draft → Submit (ASS) → Submitted
2. Approve (WiRef) → Approved (Tier1)
3. Approve (Chair) → Final

**States:**
- draft → submitted → approved-tier1 → final

---

### 5.2 Finance Payment Plan Workflow

**Actions:**
```
SUBMIT:WIREF@finances.paymentplan
WITHDRAW:WIREF@finances.paymentplan
APPROVE:WIREF@finances.paymentplan
APPROVE:CHAIR@finances.paymentplan
VERIFY:WIREF@finances.paymentplan
REJECT:-@finances.paymentplan
```

**Flow:**
1. Draft → Submit (WiRef) → Pending
2. Withdraw (WiRef) → Draft (before approvals)
3. Approve (WiRef) → Pending (awaiting Chair)
4. Approve (Chair) → Pending (awaiting banking)
5. Verify (WiRef - banking) → Active
6. Reject (no stage) → Cancelled (terminal)

**Status Computed:** Module-specific paymentplan_status() function

---

### 5.3 Year-End Lock Pattern

**Actions:**
```
LOCK:-@finances.fiscalyear
UNLOCK:-@finances.fiscalyear
```

**Flow:**
1. Open year → Lock → Locked (cascades to all plans)
2. Locked year → Unlock → Open

**Effect:** FiscalYear lock cascades readonly to all PaymentPlans.

---

### 5.4 Print/Release Pattern

**Actions:**
```
RELEASE:-@employees.timesheet
RELEASE:-@finances.paymentplan
```

**Behavior:**
- is_repeatable=True
- Uses sign_once() with 10s window
- Records each print event
- No workflow state change

**Use Case:** Audit trail for who printed/released PDFs.

---

## 6. Security Features

### 6.1 Cryptographic Signature

**Algorithm:** HMAC-SHA256

**Key Composition:**
```python
key = f"{settings.HANKOSIGN_SECRET}:{signatory.base_key}".encode("utf-8")
```

**Message:**
```python
msg = f"{verb}|{stage or ''}|{content_type_id}|{object_id}".encode("utf-8")
```

**Properties:**
- Unique per signatory (base_key)
- Unique per action (verb, stage)
- Unique per target (content_type, object_id)
- Cannot be forged without both keys
- Detects tampering (any message change invalidates)

---

### 6.2 Separation of Duties

**Mechanism:**
- `Action.require_distinct_signer=True`
- Enforced by can_act()

**Logic:**
1. Checks for prior signatures by same signatory
2. Same object, same scope (any verb/stage)
3. Blocks if signatory already signed any earlier stage

**Use Case:** Prevent single person approving all stages (e.g., WIREF + CHAIR).

---

### 6.3 Non-Repeatable Actions

**Mechanism:**
- `Action.is_repeatable=False` (default)
- UniqueConstraint on (content_type, object_id, verb, stage)
- Enforced by record_signature() with select_for_update()

**Effect:**
- Only one signature per (object, verb, stage)
- Prevents duplicate approvals

**Exception:** RELEASE actions typically repeatable for multiple prints.

---

### 6.4 Soft Dedupe (10s Window)

**Mechanism:**
- record_signature() checks for signatures within 10s
- Same signatory, same object, same verb/stage

**Effect:**
- Prevents double-clicks/refreshes
- Returns existing signature (no-op)
- No error thrown

---

### 6.5 Idempotency (sign_once)

**Mechanism:**
- Cache key: (user, obj, action, rid)
- cache.add() guarantees single execution per key
- window_seconds default=10

**Effect:**
- GET-able actions (PDF print) safe for refreshes
- Requires RID_JS onclick handler for per-click uniqueness

---

### 6.6 IP Address Logging

**Mechanism:**
- Extracts from HTTP_X_FORWARDED_FOR (proxy-aware)
- Falls back to REMOTE_ADDR
- Stored in Signature.ip_address

**Use Case:**
- Audit trail
- Geolocation analysis
- Fraud detection

---

## 7. Configuration Requirements

### 7.1 Django Settings

**HANKOSIGN_SECRET:**
```python
HANKOSIGN_SECRET = "your-secret-key-here"  # Required
```

**Purpose:** Master secret for HMAC computation.

**Security:**
- Keep secret (do not commit to version control)
- Rotate if compromised (invalidates all signature_id values)
- Use strong random value (32+ hex chars)

**Cache Backend:**
```python
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": "redis://127.0.0.1:6379/1",
    }
}
```

**Purpose:** Required for sign_once() idempotency.

---

### 7.2 Bootstrap Requirements

**Actions:** Must be created before workflows can run.

**Typical Bootstrap:**
```bash
python manage.py bootstrap_actions
```

**Policies:** Must map roles to actions for authorization.

**Typical Bootstrap:**
```bash
python manage.py bootstrap_acls
```

**Signatories:** Must be created for PersonRoles that need signing authority.

**Manual Creation:** Via admin or bootstrap script.

---

## 8. Testing

**Test File:** hankosign/tests.py (comprehensive test suite)

**Test Mixin:** `HankoSignTestMixin`

**Test Coverage:**
- Action creation and uniqueness
- Policy validation (FK vs M2M)
- Signatory resolution
- can_act() authorization logic
- record_signature() atomicity
- Separation of duties enforcement
- Non-repeatable action enforcement
- Soft dedupe window
- state_snapshot() accuracy
- object_status() priority logic

**Test Types:**
- Unit tests for individual functions
- Integration tests for workflows
- Concurrency tests for race conditions (TransactionTestCase)

---

## 9. Dependencies

**Django Framework:**
- ContentType framework (generic foreign keys)
- Django cache (for sign_once idempotency)
- Django auth (User model)

**Internal Modules:**
- people (Person, Role, PersonRole)
- organisation (OrgInfo for PDFs)
- core.admin_mixins (safe actions, guards)
- core.pdf (PDF generation)
- core.utils.bool_admin_status (status badges)

**External Packages:**
- simple_history - model history tracking
- django_object_actions - admin object actions
- django_admin_inline_paginator_plus - paginated inlines

**Python Standard Library:**
- hmac, hashlib (cryptographic signatures)
- secrets (random key generation)

---

## 10. Notes

**Immutability:**
- Actions, Policies, Signatures are immutable once created
- No delete permissions (audit trail preservation)
- Readonly after creation for identity fields

**Audit Trail:**
- All signatures permanently recorded
- simple_history tracks all model changes
- IP addresses logged
- Timestamps with timezone

**Stage Naming:**
- Uppercase convention: WIREF, CHAIR, ASS
- Empty string for stage-less actions
- Display as `-` in action codes

**Action Code Format:**
- VERB:STAGE@app_label.model
- VERB:-@app_label.model (empty stage)
- Used in get_action() and throughout codebase

**Workflow Lock Logic:**
- locked = submitted OR approved OR final OR explicit_locked
- Simple rule: any forward progress locks basic editing
- explicit_locked = LOCK signature exists (and no later UNLOCK)

**Performance:**
- Indexes on common query patterns
- select_related/prefetch_related in admin querysets
- Cache for idempotency (sign_once)
- Atomic operations for concurrency

---

## 11. File Structure

```
hankosign/
├── __init__.py
├── apps.py                           # Standard config
├── models.py                         # 303 lines
│   ├── Action (verb/stage/scope)
│   ├── Policy (role → actions)
│   ├── Signatory (person capability)
│   └── Signature (immutable record)
├── utils.py                          # 527 lines
│   ├── resolve_signatory()
│   ├── get_action()
│   ├── can_act()
│   ├── record_signature()
│   ├── sign_once()
│   ├── state_snapshot()
│   ├── object_status()
│   ├── render_signatures_box()
│   ├── seal_signatures_context()
│   └── query helpers
├── admin.py                          # 237 lines
│   ├── ActionAdmin
│   ├── PolicyAdmin (+ form)
│   ├── SignatoryAdmin
│   ├── SignatureAdmin
│   └── SignatureInline
├── tests.py                          # Test suite
└── views.py                          # Empty placeholder
```

Total lines: ~1,067 (excluding tests)

---

**Version:** 1.0.5  
**Last Updated:** 2025-12-08  
**Author:** Sven (vas)