# Assembly Module

## 1. Overview

The Assembly module manages the Hochschulvertretung (HV) - the university's representative assembly. It tracks legislative terms, assembly composition (seats/mandates), sessions (meetings), agenda items, voting records, and attendance.

**Key Responsibilities:**
- Manage legislative terms (Funktionsperioden)
- Track assembly composition with 9 mandate positions
- Record session meetings with agenda items
- Track attendance (primary mandatary or backup)
- Handle voting (counted and named votes)
- Manage election items for special roles
- Generate session protocols and dispatch documents

**Dependencies:**
- `people` - PersonRole for mandate holders
- `hankosign` - Signature workflow for session approval
- `annotations` - Commenting on sessions and items
- `organisation` - OrgInfo for PDF generation
- `tinymce` - Rich text editing for item content

---

## 2. Models

### 2.1 Term

Legislative term / Funktionsperiode.

**Purpose:** Defines the timeframe for an assembly term, typically 2 years.

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `code` | CharField(20) | Auto-generated format: `HV25_27` (editable=False, unique) |
| `label` | CharField(100) | Display name |
| `start_date` | DateField | Term start date |
| `end_date` | DateField | Term end date (auto-set to +2 years if empty) |
| `is_active` | BooleanField | Whether this is the active term (default: False) |
| `created_at` | DateTimeField | Creation timestamp (auto) |
| `updated_at` | DateTimeField | Last update timestamp (auto) |

**Constraints:**
- `code` is unique
- `end_date` >= `start_date` (validation)

**Code Generation:**

```python
def generate_code(self):
    """Generate HV25_27 from start_date and end_date"""
    y1 = self.start_date.year % 100
    
    if self.end_date:
        y2 = self.end_date.year % 100
    else:
        y2 = (self.start_date.year + 2) % 100
    
    return f"HV{y1:02d}_{y2:02d}"
```

**Auto-generation on save:**
- If `code` is empty, calls `generate_code()`
- If `end_date` is empty, sets to `start_date + 2 years`

**Lock Mechanism:**
- Locked via HankoSign `LOCK:-@assembly.term` signature
- When locked, only `updated_at` can be modified
- Lock is checked via `state_snapshot(obj).get("explicit_locked")`

**Ordering:**
- Default: `-start_date` (newest first)

---

### 2.2 Composition

Container for all mandates in a term.

**Purpose:** Groups all 9 mandate positions for a specific term.

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `term` | OneToOneField(Term) | Parent term (PROTECT, related_name: `composition`) |
| `created_at` | DateTimeField | Creation timestamp (auto) |
| `updated_at` | DateTimeField | Last update timestamp (auto) |

**Relationships:**
- OneToOne with Term
- Has many Mandate objects (related_name: `mandates`)

**Methods:**

```python
def active_mandates_count(self):
    """Count currently active mandates"""
    return self.mandates.filter(end_date__isnull=True).count()
```

**Constraints:**
- OneToOne with Term (one composition per term)
- Max 9 active mandates (validation)

---

### 2.3 Mandate

Individual seat holder - can change during term.

**Purpose:** Represents one of the 9 assembly positions, tracking who holds it and when.

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `composition` | FK(Composition) | Parent composition (CASCADE) |
| `position` | PositiveSmallIntegerField | Seat number (1-9) |
| `person_role` | FK(PersonRole) | Person holding this mandate (PROTECT) |
| `officer_role` | CharField(5) | Role type (see enum below) |
| `start_date` | DateField | When mandate started |
| `end_date` | DateField | When mandate ended (null = active) |
| `backup_person_role` | FK(PersonRole) | Backup person in system (nullable, SET_NULL) |
| `backup_person_text` | CharField(200) | Backup person external name (blank) |
| `party` | CharField(100) | Party affiliation (e.g., VSSTÖ, AG, GRAS) |
| `notes` | TextField | Additional notes (blank) |

**OfficerRole Enum:**

```python
class OfficerRole(models.TextChoices):
    CHAIR = "CHAIR", "Vorsitzende/r"
    DEPUTY_1 = "DEP1", "1. Stellvertretung"
    DEPUTY_2 = "DEP2", "2. Stellvertretung"
    MEMBER = "MEMB", "Mandatar/in"
```

**Constraints:**
- Position must be 1-9 (validation)
- `end_date` >= `start_date` (validation)

**Properties:**

```python
@property
def is_active(self):
    """Is this mandate currently active?"""
    return self.end_date is None
```

**Indexes:**
- `(composition, position)`
- `officer_role`
- `(start_date, end_date)`

**Ordering:**
- Default: `position`, `-start_date`

**String Representation:**

```
"Position 3 — {PersonRole} (active)"
"Position 5 — {PersonRole} (ended)"
```

---

### 2.4 Session

Individual HV meeting / Sitzung.

**Purpose:** Represents one assembly meeting with agenda items, attendance, and workflow status.

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `term` | FK(Term) | Parent term (PROTECT) |
| `code` | CharField(30) | Auto-generated format: `HV25_27_I:or` (unique, editable=False) |
| `session_type` | CharField(2) | Type (see enum below) |
| `status` | CharField(20) | Workflow status (auto-computed, indexed) |
| `session_date` | DateField | Meeting date |
| `session_time` | TimeField | Meeting time (nullable) |
| `location` | CharField(200) | Meeting location (blank) |
| `protocol_number` | CharField(50) | Protocol number (blank) |
| `attendees` | M2M(Mandate) | Through SessionAttendance |
| `absent` | M2M(Mandate) | Absent mandates |
| `other_attendees` | TextField | External guests (blank) |
| `invitations_sent_at` | DateTimeField | Timestamp (nullable) |
| `minutes_finalized_at` | DateTimeField | Timestamp (nullable) |
| `sent_koko_hsg_at` | DateTimeField | When sent to committees (nullable) |

**Type Enum:**

```python
class Type(models.TextChoices):
    REGULAR = "or", "Ordentlich"
    EXTRAORDINARY = "ao", "Außerordentlich"
```

**Status Enum:**

```python
class Status(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    APPROVED = "APPROVED", "Approved by Chair"
    VERIFIED = "VERIFIED", "Sent to KoKo/HSG"
    REJECTED = "REJECTED", "Rejected re-work"
```

**Code Generation:**

```python
def generate_code(self):
    """Generate HV25_27_I:or, HV25_27_II:ao, etc."""
    count = Session.objects.filter(term=self.term).count() + 1
    roman = int_to_roman(count)
    return f"{self.term.code}_{roman}:{self.session_type}"
```

**Status Computation:**

Status is auto-computed on save via `session_status()` function:

```python
def session_status(session) -> str:
    st = state_snapshot(session)
    
    # 1. Check for rejection
    if st.get("rejected"):
        return "REJECTED"
    
    # 2. Check if submitted
    if not st.get("submitted"):
        return "DRAFT"
    
    # 3. Check for Chair approval
    approved = st.get("approved", set())
    if "CHAIR" not in approved:
        return "SUBMITTED"
    
    # 4. Check for verification
    if not st.get("verified"):
        return "APPROVED"
    
    # 5. Everything done
    return "VERIFIED"
```

**Validation:**
- `session_date` must fall within term period
- Code uniqueness (defensive check)

**Indexes:**
- `(term, session_date)`
- `session_type`
- `-session_date`

**Ordering:**
- Default: `-session_date`, `code`

**Properties:**

```python
@property
def full_display_code(self):
    """For admin display"""
    return self.code
```

---

### 2.5 SessionAttendance

Through model tracking who actually attended.

**Purpose:** Tracks whether primary mandatary or backup attended the session.

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `session` | FK(Session) | Session (CASCADE) |
| `mandate` | FK(Mandate) | Mandate (PROTECT) |
| `backup_attended` | BooleanField | True if backup attended (default: False) |
| `created_at` | DateTimeField | Timestamp (auto) |

**Constraints:**
- Unique constraint: `(session, mandate)`

**Ordering:**
- Default: `mandate__position`

**String Representation:**

```
"{Mandate} (Backup) @ {session.code}"
"{Mandate} (Primary) @ {session.code}"
```

---

### 2.6 SessionItem

Agenda item / Tagesordnungspunkt.

**Purpose:** Individual item on session agenda with content, voting, and election tracking.

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `session` | FK(Session) | Parent session (CASCADE) |
| `item_code` | CharField(10) | Auto-generated: `S001`, `S002` (editable=False) |
| `order` | PositiveSmallIntegerField | Position in agenda |
| `kind` | CharField(10) | Item type (see enum below) |
| `title` | CharField(300) | Item title |
| `content` | TextField | For PROCEDURAL items (blank) |
| `subject` | HTMLField | For RESOLUTION/ELECTION (blank) |
| `discussion` | HTMLField | For RESOLUTION/ELECTION (blank) |
| `outcome` | HTMLField | For RESOLUTION/ELECTION (blank) |
| `voting_mode` | CharField(10) | Voting type (see enum below, default: NONE) |
| `votes_for` | PositiveSmallIntegerField | Count (nullable) |
| `votes_against` | PositiveSmallIntegerField | Count (nullable) |
| `votes_abstain` | PositiveSmallIntegerField | Count (nullable) |
| `passed` | BooleanField | Result (nullable) |
| `elected_person_role` | FK(PersonRole) | For ELECTION kind (nullable, PROTECT) |
| `elected_person_text_reference` | CharField(200) | Temporary person reference (blank) |
| `elected_role_text_reference` | CharField(200) | Temporary role reference (blank) |
| `notes` | TextField | Internal notes (blank) |

**Kind Enum:**

```python
class Kind(models.TextChoices):
    RESOLUTION = "RES", "Beschluss"
    PROCEDURAL = "PROC", "Ablaufinformation"
    ELECTION = "ELEC", "Beschluss iSe Personalwahl"
```

**VotingMode Enum:**

```python
class VotingMode(models.TextChoices):
    NONE = "NONE", "Keine Abstimmung"
    COUNTED = "COUNT", "Stimmenzählung"
    NAMED = "NAMED", "Namentliche Abstimmung"
```

**Item Code Generation:**

```python
# In save()
if not self.item_code:
    for attempt in range(5):
        try:
            with transaction.atomic():
                count = SessionItem.objects.filter(session=self.session).count() + 1
                self.item_code = f"S{count:03d}"
                super().save(*args, **kwargs)
                break
        except IntegrityError:
            if attempt == 4:
                raise ValidationError("Failed to generate unique item code")
            continue
```

**Election Integration:**

On save, if item is ELECTION type and session is APPROVED or VERIFIED:

```python
if (self.kind == self.Kind.ELECTION and 
    self.elected_person_role_id and
    self.session.status in (Session.Status.APPROVED, Session.Status.VERIFIED)):
    pr = self.elected_person_role
    pr.elected_via = self
    if self.session.session_date:
        pr.confirm_date = self.session.session_date
    pr.save(update_fields=['elected_via', 'confirm_date'])
```

**Properties:**

```python
@property
def full_identifier(self):
    """HV25_27_III:ao-S001"""
    return f"{self.session.code}-{self.item_code}"
```

**Constraints:**
- Unique: `(session, order)`
- For COUNTED voting, all vote fields must be filled (validation)

**Indexes:**
- `(session, order)`
- `kind`
- `voting_mode`

**Ordering:**
- Default: `session`, `order`

---

### 2.7 Vote

Named voting record (namentliche Abstimmung).

**Purpose:** Records individual mandate's vote in named voting.

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `item` | FK(SessionItem) | Parent item (CASCADE) |
| `mandate` | FK(Mandate) | Mandate voting (PROTECT) |
| `vote` | CharField(10) | Vote choice (see enum below) |
| `created_at` | DateTimeField | Timestamp (auto) |

**Choice Enum:**

```python
class Choice(models.TextChoices):
    FOR = "FOR", "Ja"
    AGAINST = "AGAINST", "Nein"
    ABSTAIN = "ABSTAIN", "Enthaltung"
```

**Constraints:**
- Unique: `(item, mandate)` - one vote per mandate per item

**String Representation:**

```
"{Mandate} — {Vote display}"
```

---

## 3. Utility Functions

### 3.1 int_to_roman

```python
def int_to_roman(num):
    """Convert 1-50 to Roman numerals"""
```

**Range:** 1-50 only (raises ValueError outside range)

**Examples:**

```python
int_to_roman(1)   # "I"
int_to_roman(3)   # "III"
int_to_roman(4)   # "IV"
int_to_roman(9)   # "IX"
int_to_roman(10)  # "X"
int_to_roman(40)  # "XL"
int_to_roman(50)  # "L"
```

Used for generating session codes: `HV25_27_I:or`, `HV25_27_II:ao`, etc.

---

### 3.2 session_status

```python
def session_status(session) -> str:
    """
    Determine Session workflow status from HankoSign signatures.
    Returns: DRAFT | SUBMITTED | APPROVED | VERIFIED | REJECTED
    """
```

**Logic Flow:**

1. Check `rejected` → `"REJECTED"`
2. Check `submitted` → if not, `"DRAFT"`
3. Check `approved["CHAIR"]` → if not, `"SUBMITTED"`
4. Check `verified` → if not, `"APPROVED"`
5. All done → `"VERIFIED"`

Called automatically on Session save to update `status` field.

---

## 4. Admin Features

### 4.1 TermAdmin

**List Display:**
- Code, label, dates, is_active flag
- Last updated
- Lock status

**Object Actions:**

| Action | Permission | Behavior |
|--------|-----------|----------|
| `lock_term` | Assembly manager | Records `LOCK:-@assembly.term` signature |
| `unlock_term` | Assembly manager | Records `UNLOCK:-@assembly.term` signature |
| `print_term` | Any user | Generates PDF with `RELEASE:-` signature (10s window) |

**Readonly Logic:**
- After creation: `code` locked
- When locked: `label`, `start_date`, `end_date`, `is_active` locked

**Features:**
- Deletion disabled
- Annotation inline
- History tracking
- Optimistic locking

---

### 4.2 CompositionAdmin

**List Display:**
- Term
- Active mandates count (e.g., "7/9")
- Last updated

**Inlines:**
- MandateInline (stacked, paginated, 1 per page, max 9)

**Object Actions:**

| Action | Behavior |
|--------|----------|
| `print_composition` | Generates board roster PDF with `RELEASE:-` signature |

**Features:**
- Deletion disabled
- Mandate inline locked when parent term locked

---

### 4.3 MandateAdmin

**Purpose:** Hidden from sidebar, used for autocomplete only.

**List Display:**
- Position, person_role, officer_role, dates, composition

**Autocomplete:**
- Available for session attendance selection

**Permissions:**

```python
def get_model_perms(self, request):
    return {}  # Hidden from sidebar
```

---

### 4.4 SessionAdmin

**List Display:**
- Status badge
- Code, session date, type
- Location
- Last updated

**Inlines:**
- SessionAttendanceInline (stacked, paginated, 9 per page)
- ElectionItemHRLinksInline (stacked, paginated, 1 per page, ELEC items only)
- AnnotationInline

**Object Actions:**

| Action | Available When | Permission | Behavior |
|--------|---------------|-----------|----------|
| `submit_session` | DRAFT | Any staff | Records `SUBMIT:ASS@assembly.session` |
| `withdraw_session` | SUBMITTED | Any staff | Records `WITHDRAW:ASS@assembly.session` |
| `approve_session` | SUBMITTED | Manager | Records `APPROVE:CHAIR@assembly.session` |
| `reject_session` | SUBMITTED | Manager | Records `REJECT:CHAIR@assembly.session` |
| `verify_session` | APPROVED | Manager | Sets `sent_koko_hsg_at`, records `VERIFY:-@assembly.session` |
| `print_session` | Any | Any staff | Generates protocol PDF with `RELEASE:-` signature |
| `open_protocol_editor` | Any | Any staff | Redirects to PROTOKOL-KUN editor |

**Action Visibility Logic:**

```python
# DRAFT: Can only submit
if status == DRAFT:
    show: submit_session, print_session, open_protocol_editor
    
# SUBMITTED: Can approve/reject/withdraw
if status == SUBMITTED:
    show: approve_session, reject_session, withdraw_session, print_session, open_protocol_editor
    
# APPROVED: Can verify
if status == APPROVED:
    show: verify_session, print_session, open_protocol_editor
    
# VERIFIED/REJECTED: No workflow actions
if status in (VERIFIED, REJECTED):
    show: print_session, open_protocol_editor
```

**Lock Logic (_is_locked method):**

```python
def _is_locked(self, request, obj):
    if self._is_manager(request):
        return False  # Managers bypass lock
    return obj.status in (SUBMITTED, APPROVED, VERIFIED, REJECTED)
```

**Readonly Logic:**
- After creation: `term`, `session_type` locked
- When locked: `session_date`, `session_time`, `location`, `protocol_number`, `attendees`, `absent`, `other_attendees` locked

**Features:**
- Deletion disabled
- Status auto-computed on save
- Optimistic locking
- History tracking

---

### 4.5 SessionItemAdmin

**List Display:**
- Full identifier (e.g., `HV25_27_I:or-S001`)
- Session, kind, title, passed status
- Last updated

**Inlines:**
- VoteInline (for named voting, stacked, paginated, 10 per page)
- AnnotationInline

**Object Actions:**

| Action | Available For | Behavior |
|--------|--------------|----------|
| `print_dispatch_document` | ELECTION items with elected_person_role linked | Generates dispatch PDF with `RELEASE:-` signature |

**Form Behavior:**

`SessionItemAdminForm` conditionally shows/hides fields based on `kind`:

- **PROCEDURAL**: Shows `content`, hides `subject/discussion/outcome`
- **RESOLUTION/ELECTION**: Shows `subject/discussion/outcome`, hides `content`

**Lock Logic:**

Locked if parent session is locked:

```python
if obj.session_id:
    session_admin = self.admin_site._registry.get(Session)
    if session_admin and session_admin._is_locked(request, obj.session):
        # Lock all content fields
```

**Deletion Permission:**

```python
def has_delete_permission(self, request, obj=None):
    # Check if parent session is locked or chair-approved
    if "CHAIR" in st.get("approved", set()) or st.get("locked"):
        return False
    return super().has_delete_permission(request, obj)
```

**Features:**
- Hidden from sidebar for non-superusers
- Readonly after session locked
- No deletion after chair approval
- Optimistic locking

---

### 4.6 Inlines

#### MandateInline

- Stacked, paginated (1 per page)
- Max 9 mandates
- Locked when parent term locked
- Ordering by position

#### SessionAttendanceInline

- Stacked, paginated (9 per page)
- Fields: `mandate`, `backup_attended`
- Locked when parent session locked

#### ElectionItemHRLinksInline

- Shows only ELECTION kind items
- Fields: `item_code` (ro), `title` (ro), `print_dispatch_btn` (ro), `elected_person_role`, text references
- Can't add/delete via inline
- Managers can edit FK fields even after submission
- Has inline print button for dispatch document

#### VoteInline

- Stacked, paginated (10 per page)
- Fields: `mandate`, `vote`
- Locked when parent session locked

---

## 5. Views & PROTOKOL-KUN Editor

### 5.1 protocol_editor

**Endpoint:** `/assembly/protocol-editor/` or `/assembly/protocol-editor/<session_id>/`

**Purpose:** Main PROTOKOL-KUN editor interface for managing session items.

**Features:**
- Load session with items in order
- Display annotations per item
- Lock status checking
- List last 20 sessions for quick switching

**Lock Check:**

```python
is_locked = st.get('submitted', False) or st.get('locked', False) or 'CHAIR' in st.get('approved', set())
```

**Context:**

```python
{
    'session': session,
    'items': items,
    'annotations_by_item': {item_id: [annotations]},
    'all_sessions': Session.objects.all()[:20],
    'is_locked': is_locked,
}
```

---

### 5.2 AJAX Endpoints

All endpoints check lock status and block non-managers from editing locked sessions.

#### protocol_save_item

**Endpoints:**
- `POST /assembly/protocol-editor/<session_id>/save-item/` (create)
- `POST /assembly/protocol-editor/<session_id>/save-item/<item_id>/` (update)

**Behavior:**
- Creates or updates SessionItem
- Auto-assigns `order` if not provided (max + 1)
- For NAMED voting, clears and recreates Vote records from POST data

**Named Voting Handling:**

```python
if item.kind == SessionItem.Kind.RESOLUTION and item.voting_mode == SessionItem.VotingMode.NAMED:
    Vote.objects.filter(item=item).delete()
    
    for key, value in request.POST.items():
        if key.startswith('vote_') and value:
            mandate_id = key.replace('vote_', '')
            Vote.objects.create(item=item, mandate=mandate, vote=value)
```

**Response:**

```json
{
    "success": true,
    "item_id": 123,
    "item_code": "S001",
    "message": "Item saved successfully"
}
```

---

#### protocol_delete_item

**Endpoint:** `POST /assembly/protocol-editor/<session_id>/delete-item/<item_id>/`

**Behavior:**
- Deletes item
- Auto-renumbers remaining items (decrement order for items after deleted)

**Renumbering:**

```python
SessionItem.objects.filter(
    session=session,
    order__gt=deleted_order
).update(order=F('order') - 1)
```

---

#### protocol_reorder_items

**Endpoint:** `POST /assembly/protocol-editor/<session_id>/reorder-items/`

**Body:** JSON array of item IDs in new order

```json
[123, 125, 124, 126]
```

**Behavior:**
- Updates `order` field for each item based on array position

---

#### protocol_insert_at

**Endpoint:** `GET /assembly/protocol-editor/<session_id>/insert-at/<insert_after_order>/`

**Behavior:**
- Increments `order` for all items after `insert_after_order`
- Returns new order position for insertion

**Response:**

```json
{
    "success": true,
    "new_order": 5,
    "message": "Ready to insert item at position 5"
}
```

---

#### protocol_get_item

**Endpoint:** `GET /assembly/protocol-editor/<session_id>/get-item/<item_id>/`

**Behavior:**
- Returns item data as JSON for editing
- Includes named votes if applicable

**Response:**

```json
{
    "success": true,
    "item": {
        "id": 123,
        "kind": "RES",
        "title": "Budget Approval",
        "order": 5,
        "content": "",
        "subject": "<p>...</p>",
        "discussion": "<p>...</p>",
        "outcome": "<p>...</p>",
        "voting_mode": "NAMED",
        "votes_for": null,
        "votes_against": null,
        "votes_abstain": null,
        "passed": true,
        "elected_person_text_reference": "",
        "elected_role_text_reference": "",
        "notes": "",
        "named_votes": {
            "45": "FOR",
            "46": "AGAINST",
            "47": "ABSTAIN"
        }
    }
}
```

---

## 6. Forms

### 6.1 SessionItemProtocolForm

Form for PROTOKOL-KUN editor with conditional fields.

**Fields:**

All SessionItem fields are included:
- Scope: `kind`, `title`, `order`
- PROCEDURAL: `content`
- RESOLUTION/ELECTION: `subject`, `discussion`, `outcome`
- Voting: `voting_mode`, vote counts, `passed`
- Election: `elected_person_role`, text references
- Notes: `notes`

**Widgets:**
- `kind`, `voting_mode`: Select with Alpine.js bindings
- `content`, `notes`: Textarea
- `subject`, `discussion`, `outcome`: TinyMCE
- Vote counts: NumberInput
- `passed`: CheckboxInput

**Field Requirements:**

All conditional fields set to `required=False` (visibility handled client-side).

---

## 7. Workflows

### 7.1 Session Workflow

**State Progression:**

```
DRAFT → SUBMITTED → APPROVED → VERIFIED
          ↓
       REJECTED
```

**Actions:**

| From | Action | To | Signature |
|------|--------|-----|-----------|
| DRAFT | submit_session | SUBMITTED | `SUBMIT:ASS@assembly.session` |
| SUBMITTED | withdraw_session | DRAFT | `WITHDRAW:ASS@assembly.session` |
| SUBMITTED | approve_session | APPROVED | `APPROVE:CHAIR@assembly.session` |
| SUBMITTED | reject_session | REJECTED | `REJECT:CHAIR@assembly.session` |
| APPROVED | verify_session | VERIFIED | `VERIFY:-@assembly.session` |

**Verify Action Side Effects:**

```python
obj.sent_koko_hsg_at = timezone.now()
obj.save(update_fields=['sent_koko_hsg_at'])
```

**Lock Behavior:**

- Non-managers: Locked once SUBMITTED or beyond
- Managers: Never locked (bypass all locks)
- Locked sessions: Can't modify date, location, attendance, items

---

### 7.2 Term Lock Workflow

**Lock Action:**
- Records `LOCK:-@assembly.term` signature
- Locks term fields
- Cascades lock to child mandates via inline

**Unlock Action:**
- Records `UNLOCK:-@assembly.term` signature
- Removes lock

---

### 7.3 Election Item Integration

When SessionItem of ELECTION kind is saved with `elected_person_role` and session is APPROVED or VERIFIED:

```python
pr = self.elected_person_role
pr.elected_via = self  # Link back to this item
pr.confirm_date = self.session.session_date  # Set confirmation date
pr.save(update_fields=['elected_via', 'confirm_date'])
```

This links the PersonRole back to the election item for audit trail.

---

## 8. Management Commands

### 8.1 bootstrap_terms

**Purpose:** Create/update Terms from YAML config (idempotent).

**Usage:**

```bash
python manage.py bootstrap_terms
python manage.py bootstrap_terms --file config/terms.yaml
python manage.py bootstrap_terms --dry-run
```

**YAML Format:**

```yaml
terms:
  - label: "Hauptvertretung 2025-2027"
    start_date: "2025-07-01"
    end_date: "2027-06-30"
    is_active: true
    
  - label: "Hauptvertretung 2027-2029"
    start_date: "2027-07-01"
    end_date: "2029-06-30"
    is_active: false
```

**Code Auto-generation:**

```python
y1 = start_date.year % 100
y2 = end_date.year % 100 if end_date else (start_date.year + 2) % 100
code = f"HV{y1:02d}_{y2:02d}"
```

**Behavior:**
- Creates new terms that don't exist
- Updates existing terms if label/dates/is_active changed
- Skips unchanged terms
- Validates with `full_clean()` before saving

**Returns:**

```
✓ Bootstrap complete! 2 created, 1 updated, 0 unchanged.
```

---

## 9. Integration Points

### 9.1 people Module

**Dependency:** PersonRole

```python
from people.models import PersonRole
```

**Usage:**
- `Mandate.person_role` - who holds mandate
- `Mandate.backup_person_role` - backup person
- `SessionItem.elected_person_role` - person elected
- Election integration: Sets `PersonRole.elected_via` and `confirm_date`

---

### 9.2 hankosign Module

**Utilities Used:**

```python
from hankosign.utils import (
    state_snapshot,           # Get workflow state
    get_action,              # Get action config
    record_signature,        # Record signature
    sign_once,               # Windowed signature
    render_signatures_box,   # Admin display
    seal_signatures_context, # PDF context
    object_status_span,      # Status badge
)
```

**Signatures Used:**

| Action String | Model | Purpose |
|--------------|-------|---------|
| `LOCK:-@assembly.term` | Term | Lock term |
| `UNLOCK:-@assembly.term` | Term | Unlock term |
| `RELEASE:-@assembly.term` | Term | Print PDF |
| `RELEASE:-@assembly.composition` | Composition | Print roster |
| `SUBMIT:ASS@assembly.session` | Session | Submit session |
| `WITHDRAW:ASS@assembly.session` | Session | Withdraw submission |
| `APPROVE:CHAIR@assembly.session` | Session | Chair approval |
| `REJECT:CHAIR@assembly.session` | Session | Chair rejection |
| `VERIFY:-@assembly.session` | Session | Verify and send |
| `RELEASE:-@assembly.session` | Session | Print protocol |
| `RELEASE:-@assembly.sessionitem` | SessionItem | Print dispatch |

---

### 9.3 annotations Module

**Integration:**

```python
from annotations.admin import AnnotationInline
from annotations.views import create_system_annotation
```

**Usage:**
- All admins have AnnotationInline
- System annotations on workflow actions
- PROTOKOL-KUN loads annotations for items

---

### 9.4 organisation Module

**Dependency:** OrgInfo

```python
from organisation.models import OrgInfo
```

Used in PDF context for letterhead/contact info.

---

### 9.5 tinymce

**Integration:**

```python
from tinymce.models import HTMLField
from tinymce.widgets import TinyMCE
```

**Usage:**
- SessionItem rich text fields: `subject`, `discussion`, `outcome`
- SessionItemProtocolForm uses TinyMCE widgets

---

## 10. Gotchas & Important Notes

### 10.1 Status Auto-Computation

⚠️ **Session.status is auto-computed on save** via `session_status()` function. Never manually set status field.

If status seems wrong:
1. Check HankoSign signatures on session
2. Status derives from signatures, not the other way around

---

### 10.2 Lock Cascading

Term locks cascade to composition mandates via inline readonly logic, but don't directly lock sessions.

Session locks are independent and based on workflow status.

---

### 10.3 Code Generation Retry Logic

Both Session and SessionItem have retry logic (5 attempts) for code generation with IntegrityError handling.

If code collision happens 5 times, raises ValidationError.

---

### 10.4 Order Field Management

SessionItem `order` must be unique per session. PROTOKOL-KUN handles:
- Auto-assignment on create (max + 1)
- Auto-renumbering on delete
- Explicit reordering
- Insert-at logic (shift others)

Don't manually set order without considering duplicates.

---

### 10.5 Named Voting Workflow

For NAMED voting mode:
1. SessionItem has `voting_mode = NAMED`
2. Vote records created per mandate
3. On update via PROTOKOL-KUN, existing votes are deleted and recreated
4. Vote records cascade-delete with parent SessionItem

---

### 10.6 Election Item Text References

`elected_person_text_reference` and `elected_role_text_reference` are temporary placeholders.

Once linked to actual `elected_person_role`:
- Text references should be cleared
- Dispatch document can be generated
- PersonRole.elected_via is set on save

---

### 10.7 Attendance Tracking

Two separate fields:
- `Session.attendees` (M2M through SessionAttendance)
- `Session.absent` (direct M2M)

SessionAttendance tracks primary vs backup via `backup_attended` flag.

---

### 10.8 Manager Bypass

`is_assembly_manager()` users bypass all lock checks:
- Can edit locked sessions
- Can modify items after approval
- Can edit HR links after submission

Non-managers strictly respect locks.

---

### 10.9 Roman Numeral Limit

`int_to_roman()` only supports 1-50. Sessions beyond 50 in a term will raise ValueError.

This is intentional - HV terms typically have <50 sessions.

---

### 10.10 PROTOKOL-KUN Lock Checks

All AJAX endpoints independently check lock status:

```python
st = state_snapshot(session)
is_locked = (st.get('submitted') or st.get('explicit_locked') or 
             'CHAIR' in st.get('approved', set()))

if is_locked and not is_assembly_manager(request.user):
    return JsonResponse({'success': False, ...}, status=403)
```

Client-side lock display doesn't enforce security - server-side checks do.

---

## 11. Testing Strategy

### 11.1 Key Test Scenarios

**Term:**
- [ ] Code auto-generation from dates
- [ ] end_date auto-set to +2 years
- [ ] Lock prevents editing
- [ ] Date validation (end >= start)
- [ ] Duplicate code prevention

**Composition:**
- [ ] OneToOne with Term enforced
- [ ] Max 9 active mandates validation
- [ ] active_mandates_count() accuracy

**Mandate:**
- [ ] Position must be 1-9
- [ ] Date validation (end >= start)
- [ ] is_active property accuracy
- [ ] Ordering by position

**Session:**
- [ ] Code auto-generation with Roman numerals
- [ ] Status auto-computation from signatures
- [ ] Date must fall within term period
- [ ] Lock logic for non-managers
- [ ] Retry logic on code collision

**SessionAttendance:**
- [ ] Unique constraint (session, mandate)
- [ ] backup_attended flag behavior

**SessionItem:**
- [ ] Item code generation (S001, S002...)
- [ ] Order uniqueness per session
- [ ] Election integration (PersonRole.elected_via)
- [ ] Validation for COUNTED voting (all fields required)

**Vote:**
- [ ] Unique constraint (item, mandate)
- [ ] Cascade delete with item

**session_status():**
- [ ] All status states from signature combinations
- [ ] Rejection takes precedence
- [ ] Correct ordering of checks

**int_to_roman():**
- [ ] Correct conversion 1-50
- [ ] ValueError outside range

---

### 11.2 Admin Action Tests

**TermAdmin:**
- [ ] lock_term creates signature
- [ ] unlock_term removes lock
- [ ] print_term generates PDF
- [ ] Action visibility based on lock state

**SessionAdmin:**
- [ ] submit_session transitions DRAFT → SUBMITTED
- [ ] withdraw_session transitions SUBMITTED → DRAFT
- [ ] approve_session transitions SUBMITTED → APPROVED
- [ ] reject_session transitions SUBMITTED → REJECTED
- [ ] verify_session sets timestamp and transitions
- [ ] Action visibility based on status
- [ ] Manager bypass for locks

**SessionItemAdmin:**
- [ ] print_dispatch_document requires linked PersonRole
- [ ] Form conditional fields based on kind
- [ ] Deletion blocked after chair approval

---

### 11.3 PROTOKOL-KUN Tests

**protocol_save_item:**
- [ ] Creates new items with auto-order
- [ ] Updates existing items
- [ ] Handles named voting (delete/recreate Votes)
- [ ] Lock check prevents non-manager edits

**protocol_delete_item:**
- [ ] Deletes item
- [ ] Renumbers remaining items correctly
- [ ] Lock check blocks non-managers

**protocol_reorder_items:**
- [ ] Updates order based on array
- [ ] Lock check prevents non-manager reorder

**protocol_insert_at:**
- [ ] Shifts items after insert point
- [ ] Returns correct new_order

**protocol_get_item:**
- [ ] Returns complete item data
- [ ] Includes named votes if applicable

---

### 11.4 Edge Cases

**Code Generation:**
- Multiple simultaneous creates (race condition)
- 5 retry exhaustion scenario
- Session #51 (Roman numeral limit)

**Ordering:**
- Gap in orders (e.g., 1, 3, 5)
- Reorder with invalid item IDs
- Insert at position 0
- Delete last item

**Election:**
- ELECTION item without elected_person_role
- Session approved before PersonRole linked
- PersonRole updated after approval

**Lock States:**
- Manager editing locked session
- Non-manager attempting edit
- Withdraw after approve (should fail)

**Voting:**
- COUNTED mode with missing vote counts
- NAMED mode with no votes created
- Vote for non-existent mandate

---

### 11.5 Performance Considerations

**Query Optimization:**

SessionAdmin:

```python
qs.select_related('term')
qs.prefetch_related('attendees', 'absent', 'items')
```

SessionItemAdmin:

```python
qs.select_related('session__term', 'elected_person_role__person', 'elected_person_role__role')
```

MandateAdmin:

```python
# Search fields include related lookups - potentially slow
search_fields = ('person_role__person__first_name', ...)
```

**PROTOKOL-KUN:**

Loads all items + annotations in single view - reasonable for typical session size (<50 items).

---

## 12. File Structure

```
assembly/
├── __init__.py
├── models.py              # All models + utility functions
├── admin.py               # All admin classes + inlines
├── views.py               # PROTOKOL-KUN editor + AJAX endpoints
├── forms.py               # SessionItemProtocolForm
├── urls.py                # URL patterns
├── apps.py
├── tests.py
├── management/
│   └── commands/
│       └── bootstrap_terms.py
└── migrations/
    ├── 0001_initial.py
    ├── 0002_initial.py    # FK constraints
    ├── 0003_*.py          # Remove notes fields
    ├── 0004_*.py          # Add attendance tracking
    ├── 0005_*.py          # Attendance constraint changes
    ├── 0006_*.py          # Attendance unique together
    └── 0007_*.py          # Mandate indexes
```

---

## 13. Common Pitfalls

1. **Don't manually set Session.status** - it's auto-computed from signatures
2. **Roman numerals limited to 50** - terms with >50 sessions will fail
3. **Manager bypass isn't optional** - `_is_locked()` checks manager status
4. **Order field must be unique** - use PROTOKOL-KUN endpoints, not manual edits
5. **Code generation has 5-retry limit** - collisions unlikely but possible
6. **Election integration runs on save** - only when status is APPROVED/VERIFIED
7. **Named voting deletes/recreates votes** - don't assume Vote IDs stable
8. **Lock checks in AJAX are separate** - client display doesn't enforce security
9. **Text references are temporary** - clear after linking PersonRole
10. **SessionAttendance is through model** - use inline, not direct M2M add

---

**Version:** 1.0.5  
**Last Updated:** 2025-12-08  
**Author:** Sven (vas)