# Academia Audit Module

## 1. Overview

The Academia Audit module handles the final ECTS calculation, verification, and approval workflow for semester audits. It's separate from the inbox filing workflow and performs complex aliquotation calculations based on work period overlap.

**Key Responsibilities:**
- Generate per-person audit entries with aliquoted ECTS calculations
- Apply semester bonus/malus adjustments
- Track specific course reimbursements vs. bulk ECTS allocation
- Manage audit approval workflow with chair signatures
- Generate audit PDF reports

**Dependencies:**
- `academia` - Semester and InboxRequest models
- `people` - Person and PersonRole models for work period calculations
- `hankosign` - Digital signature workflow and lock management
- `annotations` - Cross-module annotation support
- `organisation` - OrgInfo for PDF generation
- `core` - PDF rendering, admin mixins, authorization utilities

---

## 2. Models

### 2.1 AuditSemester

Container for audit workflow tied to an academia.Semester.

**Purpose:** Manages the audit lifecycle for a specific semester, tracks synchronization timestamps, stores final audit PDF, and controls workflow progression through HankoSign signatures.

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `semester` | OneToOneField(Semester) | Reference to academia.Semester (PROTECT) |
| `audit_generated_at` | DateTimeField | Last synchronization timestamp (nullable) |
| `audit_pdf` | FileField | Final signed audit report PDF (25MB max, nullable) |
| `audit_sent_university_at` | DateTimeField | Timestamp when sent to university (nullable) |

**Relationships:**
- OneToOne with `academia.Semester` (related_name: `audit`)
- Has many `AuditEntry` objects (related_name: `entries`)

**Constraints:**
- OneToOneField enforces one audit per semester
- Custom validation prevents duplicate semester

**Lock Mechanism:**
- Locked via HankoSign `LOCK:-@academia_audit.AuditSemester` signature
- When locked, prevents all modifications (ValidationError on save)
- Lock cascades to all child AuditEntry objects

**File Upload:**
- `audit_pdf` accepts only PDF files (25MB max)
- Stored in `media/academia/audits/`

**Ordering:**
- Default sort: `-semester__start_date` (newest first)

---

### 2.2 AuditEntry

Final per-person ECTS calculation for a semester audit.

**Purpose:** Represents the complete ECTS entitlement calculation for one person across all their roles during a semester. Tracks aliquotation, reimbursements, and remaining bulk allocation.

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `audit_semester` | FK(AuditSemester) | Parent audit (PROTECT) |
| `person` | FK(Person) | The person this entry is for (PROTECT) |
| `person_roles` | M2M(PersonRole) | All roles held during semester |
| `inbox_requests` | M2M(InboxRequest) | Approved reimbursement requests |
| `aliquoted_ects` | DecimalField(5,2) | Base ECTS with aliquotation (before bonus/malus) |
| `final_ects` | DecimalField(5,2) | Final entitled ECTS (after bonus/malus) |
| `reimbursed_ects` | DecimalField(5,2) | Sum from specific course reimbursements |
| `remaining_ects` | DecimalField(5,2) | Remaining ECTS credited as bulk/general |
| `calculation_details` | JSONField | Detailed breakdown per role |
| `checked_at` | DateTimeField | Manual review timestamp (nullable) |
| `notes` | TextField | Optional notes for adjustments |

**Constraints:**
- Unique constraint on `(audit_semester, person)` - one entry per person per audit
- Indexes on `audit_semester`, `checked_at`

**Validation Rules:**
- `reimbursed_ects` cannot be negative
- `remaining_ects` cannot be negative
- Cannot modify if parent AuditSemester is locked

**ECTS Calculation Flow:**

```python
# 1. Calculate aliquoted ECTS (highest role with work period aliquotation)
aliquoted_ects = max(aliquoted_ects_per_role)

# 2. Apply semester bonus/malus
final_ects = aliquoted_ects + semester.ects_adjustment

# 3. Ensure non-negative
final_ects = max(final_ects, 0.00)

# 4. Sum approved reimbursement requests
reimbursed_ects = sum(courses.ects_amount for approved_requests)

# 5. Calculate remaining for bulk allocation
remaining_ects = max(final_ects - reimbursed_ects, 0.00)
```

**Manual Review Protection:**

The `checked_at` field serves as a protection flag:
- Set to current timestamp when admin manually edits ECTS fields
- Entries with `checked_at != NULL` are **skipped** by synchronization
- Prevents automated calculations from overwriting manual corrections
- Admin must clear `checked_at` to allow re-synchronization

**calculation_details JSON Structure:**

```json
{
  "roles": [
    {
      "role_name": "Student Representative",
      "person_role_id": 123,
      "nominal_ects": 30.0,
      "held_from": "2024-10-01",
      "held_to": "2025-02-15",
      "aliquoted_ects": 28.5
    }
  ],
  "aliquoted_ects": 28.5,
  "bonus_malus": 2.0,
  "final_ects": 30.5,
  "calculation_date": "2025-12-08T14:30:00Z",
  "approved_requests_count": 2
}
```

---

## 3. Admin Features

### 3.1 AuditSemesterAdmin

**List Display:**
- Status badge (from HankoSign state)
- Semester code, display name, dates
- Entry count (annotated)
- Last updated timestamp
- Lock status

**Search:**
- Semester code
- Semester display name

**Inlines:**
- AuditEntry inline (paginated, 5 per page)
- Annotation inline

**Object Actions:**

| Action | Permission | Available When | Behavior |
|--------|-----------|----------------|----------|
| `lock_audit` | Audit manager | Not locked | Records `LOCK:-` signature |
| `unlock_audit` | Audit manager | Locked | Records `UNLOCK:-` signature |
| `synchronize_entries` | Audit manager | Any time, but not after verified | Runs `synchronize_audit_entries()` |
| `verify_audit_complete` | Audit manager | Locked, not verified, all entries checked | Records `VERIFY:-` signature |
| `approve_audit` | Audit manager | Locked + verified | Records `APPROVE:CHAIR` signature |
| `reject_audit` | Audit manager | Locked + verified, not approved | Records `REJECT:CHAIR` signature |
| `verify_audit_sent` | Audit manager | Locked + chair approved | Sets `audit_sent_university_at`, records `VERIFY:SENT` signature |
| `print_audit_pdf` | Audit manager | Any time | Generates PDF with `RELEASE:-` signature (10s window) |

**Action Visibility Logic:**

```python
# Not locked → only lock_audit, synchronize_entries, print_audit_pdf
if not locked:
    hide: verify_audit_complete, approve_audit, reject_audit, verify_audit_sent
    show: lock_audit, synchronize_entries
    
# Locked, not verified → verify_audit_complete available
elif locked and not verified:
    hide: unlock_audit, approve_audit, reject_audit, verify_audit_sent, synchronize_entries
    show: verify_audit_complete

# Locked + verified, not approved → approve/reject available
elif locked and verified and not approved:
    hide: verify_audit_complete, synchronize_entries
    show: approve_audit, reject_audit
    
# Locked + verified + approved → verify_audit_sent available
elif locked and verified and approved:
    hide: verify_audit_complete, approve_audit, reject_audit, synchronize_entries
    show: verify_audit_sent
```

**Readonly Logic:**
- After creation: `semester` locked
- All fields editable until locked

**Special Features:**
- Status badge uses `object_status_span(obj, final_stage="CHAIR")`
- Entry count annotated in queryset
- Semester info displayed as readonly fields in form
- Import/Export support
- History tracking
- Optimistic locking

---

### 3.2 AuditEntryInline

**Behavior:**
- Stacked inline, paginated (5 per page)
- Shows person, ECTS fields, review status, notes
- Links to uploaded forms from inbox requests
- Cannot add entries via inline (use synchronize action)
- Cannot delete entries via inline

**Auto-set checked_at:**

When admin modifies any ECTS field or notes via inline:

```python
# In save_formset()
ects_fields = ['aliquoted_ects', 'final_ects', 'reimbursed_ects', 'remaining_ects', 'notes']
if any field changed:
    instance.checked_at = timezone.now()
```

**Lock Behavior:**
- If parent AuditSemester locked → all ECTS fields readonly

**Linked PDFs Display:**

Shows clickable links to all uploaded forms from inbox requests:

```
📄 WS24-SMIT-1234
📄 WS24-SMIT-5678
REF-CODE-9999 (no form)
```

---

### 3.3 AuditEntryAdmin

**List Display:**
- Person name
- Audit semester code
- Final ECTS, reimbursed ECTS, remaining ECTS
- Checked status (Yes/No badge)
- Last updated timestamp
- Lock status

**List Filters:**
- Audit semester
- Checked at timestamp

**Search:**
- Person last name, first name

**Readonly Fields:**
- Always: `created_at`, `updated_at`, `calculation_details_display`, `linked_pdfs_display`
- After creation: `audit_semester`, `person` (scope lock)
- When parent locked: All ECTS fields, `notes`, M2M fields

**Auto-set checked_at:**

```python
# In save_model()
ects_fields = {'aliquoted_ects', 'final_ects', 'reimbursed_ects', 'remaining_ects', 'notes'}
if any field in form.changed_data:
    obj.checked_at = timezone.now()
```

**Special Features:**
- `calculation_details_display` shows formatted JSON
- `linked_pdfs_display` shows links to inbox request forms
- Deletion disabled
- Optimistic locking
- History tracking

---

## 4. Workflows

### 4.1 Audit Workflow

**Complete Workflow:**

```
1. CREATE AuditSemester (unlocked)
   ↓
2. SYNCHRONIZE entries (can repeat)
   ↓
3. LOCK audit
   ↓
4. Manual review → set checked_at on each entry
   ↓
5. VERIFY complete (requires all entries checked)
   ↓
6. APPROVE (chair) OR REJECT
   ↓
7. VERIFY sent to university
   ↓
8. PRINT PDF (available at any stage)
```

**State Transitions:**

| From State | Action | To State | Requirements |
|-----------|---------|----------|--------------|
| Unlocked | `lock_audit` | Locked | None |
| Locked | `unlock_audit` | Unlocked | None (use with caution) |
| Locked | `verify_audit_complete` | Verified | All entries checked |
| Verified | `approve_audit` | Approved (CHAIR) | None |
| Verified | `reject_audit` | Rejected | Not already approved |
| Approved | `verify_audit_sent` | Sent | Chair approval exists |

**Lock Points:**

| State | Can Synchronize? | Can Edit Entries? | Can Verify/Approve? |
|-------|-----------------|------------------|-------------------|
| Unlocked | ✅ Yes | ✅ Yes | ❌ No |
| Locked (not verified) | ❌ No | ✅ Yes | ✅ Can verify |
| Locked + Verified | ❌ No | ✅ Yes | ✅ Can approve/reject |
| Locked + Approved | ❌ No | ❌ No | ✅ Can verify sent |

---

### 4.2 Synchronization Workflow

**Process:**

1. Find all PersonRoles active during semester (with `ects_cap > 0`)
2. Group by Person
3. For each person:
   - Calculate aliquoted ECTS for each role
   - Take maximum (not sum) of aliquoted amounts
   - Apply semester bonus/malus
   - Find approved InboxRequests (with `APPROVE:CHAIR` signature)
   - Sum reimbursed ECTS from courses
   - Calculate remaining ECTS
4. Create new entry OR update existing if `checked_at IS NULL`
5. Skip entries with `checked_at != NULL` (manually reviewed)

**Idempotency:**

`synchronize_audit_entries()` can be run multiple times:
- Creates entries that don't exist
- Updates entries where `checked_at IS NULL`
- **Skips** entries where `checked_at IS NOT NULL`
- Updates `audit_generated_at` timestamp

**Returns:**

```python
(created_count, updated_count, skipped_count)
```

---

### 4.3 HankoSign Actions

All signatures used:

| Action String | Type | Scope | Purpose |
|--------------|------|-------|---------|
| `LOCK:-@academia_audit.AuditSemester` | Regular | Audit | Lock audit semester |
| `UNLOCK:-@academia_audit.AuditSemester` | Regular | Audit | Unlock audit semester |
| `VERIFY:-@academia_audit.AuditSemester` | Regular | Audit | Verify audit complete |
| `APPROVE:CHAIR@academia_audit.AuditSemester` | Regular | Audit | Chair approval |
| `REJECT:CHAIR@academia_audit.AuditSemester` | Regular | Audit | Chair rejection |
| `VERIFY:SENT@academia_audit.AuditSemester` | Regular | Audit | Verify sent to university |
| `RELEASE:-@academia_audit.AuditSemester` | Window (10s) | Audit | PDF generation |

---

## 5. Important Functions & Utilities

### 5.1 Core Calculation Functions

#### `calculate_aliquoted_ects(person_role, semester)`

```python
def calculate_aliquoted_ects(person_role, semester) -> Decimal:
    """
    Calculate aliquoted ECTS for a PersonRole during semester.
    Accounts for partial semester overlap by prorating based on days worked.
    """
```

**Logic:**

1. Find overlap window: `max(pr.start_date, sem.start_date)` to `min(pr.end_date, sem.end_date)`
2. If no overlap → return 0
3. Calculate: `days_worked = (end - start).days + 1` (inclusive)
4. Calculate: `semester_days = (sem.end - sem.start).days + 1`
5. Calculate: `percentage = days_worked / semester_days`
6. Apply: `aliquoted = role.ects_cap * percentage`
7. Round to 2 decimal places (ROUND_HALF_UP)

**Example:**

```python
# Role: 30 ECTS cap
# Semester: Oct 1 - Feb 15 (138 days)
# Person worked: Oct 1 - Dec 31 (92 days)

percentage = 92 / 138 = 0.6667
aliquoted = 30 * 0.6667 = 20.00 ECTS
```

---

#### `calculate_overlap_percentage(person_role, semester)`

```python
def calculate_overlap_percentage(person_role, semester) -> Decimal:
    """Calculate what percentage of the semester a PersonRole was active."""
```

Same logic as `calculate_aliquoted_ects()` but returns the percentage (0-1) rounded to 4 decimal places.

---

#### `synchronize_audit_entries(audit_semester)`

```python
@transaction.atomic
def synchronize_audit_entries(audit_semester) -> tuple[int, int, int]:
    """
    Create or update AuditEntry records for an audit semester.
    Returns: (created_count, updated_count, skipped_count)
    """
```

**Complete Algorithm:**

```python
# 1. Find all PersonRoles active during semester
person_roles = PersonRole.objects.filter(
    start_date <= semester.end_date,
    (end_date >= semester.start_date OR end_date IS NULL),
    role.ects_cap > 0
)

# 2. Group by person
persons_map = {}  # person -> [list of their roles]

# 3. For each person:
for person, their_roles in persons_map.items():
    
    # Check if entry exists and is manually checked
    existing = AuditEntry.objects.filter(
        audit_semester=audit_semester,
        person=person
    ).first()
    
    if existing and existing.checked_at is not None:
        skipped_count += 1
        continue  # Skip manually reviewed entries
    
    # 4. Calculate aliquoted ECTS for each role
    role_calcs = []
    for pr in their_roles:
        aliquoted = calculate_aliquoted_ects(pr, semester)
        role_calcs.append({...})
    
    # 5. Take MAXIMUM (not sum) of aliquoted ECTS
    aliquoted_ects = max(rc['aliquoted_ects'] for rc in role_calcs)
    
    # 6. Apply semester bonus/malus
    final_ects = aliquoted_ects + semester.ects_adjustment
    final_ects = max(final_ects, 0.00)  # Ensure non-negative
    
    # 7. Find approved InboxRequests
    approved_requests = InboxRequest.objects.filter(
        person_role__person=person,
        semester=semester
    )
    
    # Filter to only those with APPROVE:CHAIR signature
    approved_requests_filtered = [
        req for req in approved_requests
        if has_sig(req, 'APPROVE', 'CHAIR')
    ]
    
    # 8. Sum reimbursed ECTS
    total_reimbursed = sum(
        req.courses.sum('ects_amount')
        for req in approved_requests_filtered
    )
    
    # 9. Calculate remaining
    remaining_ects = max(final_ects - total_reimbursed, 0.00)
    
    # 10. Create or update entry
    if existing:
        # Update (only if not checked)
        existing.aliquoted_ects = aliquoted_ects
        existing.final_ects = final_ects
        existing.reimbursed_ects = total_reimbursed
        existing.remaining_ects = remaining_ects
        existing.calculation_details = calc_details
        existing.save()
        existing.person_roles.set(their_roles)
        existing.inbox_requests.set(approved_requests_filtered)
        updated_count += 1
    else:
        # Create new
        entry = AuditEntry.objects.create(...)
        entry.person_roles.set(their_roles)
        entry.inbox_requests.set(approved_requests_filtered)
        created_count += 1

# 11. Update timestamp
audit_semester.audit_generated_at = now()
audit_semester.save()

return (created_count, updated_count, skipped_count)
```

**Key Points:**

- **Maximum, not sum**: If person has multiple roles, takes highest aliquoted amount
- **Signature-based filtering**: Only counts requests with `APPROVE:CHAIR` signature
- **Protection**: Skips entries where `checked_at != NULL`
- **Idempotent**: Can run multiple times safely
- **Transactional**: All-or-nothing database updates

---

### 5.2 Validation Functions

#### `validate_pdf_size(file)`

```python
def validate_pdf_size(file):
    """Validate PDF size (max 25MB for audit documents)."""
```

Used for `audit_pdf` field.

---

## 6. Gotchas & Important Notes

### 6.1 Maximum vs. Sum

⚠️ **Critical:** When a person has multiple roles during a semester, the system takes the **MAXIMUM** aliquoted ECTS, not the sum.

**Why?** A person can only earn ECTS under one role at a time, even if they hold multiple positions simultaneously.

**Example:**

```python
Person has two roles in WS24:
- Role A: 30 ECTS cap, worked full semester → 30.00 aliquoted
- Role B: 20 ECTS cap, worked half semester → 10.00 aliquoted

Result: max(30.00, 10.00) = 30.00 ECTS (NOT 40.00)
```

---

### 6.2 checked_at Protection

The `checked_at` field is a **protection mechanism**:

- Synchronization **skips** entries with `checked_at != NULL`
- Admin must explicitly clear `checked_at` to allow re-synchronization
- Auto-set when admin manually edits ECTS fields or notes
- This prevents automated calculations from overwriting manual corrections

**Use Case:** Admin finds calculation error, manually corrects entry. Future synchronizations won't overwrite the correction.

---

### 6.3 Aliquotation Details

**Date Calculation:**

```python
# Overlap window
pr_start = max(person_role.start_date, semester.start_date)
pr_end = min(person_role.end_date or date.max, semester.end_date)

# Days calculation (inclusive on both ends)
days_worked = (pr_end - pr_start).days + 1
semester_days = (semester.end_date - semester.start_date).days + 1

# Percentage
percentage = days_worked / semester_days
```

**Important:** Both start and end dates are inclusive (+1 to days calculation).

---

### 6.4 Negative ECTS Handling

The system prevents negative ECTS at multiple points:

```python
# After bonus/malus
final_ects = max(aliquoted_ects + bonus_malus, 0.00)

# After reimbursement subtraction
remaining_ects = max(final_ects - reimbursed_ects, 0.00)

# Validation
if reimbursed_ects < 0:
    raise ValidationError
if remaining_ects < 0:
    raise ValidationError
```

---

### 6.5 Synchronization Timing

**When to synchronize:**

1. **After inbox requests are approved** - to include new reimbursements
2. **After person role changes** - if work periods adjusted
3. **Before verification** - final calculation pass
4. **Never after verification** - action hidden in locked state

**Best Practice:** Run synchronization multiple times before locking, but not after.

---

### 6.6 Lock Cascading

AuditSemester lock cascades to entries:

- Parent locked → all child entries readonly in admin
- Entry inline respects parent lock
- Individual entries don't have their own lock mechanism
- Unlock parent → entries become editable again

---

### 6.7 OneToOne Relationship

`AuditSemester.semester` is OneToOne:

- Each academia.Semester can have only one AuditSemester
- Attempting to create duplicate raises ValidationError
- Related_name: `semester.audit` (not `semester.audits`)

---

### 6.8 Approval vs. Sent

Two separate verification steps:

1. **APPROVE:CHAIR** - Chair approves the audit calculations
2. **VERIFY:SENT** - Manager confirms audit was sent to university

These are distinct signatures for audit trail purposes.

---

## 7. GDPR Considerations

**Personal Data:**

| Model | Fields | Purpose |
|-------|--------|---------|
| AuditEntry | Person FK, notes | Legal requirement for ECTS allocation |
| AuditEntry | calculation_details JSON | Transparency & audit trail |

**Data Retention:**

- Audit records must be retained for legal/financial compliance
- No automatic deletion mechanisms
- Person data is via FK (not duplicated)

**Access Control:**

- Only audit managers can access/modify
- History tracking for all changes
- Deletion disabled (immutable records)

---

## 8. Testing Strategy

### 8.1 Key Test Scenarios

**AuditSemester:**
- [ ] OneToOne constraint (can't create duplicate for same semester)
- [ ] Lock prevents all modifications
- [ ] Unlock removes lock
- [ ] PDF upload validation (25MB max, PDF only)

**AuditEntry:**
- [ ] Unique constraint (person, audit_semester)
- [ ] ECTS fields cannot be negative
- [ ] Lock cascade from parent AuditSemester
- [ ] checked_at protection in synchronization

**Aliquotation Calculations:**
- [ ] Full semester overlap (100%)
- [ ] Partial overlap (start mid-semester)
- [ ] Partial overlap (end mid-semester)
- [ ] No overlap (0%)
- [ ] Ongoing role (end_date IS NULL)

**Synchronization:**
- [ ] Creates entries for new people
- [ ] Updates entries without checked_at
- [ ] Skips entries with checked_at
- [ ] Takes maximum (not sum) of role ECTS
- [ ] Applies semester bonus/malus correctly
- [ ] Filters to only APPROVE:CHAIR requests
- [ ] Calculates remaining_ects correctly
- [ ] Idempotency (multiple runs)

**Admin Actions:**
- [ ] Lock/unlock toggle
- [ ] verify_audit_complete requires all entries checked
- [ ] approve_audit requires verification first
- [ ] verify_audit_sent requires approval first
- [ ] Action visibility based on state
- [ ] print_audit_pdf generates correct data

**checked_at Auto-set:**
- [ ] Set when ECTS field edited via form
- [ ] Set when ECTS field edited via inline
- [ ] Set when notes edited
- [ ] Not set when other fields edited

---

### 8.2 Edge Cases

**Aliquotation:**
- Person worked exactly 1 day (edge of semester)
- PersonRole with no end_date (ongoing)
- Multiple roles with overlapping periods
- Role start/end exactly match semester boundaries

**Synchronization:**
- Person with no approved requests (reimbursed_ects = 0)
- Person with reimbursements exceeding entitlement (remaining_ects = 0)
- Semester with negative bonus/malus (final_ects could be 0)
- Mixed requests (some approved, some not)

**Manual Review:**
- Edit entry, run synchronization → should skip
- Clear checked_at, run synchronization → should update
- Edit multiple ECTS fields in one save → checked_at set once

**Lock States:**
- Lock → verify → unlock → lock again (workflow restart)
- Approve → reject attempt (should fail)
- Verify sent without approval (should fail)

---

### 8.3 Performance Considerations

**Query Optimization:**

AuditSemesterAdmin queryset:

```python
qs.select_related('semester')
qs.annotate(_entry_count=Count('entries'))
```

AuditEntryAdmin queryset:

```python
qs.select_related('audit_semester__semester', 'person')
```

Synchronization queries:

```python
person_roles = PersonRole.objects.filter(...).select_related('person', 'role')
approved_requests.prefetch_related('courses')
entries.select_related(...).prefetch_related('person_roles', 'inbox_requests')
```

**Large Dataset Handling:**

- Synchronization is transactional (all-or-nothing)
- No batching for very large semesters (100+ people)
- Inline pagination (5 entries per page) for large audits

---

## 9. Integration Points

### 9.1 academia Module

**Dependencies:**

```python
from academia.models import Semester, InboxRequest
```

**Usage:**
- `AuditSemester.semester` OneToOne FK
- Synchronization filters to `APPROVE:CHAIR` requests
- Sums course ECTS from approved requests

---

### 9.2 people Module

**Dependencies:**

```python
from people.models import Person, PersonRole
```

**Usage:**
- `AuditEntry.person` FK
- `AuditEntry.person_roles` M2M
- Aliquotation calculations use PersonRole dates
- Find roles active during semester

---

### 9.3 hankosign Module

**Utilities Used:**

```python
from hankosign.utils import (
    state_snapshot,         # Get lock/approval state
    has_sig,               # Check signature exists
    record_signature,      # Create signature
    sign_once,             # Create windowed signature
    render_signatures_box, # Display in admin
    seal_signatures_context, # Prepare for PDF
    object_status_span,    # Status badge
)
```

**Integration:**
- Lock state controls editability
- Approval signatures control workflow progression
- verify_audit_complete requires VERIFY signature
- approve_audit requires APPROVE:CHAIR signature

---

### 9.4 annotations Module

**Integration:**

```python
from annotations.admin import AnnotationInline
from annotations.views import create_system_annotation
```

**Usage:**
- Both AuditSemester and AuditEntry have AnnotationInline
- System annotations on LOCK, UNLOCK, VERIFY, APPROVE, REJECT, synchronize

---

### 9.5 organisation Module

**Dependency:**

```python
from organisation.models import OrgInfo
```

Used in PDF generation for letterhead/contact info.

---

### 9.6 core Module

**Utilities:**

```python
from core.admin_mixins import (
    log_deletions,
    safe_admin_action,
    ImportExportGuardMixin,
    HistoryGuardMixin,
    with_help_widget,
)
from core.pdf import render_pdf_response
from core.utils.bool_admin_status import boolean_status_span
from core.utils.authz import is_academia_audit_manager
```

---

## 10. Workflow Examples

### 10.1 Standard Audit Process

```
Week 1: Create AuditSemester
   └─> AuditSemester created, unlocked

Week 2-4: Synchronize as inbox requests come in
   └─> Run synchronize_entries multiple times
   └─> Entries updated with latest calculations

Week 5: Lock and begin review
   └─> lock_audit action
   └─> Entries now locked for synchronization
   └─> Admin can still manually edit entries

Week 6: Manual review
   └─> Edit entry ECTS fields → checked_at auto-set
   └─> Entries with checked_at protected from future syncs
   └─> Add notes for special cases

Week 7: Verify complete
   └─> Ensure all entries have checked_at
   └─> verify_audit_complete action
   └─> VERIFY signature recorded

Week 8: Chair approval
   └─> approve_audit action
   └─> APPROVE:CHAIR signature recorded

Week 9: Send to university
   └─> Upload signed audit_pdf
   └─> verify_audit_sent action
   └─> audit_sent_university_at timestamp set
```

---

### 10.2 Correction Workflow

```
Scenario: Error found after verification

Option A: Minor correction (entry-level)
1. Don't unlock audit
2. Edit specific entry directly
3. checked_at is updated
4. Entry protected from future syncs
5. Re-verify if needed (requires unlock → verify)

Option B: Major correction (requires re-sync)
1. unlock_audit
2. Clear checked_at on affected entries
3. Fix underlying data (PersonRole, InboxRequest)
4. synchronize_entries
5. lock_audit
6. verify_audit_complete again
```

---

## 11. File Structure

```
academia_audit/
├── __init__.py
├── models.py              # AuditSemester, AuditEntry
├── admin.py               # Admin interfaces with workflow actions
├── utils.py               # Aliquotation & synchronization logic
├── apps.py
├── tests.py
└── migrations/
    ├── 0001_initial.py
    ├── 0002_initial.py    # FK constraints
    ├── 0003_*.py          # audit_generated_at field
    ├── 0004_*.py          # Remove notes field (moved?)
    └── 0005_*.py          # FileField validators
```

---

## 12. Common Pitfalls

1. **Don't assume sum** - Multiple roles → MAXIMUM, not sum
2. **checked_at is protection** - Must clear to allow re-sync
3. **Lock timing matters** - Synchronize before locking, not after
4. **Approval chain required** - Can't verify_sent without approval
5. **Date inclusivity** - Both start and end dates are inclusive in calculations
6. **Negative handling** - System prevents but validate at boundaries
7. **OneToOne constraint** - Can't create multiple audits for same semester
8. **Signature filtering** - Only APPROVE:CHAIR requests count, not just stage
9. **Transactional sync** - All-or-nothing, no partial updates
10. **Lock cascades** - Parent lock affects all children

---

**Version:** 1.0.5  
**Last Updated:** 2025-12-08  
**Author:** Sven (vas)