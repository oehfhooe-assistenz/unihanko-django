# Academia Module

## 1. Overview

The Academia module manages ECTS (European Credit Transfer System) reimbursement requests for Austrian student union elected officials and acknowledged functionaries. It handles the complete workflow from student submission through verification, chair approval, and eventual transfer to audit.

**Key Responsibilities:**
- Define academic semesters with public filing windows
- Track ECTS reimbursement requests from students
- Validate ECTS claims against role entitlements
- Workflow management through HankoSign integration
- Generate printable forms with digital signatures

**Dependencies:**
- `people` - PersonRole model for role-based ECTS entitlements
- `hankosign` - Digital signature workflow and state management
- `annotations` - Cross-module annotation support
- `organisation` - OrgInfo for PDF generation
- `core` - PDF rendering, admin mixins, authorization utilities

---

## 2. Models

### 2.1 Semester

Academic semester definition with public filing access control.

**Purpose:** Defines the time period for ECTS reimbursements, controls public portal access via password, and can be locked to prevent modifications during audit.

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `code` | CharField(10) | Unique semester code (format: `WS##` or `SS##`) |
| `display_name` | CharField(100) | Full name (e.g., "Winter Semester 2024/25") |
| `start_date` | DateField | Semester start date |
| `end_date` | DateField | Semester end date |
| `filing_start` | DateTimeField | When public portal opens (nullable) |
| `filing_end` | DateTimeField | When public portal closes (nullable) |
| `access_password` | CharField(50) | Auto-generated password (format: `word-word-##`) |
| `ects_adjustment` | DecimalField(3,1) | Bonus/malus ECTS for all roles (e.g., +2.0, -2.0) |

**Constraints:**
- `code` must match regex `^(WS|SS)\d{2}$` (e.g., WS24, SS25)
- `end_date` >= `start_date` (database check constraint)
- `filing_end` > `filing_start` (validation)

**Lock Mechanism:**
- Locked via HankoSign `LOCK` signature
- When locked, only `updated_at` can be modified
- Lock prevents editing dates, filing windows, ECTS adjustment

**Auto-generation:**
- `access_password` auto-generated on save using wordlist (see `generate_semester_password()`)

**Properties:**

```python
@property
def is_filing_open(self):
    """Returns True if current time is within filing window"""
```

---

### 2.2 InboxRequest

Main working table for student ECTS reimbursement requests.

**Purpose:** Tracks individual student requests through workflow stages from draft to approval/rejection. Each person can have only one request per semester.

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `semester` | FK(Semester) | Associated semester (PROTECT) |
| `person_role` | FK(PersonRole) | Role under which ECTS are claimed (PROTECT) |
| `stage` | CharField(12) | Auto-computed from HankoSign signatures |
| `reference_code` | CharField(20) | Unique code (format: `SSSS-LLLL-####`) |
| `filing_source` | CharField(20) | `'PUBLIC'` or `'ADMIN'` |
| `student_note` | TextField | Optional student comment |
| `affidavit1_confirmed_at` | DateTimeField | Initial submission confirmation timestamp |
| `affidavit2_confirmed_at` | DateTimeField | Form upload confirmation timestamp |
| `uploaded_form` | FileField | PDF with professor signatures (10MB max) |
| `uploaded_form_at` | DateTimeField | Upload timestamp |
| `submission_ip` | GenericIPAddressField | IP for audit trail |

**Stage Enum:**

```python
class Stage(models.TextChoices):
    DRAFT        = "DRAFT", "Draft"
    SUBMITTED    = "SUBMITTED", "Submitted"
    VERIFIED     = "VERIFIED", "Verified"
    APPROVED     = "APPROVED", "Approved"
    REJECTED     = "REJECTED", "Rejected"
    TRANSFERRED  = "TRANSFERRED", "Transferred to Audit"
```

**Constraints:**
- Unique constraint on `(person_role, semester)` - one request per person per semester
- `reference_code` unique globally
- Indexes on `stage`, `(semester, stage)`, `created_at`

**Stage Computation Logic:**

Stage is auto-computed via `inboxrequest_stage()` function:

1. `REJECTED` - if has `REJECT:CHAIR` signature
2. `TRANSFERRED` - if has `TRANSFER:-` signature (terminal state)
3. `APPROVED` - if has `APPROVE:CHAIR` signature
4. `VERIFIED` - if has `VERIFY:-` signature
5. `SUBMITTED` - if uploaded_form exists AND either:
   - `filing_source == 'ADMIN'`, OR
   - `affidavit2_confirmed_at` is set (public submission)
6. `DRAFT` - if has courses AND either:
   - `affidavit1_confirmed_at` is set, OR
   - `filing_source == 'ADMIN'` (admin can skip affidavit)
7. `DRAFT` - default

**Lock Mechanism:**
- Partially locked after `VERIFY:-` signature
- When verified, only these fields can be modified: `uploaded_form`, `uploaded_form_at`, `affidavit2_confirmed_at`, `updated_at`
- Also locked if parent Semester is locked

**Reference Code Generation:**

Auto-generated on first save using retry logic:

```python
# Format: SSSS-LLLL-####
# Example: WS24-SMIT-1234
# - SSSS: 4-char semester code
# - LLLL: First 4 chars of last name (uppercase, padded with X)
# - ####: 4 random digits
```

Retry up to 100 times on collision, raises ValidationError if unsuccessful.

**Properties:**

```python
@property
def total_ects(self):
    """Sum of ECTS from all related courses"""
```

---

### 2.3 InboxCourse

Individual course within an ECTS request.

**Purpose:** Represents a single course for which student claims ECTS credit. Multiple courses can be attached to one InboxRequest.

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `inbox_request` | FK(InboxRequest) | Parent request (CASCADE) |
| `course_code` | CharField(20) | Course code (e.g., "LV101") - optional |
| `course_name` | CharField(200) | Course name - optional |
| `ects_amount` | DecimalField(3,1) | ECTS credit amount (must be > 0) |

**Validation Rules:**
- At least one of `course_code` or `course_name` must be provided
- `ects_amount` must be > 0

**String Representation:**

```python
# Displays: "CODE - NAME (X.X ECTS)" if both exist
# Or: "CODE (X.X ECTS)" if only code
# Or: "NAME (X.X ECTS)" if only name
```

---

## 3. Admin Features

### 3.1 SemesterAdmin

**List Display:**
- Code, display name, dates
- Filing window status (OPEN/Upcoming/Closed) with colored indicators
- ECTS adjustment
- Request count (annotated queryset)
- Lock status

**Object Actions:**

| Action | Permission | Behavior |
|--------|-----------|----------|
| `regenerate_password` | Superuser only | Generates new access password |
| `lock_semester` | Academia manager | Records `LOCK:-` signature, prevents edits |
| `unlock_semester` | Academia manager | Records `UNLOCK:-` signature, allows edits |

**Readonly Logic:**
- After creation: `code`, `display_name` locked
- When locked: All fields except `updated_at` are readonly

**Special Features:**
- Annotations inline for collaboration
- Import/Export support
- History tracking (SimpleHistory)
- Optimistic locking (Concurrency)

---

### 3.2 InboxRequestAdmin

**List Display:**
- Status badge (colored by stage)
- Reference code, person name, role
- Semester
- Total ECTS
- Lock status

**List Filters:**
- Semester
- Stage
- Created date

**Search Fields:**
- Reference code
- Person last name, first name
- Role name

**Object Actions:**

| Action | Permission | Available When | Behavior |
|--------|-----------|----------------|----------|
| `verify_request` | Academia manager | DRAFT/SUBMITTED stages | Records `VERIFY:-` signature, creates annotation |
| `approve_request` | Academia manager | VERIFIED stage | Records `APPROVE:CHAIR` signature |
| `reject_request` | Academia manager | VERIFIED stage | Records `REJECT:CHAIR` signature |
| `print_form` | Academia manager | Any stage | Generates PDF with `RELEASE:-` signature (10s window) |

**Action Visibility Logic:**

```python
DRAFT/SUBMITTED → only verify_request available
VERIFIED        → approve_request, reject_request available
APPROVED+       → only print_form available
```

**Readonly Logic:**
- Always readonly: `reference_code`, `stage`, affidavit timestamps, `submission_ip`, `filing_source`
- After creation: `semester`, `person_role` locked (scope lock)
- When verified OR semester locked: `student_note`, affidavits, form fields locked

**Special Features:**
- ECTS validation display shows current/max/status
- Auto-sets `uploaded_form_at` when form uploaded
- For admin-filed requests, auto-sets `affidavit2_confirmed_at` on form upload
- InboxCourse inline with pagination (5 per page)
- Deletion disabled

**Custom Admin Display Fields:**

```python
status_text         # Colored stage badge with JS state hooks
person_name         # First + last name from person_role
total_ects_display  # Sum from courses
validation_status   # OK/Exceeds indicator
active_text         # Open/Locked status
```

---

### 3.3 InboxCourseInline

**Behavior:**
- Stacked inline with pagination (5 per page)
- Validates at least one of course_code/course_name provided
- Permission checks cascade from parent InboxRequest and Semester locks

**Lock Behavior:**
- If parent InboxRequest is locked → no add/change/delete
- If parent Semester is locked → no add/change/delete

---

## 4. Workflows

### 4.1 InboxRequest Workflow

**Stage Progression:**

```
DRAFT → SUBMITTED → VERIFIED → APPROVED/REJECTED
                              ↓
                         TRANSFERRED (to audit)
```

**Detailed Flow:**

1. **DRAFT**
   - Created by admin OR public portal with affidavit1
   - Courses can be added
   - All fields editable

2. **SUBMITTED**
   - Form PDF uploaded
   - For admin: automatic on upload
   - For public: requires affidavit2 confirmation

3. **VERIFIED**
   - Manager verifies form completeness
   - ECTS validation occurs (warning if exceeds)
   - `VERIFY:-` signature recorded
   - Most fields locked, only form upload still editable

4. **APPROVED**
   - Chair approves request
   - `APPROVE:CHAIR` signature recorded
   - Fully locked except for printing

5. **REJECTED**
   - Chair rejects request
   - `REJECT:CHAIR` signature recorded
   - Terminal state

6. **TRANSFERRED**
   - Request transferred to audit system
   - `TRANSFER:-` signature recorded
   - Terminal state

**Lock Points:**

| Stage | Editable Fields |
|-------|----------------|
| DRAFT | All |
| SUBMITTED | All |
| VERIFIED | Only `uploaded_form`, `uploaded_form_at`, `affidavit2_confirmed_at` |
| APPROVED+ | None (read-only) |

---

### 4.2 Semester Lock Workflow

**Lock Action:**
- Records `LOCK:-@academia.Semester` signature
- Sets `explicit_locked` state
- Prevents all edits except timestamp
- Also locks all child InboxRequests

**Unlock Action:**
- Records `UNLOCK:-@academia.Semester` signature
- Removes lock
- Use with caution - intended for corrections only

---

### 4.3 Signature Actions

All HankoSign actions used:

| Action String | Type | Scope | Purpose |
|--------------|------|-------|---------|
| `VERIFY:-@academia.InboxRequest` | Regular | Request | Staff verification |
| `APPROVE:CHAIR@academia.InboxRequest` | Regular | Request | Chair approval |
| `REJECT:CHAIR@academia.InboxRequest` | Regular | Request | Chair rejection |
| `RELEASE:-@academia.InboxRequest` | Window (10s) | Request | PDF generation |
| `LOCK:-@academia.Semester` | Regular | Semester | Lock semester |
| `UNLOCK:-@academia.Semester` | Regular | Semester | Unlock semester |
| `TRANSFER:-@academia.InboxRequest` | Regular | Request | Transfer to audit |

---

## 5. Important Functions & Utilities

### 5.1 Core Functions

#### `generate_semester_password()`

```python
def generate_semester_password() -> str:
    """Generate memorable password: word-word-##"""
```

- Uses wordlist.yaml (120+ nature/color/animal words)
- Format: `forest-mountain-42`
- Secure random number generation

---

#### `generate_reference_code(semester_code, last_name)`

```python
def generate_reference_code(semester_code: str, last_name: str) -> str:
    """Generate reference code: SSSS-LLLL-####"""
```

- Takes first 4 chars of last name (uppercase, padded with X)
- Generates 4 random digits
- Example: `WS24-SMIT-1234`

---

#### `inboxrequest_stage(ir)`

```python
def inboxrequest_stage(ir: InboxRequest) -> str:
    """Compute stage from HankoSign signatures and upload state"""
```

Critical function that determines workflow stage. See **2.2 InboxRequest** for logic flow.

**Important:** Stage is recomputed on every save. Never set manually.

---

#### `validate_ects_total(inbox_request)`

```python
def validate_ects_total(inbox_request) -> tuple[bool, Decimal, Decimal, str]:
    """
    Validate total ECTS doesn't exceed role's nominal cap.
    
    Returns: (is_valid, max_ects, total_ects, message)
    """
```

**Key Points:**
- Checks against `person_role.role.ects_cap`
- This is **formal validation** - no aliquotation
- Actual earned ECTS (with work period aliquotation) calculated during audit
- Used in admin validation and object actions

---

#### `get_random_words(count)`

```python
def get_random_words(count: int = 2) -> list[str]:
    """Get random words from wordlist.yaml for passwords"""
```

- Uses `SystemRandom` for security
- Fallback wordlist if file missing
- Called by `generate_semester_password()`

---

### 5.2 Admin Utilities

All admin actions use these decorators/mixins:

```python
@transaction.atomic       # Database safety
@safe_admin_action       # Error handling & rollback
```

Permission check: `is_academia_manager(request.user)` required for most actions.

---

## 6. Gotchas & Important Notes

### 6.1 Stage Management

⚠️ **Never manually set `stage` field** - it's auto-computed from HankoSign signatures on every save via `inboxrequest_stage()` function.

If stage seems wrong:
1. Check HankoSign signatures on the object
2. Run `python manage.py recompute_stages` to recalculate all stages

---

### 6.2 Lock Cascading

Semester locks cascade to all InboxRequests:
- Parent Semester locked → all child requests locked
- InboxRequest can be individually locked via VERIFY signature
- InboxCourse inline respects both parent and grandparent locks

---

### 6.3 Reference Code Collisions

Reference code generation has **100 retry limit**. If exhausted, raises ValidationError.

Collision probability is low (~0.01% for 100 requests in same semester with same name prefix), but possible with:
- Many requests from people with same last name prefix
- Same semester

---

### 6.4 Filing Source Differences

`filing_source` affects stage computation:

| Source | affidavit1 Required? | affidavit2 Required? |
|--------|---------------------|---------------------|
| `ADMIN` | No (courses alone = DRAFT) | No (auto-set on upload) |
| `PUBLIC` | Yes | Yes |

---

### 6.5 ECTS Validation vs. Audit

Two separate ECTS calculations exist:

1. **Validation** (in this module):
   - Simple: `sum(courses.ects_amount) <= role.ects_cap`
   - No aliquotation, no work period consideration
   - Warning only, not blocking

2. **Audit** (in audit module):
   - Complex: considers work period overlap with semester
   - Applies aliquotation based on actual days worked
   - Generates final entitlement amounts

---

### 6.6 Form Upload Timestamps

`uploaded_form_at` is auto-set when file uploaded in admin:

```python
# In save_model()
if 'uploaded_form' in form.changed_data:
    obj.uploaded_form_at = timezone.now()
```

Don't manually set this field.

---

### 6.7 Optimistic Locking

Both Semester and InboxRequest use `AutoIncVersionField`:
- Prevents concurrent modification conflicts
- Raises exception if version mismatch on save
- User must refresh and retry

---

## 7. GDPR Considerations

**Personal Data Fields:**

| Model | Fields | Retention |
|-------|--------|-----------|
| InboxRequest | `student_note`, `submission_ip` | Keep for audit trail |
| InboxRequest | `uploaded_form` (contains signatures) | Keep for legal compliance |

**Access Control:**
- `submission_ip` logged for security/audit
- Only academia managers can access most actions
- Superusers required for password regeneration

**Data Minimization:**
- Only essential fields captured
- Student note is optional
- IP captured only on submission, not on edits

---

## 8. Testing Strategy

### 8.1 Key Test Scenarios

**Semester:**
- [ ] Password auto-generation on save
- [ ] Lock prevents editing (except updated_at)
- [ ] Filing window validation (end > start)
- [ ] Date constraint (end >= start)
- [ ] Code format validation (WS##/SS##)

**InboxRequest:**
- [ ] Stage computation for each HankoSign state
- [ ] Reference code generation & collision handling
- [ ] Unique constraint (person_role, semester)
- [ ] Lock behavior after VERIFY signature
- [ ] Parent semester lock cascades to request
- [ ] `total_ects` property calculates correctly
- [ ] Admin vs. public filing source behavior

**InboxCourse:**
- [ ] Validation: at least one of code/name required
- [ ] ECTS amount must be positive
- [ ] Cascade delete when parent deleted

**Workflows:**
- [ ] DRAFT → SUBMITTED transition (both admin & public)
- [ ] VERIFY action locks most fields
- [ ] APPROVE/REJECT terminal states
- [ ] Print form creates RELEASE signature

**Admin Actions:**
- [ ] verify_request validates form uploaded
- [ ] approve_request only available in VERIFIED stage
- [ ] print_form generates PDF with correct data
- [ ] lock_semester prevents all child edits

**Utility Functions:**
- [ ] `generate_semester_password()` produces valid format
- [ ] `generate_reference_code()` handles special chars in names
- [ ] `validate_ects_total()` correctly compares against cap
- [ ] `inboxrequest_stage()` handles all signature combinations

---

### 8.2 Edge Cases

**Reference Code Generation:**
- Names with umlauts (ä→A, ö→O, etc.)
- Names < 4 chars (padding with X)
- Collision retry exhaustion (100 attempts)

**Stage Computation:**
- Request with no courses (DRAFT)
- Admin request without affidavits (valid)
- Public request without affidavit2 (stays DRAFT even with form)

**Lock Behavior:**
- Semester lock + request VERIFY lock (both active)
- Unlock semester while requests are verified (requests stay locked)
- Editing locked field attempts (should show validation error)

**ECTS Validation:**
- Total equals exactly cap (valid)
- Total exceeds by 0.1 (warning but not blocking)
- No courses (0.00 total, always valid)

---

### 8.3 Performance Considerations

**Query Optimization:**

InboxRequestAdmin uses `select_related()` and `prefetch_related()`:

```python
qs.select_related('semester', 'person_role__person', 'person_role__role')
qs.prefetch_related('courses')
```

SemesterAdmin annotates request count:

```python
qs.annotate(_requests_count=Count('inbox_requests'))
```

**File Upload:**
- Max 10MB for PDF forms
- Files stored in `media/academia/forms/%Y/%m/`

---

## 9. Management Commands

### 9.1 `bootstrap_semesters`

**Purpose:** Create/update semesters from YAML config (idempotent).

**Usage:**

```bash
python manage.py bootstrap_semesters --file config/fixtures/semesters.yaml
python manage.py bootstrap_semesters --dry-run  # Preview changes
```

**YAML Format:**

```yaml
semesters:
  - code: WS24
    display_name: Winter Semester 2024/25
    start_date: 2024-10-01
    end_date: 2025-02-15
  - code: SS25
    display_name: Summer Semester 2025
    start_date: 2025-03-01
    end_date: 2025-07-31
```

**Behavior:**
- Creates new semesters if code doesn't exist
- Updates existing semesters if dates/name changed
- Skips unchanged semesters
- Validates all fields before saving
- Transactional (all-or-nothing)

---

### 9.2 `recompute_stages`

**Purpose:** Recalculate stage field for all InboxRequest objects.

**Usage:**

```bash
python manage.py recompute_stages
python manage.py recompute_stages --dry-run  # Preview changes
```

**When to Use:**
- After HankoSign signature corrections
- After data migrations affecting signatures
- If stage seems out of sync with actual signatures

**Behavior:**
- Iterates all InboxRequest objects
- Calls `inboxrequest_stage()` for each
- Updates only if stage changed
- Reports count of updated vs. unchanged

---

## 10. Integration Points

### 10.1 people Module

**Dependency:** `PersonRole` model

```python
person_role = models.ForeignKey(PersonRole, ...)
```

Used for:
- Linking request to person and their role
- Accessing `role.ects_cap` for validation
- Display person name in admin

---

### 10.2 hankosign Module

**Utilities Used:**

```python
from hankosign.utils import (
    state_snapshot,         # Get lock/signature state
    has_sig,               # Check if signature exists
    record_signature,      # Create signature
    sign_once,             # Create windowed signature
    render_signatures_box, # Display signatures in admin
    seal_signatures_context, # Prepare signatures for PDF
)
```

**HankoSign Integration:**
- Stage computed from signatures
- Lock state from signatures
- Admin actions record signatures
- PDF generation includes signature metadata

---

### 10.3 annotations Module

**Integration:**

```python
from annotations.admin import AnnotationInline
from annotations.views import create_system_annotation
```

**Usage:**
- Both Semester and InboxRequest have AnnotationInline
- System annotations created on VERIFY, APPROVE, REJECT, LOCK, UNLOCK actions
- Provides collaboration & audit trail

---

### 10.4 organisation Module

**Dependency:** `OrgInfo` model

Used in PDF generation for letterhead/contact info:

```python
ctx = {'org': OrgInfo.get_solo(), ...}
```

---

### 10.5 core Module

**Utilities Used:**

```python
from core.admin_mixins import (
    log_deletions,         # Deletion audit trail
    safe_admin_action,     # Error handling wrapper
    ImportExportGuardMixin, # IE permission control
    HistoryGuardMixin,     # History permission control
    with_help_widget,      # Help text enhancement
)
from core.pdf import render_pdf_response
from core.utils.bool_admin_status import boolean_status_span
from core.utils.authz import is_academia_manager
```

---

## 11. File Structure

```
academia/
├── __init__.py
├── models.py              # Semester, InboxRequest, InboxCourse
├── admin.py               # Admin interfaces with object actions
├── utils.py               # ECTS validation, password generation
├── apps.py
├── tests.py
├── wordlist.yaml          # 120+ words for password generation
├── migrations/
│   ├── 0001_initial.py
│   ├── 0002_initial.py    # Adds FK constraints
│   ├── 0003_*.py          # filing_source field
│   ├── 0004_*.py          # stage field
│   ├── 0005_*.py          # Remove old audit fields
│   └── 0006_*.py          # FileField validators
└── management/
    └── commands/
        ├── bootstrap_semesters.py
        └── recompute_stages.py
```

---

## 12. Common Pitfalls

1. **Don't manually set `stage`** - it's computed automatically
2. **Reference codes can collide** - retry logic handles up to 100 attempts
3. **ECTS validation is not blocking** - it's a warning, not a hard stop
4. **Semester locks cascade** - unlocking semester doesn't unlock individual requests
5. **affidavit2 timing differs** - admin auto-sets, public requires explicit confirmation
6. **Optimistic locking active** - concurrent edits will fail, user must refresh
7. **stage recomputes on save** - any change triggers stage recalculation
8. **VERIFY locks most fields** - only form upload remains editable
9. **Print form signature is windowed** - only valid for 10 seconds
10. **Deletion disabled** - both Semester and InboxRequest cannot be deleted via admin

---

**Version:** 1.0.5  
**Last Updated:** 2025-12-08  
**Author:** Sven (vas)