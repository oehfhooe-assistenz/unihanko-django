# PEOPLE.md

**Module:** `people`  
**Purpose:** Personnel management - people, roles, and role assignments with lifecycle tracking  
**Version:** 1.0.3 (models), 1.0.0 (admin)  
**Dependencies:** Django auth (User), assembly (SessionItem for elections)

---

## 1. Overview

The people module is a core tentpole of UniHanko, managing personnel records, organizational roles, and time-bound role assignments. It provides:

- **Person records** - Individual personnel with contact info, matriculation numbers, and access codes
- **Role definitions** - Organizational positions with ECTS caps, stipend settings, and type classification
- **PersonRole assignments** - Time-bound assignments with start/end dates, reasons, and election tracking
- **Transition reasons** - Dictionary of coded reasons for starting/ending assignments (I##/O##/C##/X99)
- **Access control** - Lock/unlock mechanism via HankoSign workflow
- **Certificate generation** - PDF certificates for appointments, confirmations, and resignations

The module enforces business rules around elected positions, stipend eligibility, and assignment lifecycle management.

---

## 2. Models

### 2.1 Person

**Purpose:** Individual personnel record with identity, contact, and access code.

**Gender Enum:**

```python
class Gender(models.TextChoices):
    M = "M", _("Male")
    F = "F", _("Female")
    D = "D", _("Diverse")
    X = "X", _("Not specified")
```

**Fields:**

**Identity:**
- `uuid`: UUIDField default=uuid4 unique editable=False - stable system identifier
- `first_name`: CharField(80) - first name
- `last_name`: CharField(80) - last name
- `gender`: CharField(1) choices=Gender default=X

**Contact:**
- `email`: EmailField blank - primary email
- `student_email`: EmailField blank - student email (if applicable)

**University:**
- `matric_no`: CharField(12) nullable blank - matriculation number
  - Format: `s` + 10 digits (FH) OR up to 10 digits (federal)
  - Examples: s2210562023, 52103904
  - Validation: `^([sS]\d{9,10}|\d{1,10})$`

**Account:**
- `user`: OneToOneField(User) nullable SET_NULL - linked Django user account

**Access Control:**
- `personal_access_code`: CharField(19) unique blank - public filing access code
  - Auto-generated on creation (format: ABCD-EFGH)
  - Used for external filing systems (payment plans, etc.)

**Lifecycle:**
- `is_active`: BooleanField default=True - active status
- `notes`: TextField blank - record notes

**System:**
- `created_at`, `updated_at`: DateTimeField auto
- `history`: HistoricalRecords
- `version`: AutoIncVersionField (concurrency control)

**Constraints:**

UniqueConstraint (conditional):
- `matric_no` unique when not null (uq_person_matric_no)
- `email` unique when not null and not empty (uq_person_email)

**Indexes:**
- (last_name, first_name)
- (matric_no)

**Ordering:** ["last_name", "first_name"]

**String Representation:** "Last, First"

---

### 2.2 Person Methods

**clean():**

No specific validation beyond base (placeholder for future rules).

**save():**

On creation:
1. **Auto-generates personal_access_code** if not set
2. **Atomic matric_no duplicate check:**
   - select_for_update() lock
   - Prevents concurrent matric_no collisions
   - Raises ValidationError if duplicate

**Access Code Generation:**

```python
_ACCESS_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
```
Excludes ambiguous characters (0/O, 1/I/l).

```python
@classmethod
def _generate_access_code(cls, groups=2, chars_per_group=4) -> str
```
Default: XXXX-XXXX (8 chars + hyphen).

```python
@classmethod
def _generate_unique_access_code(cls) -> str
```
- Tries 20 times with 2 groups
- Falls back to 3 groups if collision
- Raises ValidationError if all fail

```python
def regenerate_access_code(self, *, commit=True) -> str
```
Manually regenerate code (managers only via admin action).

---

### 2.3 Role

**Purpose:** Organizational position definition with financial and administrative properties.

**Kind Enum:**

```python
class Kind(models.TextChoices):
    DEPT_HEAD = "DEPT. HEAD", _("Department head (Referent:in)")
    DEPT_CLERK = "DEPT. CLERK", _("Department clerk (Sachbearbeiter:in)")
    OTHER = "OTHER", _("Other / miscellaneous")
```

**Fields:**

**Identity:**
- `name`: CharField(100) unique - full role name
- `short_name`: CharField(30) blank - short form (e.g., WiRef)
  - Validation: no digits, max 30 chars (`^\D{1,30}$`)

**Classification:**
- `kind`: CharField(16) choices=Kind default=OTHER indexed - role type
- `is_elected`: BooleanField default=False - elected position
- `is_system`: BooleanField default=False - internal/admin role
- `is_stipend_reimbursed`: BooleanField default=False - eligible for stipend (FuGeb)

**Defaults:**
- `ects_cap`: DecimalField(4,1) default=0 - nominal reimbursable ECTS
- `default_monthly_amount`: DecimalField(10,2) nullable - default monthly stipend

**Notes:**
- `notes`: TextField blank - configuration notes

**System:**
- `history`: HistoricalRecords
- `version`: AutoIncVersionField

**Constraints:**

CheckConstraint:
- `ck_system_kind_other`: System roles must have kind=OTHER

**Ordering:** ["name"]

**String Representation:** Role name

---

### 2.4 Role Properties & Methods

**kind_label (property):**

```python
@property
def kind_label(self) -> str
```
Returns "Other/System" if kind=OTHER and is_system, else normal kind display.

**is_financially_relevant (property):**

```python
@property
def is_financially_relevant(self) -> bool
```
Returns True if is_stipend_reimbursed and NOT is_system.

**clean():**

Validates system role constraints:
- System roles must use kind=OTHER
- System roles cannot be stipend-reimbursed
- System roles must have default_monthly_amount=null
- System roles must have ects_cap=0

Raises ValidationError with specific field errors.

---

### 2.5 RoleTransitionReason

**Purpose:** Dictionary of coded reasons for assignment lifecycle events.

**Code Pattern:**
- `I##` - Start reasons (Ixx: entry, joining)
- `O##` - End reasons (Oxx: exit, leaving)
- `C##` - Change reasons (Cxx: modifications)
- `X99` - Other (catch-all)

**Fields:**
- `code`: CharField(4) unique - stable code (I01, O01, C99, X99)
  - Validation: `^(?:[IOC]\d{2}|X99)$` (case-insensitive)
- `name`: CharField(120) - German label
- `name_en`: CharField(120) blank - English label (optional)
- `active`: BooleanField default=True - active status

**Ordering:** ["code"]

**String Representation:** "{code} — {display_name}"

**display_name (property):**

```python
@property
def display_name(self) -> str
```
Returns name_en if current language is English, else name (with fallback).

**clean():**

Normalizes code to uppercase.

**save():**

Uppercases code before save.

---

### 2.6 PersonRole

**Purpose:** Time-bound assignment of Person to Role with lifecycle tracking.

**Fields:**

**Scope:**
- `person`: FK(Person, PROTECT) - assigned person
- `role`: FK(Role, PROTECT) - assigned role

**Core Dates:**
- `start_date`: DateField - assignment start
- `end_date`: DateField nullable - assignment end (null = active)

**Effective Dates (Optional):**
- `effective_start`: DateField nullable - official/legal start
- `effective_end`: DateField nullable - official/legal end

**Reasons:**
- `start_reason`: FK(RoleTransitionReason) nullable SET_NULL - why started (I##)
- `end_reason`: FK(RoleTransitionReason) nullable SET_NULL - why ended (O##)

**Election Details:**
- `confirm_date`: DateField nullable - assembly confirmation date
- `elected_via`: FK(assembly.SessionItem) nullable SET_NULL - confirming session item

**Notes:**
- `notes`: TextField blank - record notes

**System:**
- `created_at`, `updated_at`: DateTimeField auto
- `history`: HistoricalRecords
- `version`: AutoIncVersionField

**Constraints:**

UniqueConstraint:
- (person, role, start_date) - prevents duplicate assignments

CheckConstraints:
1. `ck_assignment_dates`: end_date >= start_date (or null)
2. `ck_effective_after_start`: effective_start >= start_date (or null)
3. `ck_effective_order`: effective_end >= effective_start (or both null)
4. `ck_end_reason_iff_end_date`: (end_date is null) ⟺ (end_reason is null)
5. `ck_confirm_after_start`: confirm_date >= start_date (or null)

**Indexes:**
- (effective_start)
- (effective_end)
- (effective_start, effective_end)
- (person, end_date)

**Ordering:** ["-start_date", "-id"] (newest first)

**String Representation:** "Person — Role (start -> end)"

---

### 2.7 PersonRole Properties & Methods

**is_active (property):**

```python
@property
def is_active(self) -> bool
```
Returns True if end_date is null.

**save():**

On creation:
- **Atomic duplicate check** for (person, role, start_date)
- select_for_update() lock prevents race conditions
- Raises ValidationError if duplicate

**clean():**

Comprehensive validation:

1. **System role restrictions:**
   - Cannot have confirm_date or elected_via
   - Cannot have effective_start or effective_end
   - Uses start_date and end_date only

2. **Reason format validation:**
   - start_reason must be I## or X99
   - end_reason must be O## or X99

3. **Date-reason coupling:**
   - end_date requires end_reason (and vice versa)

4. **Reason uniqueness:**
   - start_reason != end_reason (except both X99)

5. **Election validation:**
   - elected_via requires confirm_date

Raises ValidationError with per-field errors.

---

## 3. Admin Interface

### 3.1 Import/Export Resources

**PersonResource:**
- Fields: id, uuid, names, emails, matric_no, gender, is_active, dates, notes
- Export-only (import disabled for safety)

**RoleResource:**
- Fields: id, name, short_name, ects_cap, flags, kind, monthly_amount, notes
- Full import/export

**RoleTransitionReasonResource:**
- Fields: id, code, name, name_en, active
- Full import/export

**PersonRoleResource:**
- Fields: id, person_id, role_id, dates, reasons (as codes), confirm_date, elected_via_code, notes
- Special: Exports reason codes (I01, O01) and session item codes
- Import: Accepts reason codes and resolves to IDs

---

### 3.2 Custom List Filters

**ActiveAssignmentFilter (Person):**
- Parameter: active_assign
- Options: Yes (has active assignment), No (all ended)
- Filters: role_assignments__end_date__isnull

**ActiveFilter (PersonRole):**
- Parameter: active
- Options: Active (end_date=null), Ended (end_date!=null)

---

### 3.3 Inlines

**PersonRoleInline:**
- Type: StackedInlinePaginated (per_page=1)
- Parent: Person
- Shows: All PersonRole fields with HankoSign signatures
- Autocomplete: role, reasons, elected_via
- Readonly: person, role (after creation)
- Can delete: False (preserves history)
- Lock-aware: Respects parent Person lock status

**AnnotationInline:**
- Included in Person and PersonRole admins
- Allows commenting on records

---

### 3.4 Person Admin

**Registration:** `@admin.register(Person)`

**Base Classes:**
- SimpleHistoryAdmin - history tracking
- DjangoObjectActions - object action buttons
- ImportExportModelAdmin - CSV/Excel
- ConcurrentModelAdmin - optimistic locking
- ImportExportGuardMixin, HistoryGuardMixin

**List Display:**
- last_name, first_name, mail_merged (dual email), mat_no_display
- acc_check (🔗 if Django account linked), is_active
- active_roles (prefetched), updated_at, active_text (lock status)

**Filters:**
- ActiveAssignmentFilter, gender, is_active

**Search:**
- first_name, last_name, email, student_email, matric_no

**Autocomplete:**
- user (Django User)

**Readonly:**
- uuid, personal_access_code, created_at, updated_at, signatures_box, mail_merged

**Fieldsets:**

1. **Scope:** first_name, last_name, uuid, gender, is_active
2. **Contact:** email, student_email
3. **University:** matric_no
4. **Account:** user
5. **Personal Access Code:** personal_access_code
6. **Notes:** notes
7. **Workflow & HankoSign:** signatures_box
8. **System:** version, created_at, updated_at

**Inlines:**
- PersonRoleInline (paginated), AnnotationInline

**Computed Displays:**

**mail_merged:**
- Template: admin/people/_mail_cell.html
- Shows email and student_email in formatted cell

**mat_no_display:**
- Returns matric_no value

**acc_check:**
- 🔗 if user linked, ❌ otherwise

**active_text:**
- Shows lock status: Open (green) / Locked (red)

**active_roles:**
- Prefetched active assignments, shows role names

**signatures_box:**
- HankoSign signature audit trail

**Queryset Optimization:**
- Prefetches active role_assignments with role

**Permissions:**
- No delete (preserves personnel records)

---

### 3.5 Person Admin - Object Actions

**lock_person:**
- Creates LOCK:-@people.person signature
- Creates system annotation
- Message: "Locked." or "Already locked."
- Label: "Lock record"
- Color: Secondary (gray)

**unlock_person:**
- Creates UNLOCK:-@people.person signature
- Creates system annotation
- Message: "Unlocked." or "Not locked."
- Label: "Unlock record"
- Color: Warning (yellow)

**print_person:**
- Creates RELEASE:-@people.person signature (idempotent)
- Template: people/person_pdf.html
- Filename: HR-P_AKT_{id}_{lastname}_{date}.pdf
- Label: "🖨️ Print Personnel Record PDF"
- Color: Info (cyan)
- onclick: RID_JS (idempotency)

**print_pac:**
- Managers only
- Prints personal access code info with attestation seal
- Template: people/person_action_code_notice_pdf.html
- Filename: HR-P_PAC_INFO_{id}_{lastname}_{date}.pdf
- Label: "🖨️ Print Personal Access Code Info PDF (ext.)"
- Color: Info (cyan)

**regenerate_access_code:**
- Managers only
- JavaScript confirm: "Regenerate the access code for this person? The old code will stop working."
- Generates new unique code
- Creates RELEASE signature
- Shows new code in success message
- Label: "🔐 Regenerate access code"
- Color: Danger (red)

**Action Visibility:**
- Managers: All actions
- Non-managers: print_person only
- Locked state: Show unlock (hide lock), or vice versa

---

### 3.6 Person Admin - Bulk Actions

**lock_selected:**
- Bulk lock operation
- Skips already-locked
- Creates LOCK signature + annotation for each
- Reports: "locked N, already locked N, failed N"

**unlock_selected:**
- Bulk unlock operation
- Skips already-unlocked
- Creates UNLOCK signature + annotation for each
- Reports: "unlocked N, already unlocked N, failed N"

**export_selected_pdf:**
- Generates roster PDF for selected people
- Creates RELEASE signature for each (non-blocking)
- Template: people/people_list_pdf.html
- Filename: HR-P_SELECT_{date}.pdf
- Orders by last_name, first_name

**Bulk Action Visibility:**
- Managers only

---

### 3.7 Person Admin - Lock Behavior

**Lock Detection:**

```python
def _is_locked(self, request, obj)
```
- Checks state_snapshot(obj) for explicit_locked
- Managers bypass (always False for them)

**Readonly When Locked:**
- Fields: first_name, last_name, email, student_email, matric_no, gender, notes, user, is_active
- Inline: PersonRoleInline becomes readonly

**Row Attributes:**
- data-state="ok" (open) or data-state="locked"
- CSS targeting for visual indication

---

### 3.8 Role Admin

**Registration:** `@admin.register(Role)`

**Base Classes:**
- SimpleHistoryAdmin, ImportExportModelAdmin, ConcurrentModelAdmin
- ImportExportGuardMixin, HistoryGuardMixin

**List Display:**
- name, short_name, ects_cap, is_elected, is_stipend_reimbursed, kind_text, is_system

**Search:**
- name

**Filters:**
- is_elected, is_stipend_reimbursed, is_system, kind

**Fieldsets:**

1. **Scope:** name, short_name
2. **Type & Flags:** kind, is_system, is_elected, is_stipend_reimbursed
3. **Defaults:** ects_cap, default_monthly_amount
4. **Notes:** notes
5. **System:** version

**Computed Display:**

**kind_text:**
- Template: admin/people/_role_kind.html
- Shows kind with "Other/System" for system roles

**Permissions:**
- No delete (preserves role definitions)
- Managers only (hidden from sidebar for others)

---

### 3.9 RoleTransitionReason Admin

**Registration:** `@admin.register(RoleTransitionReason)`

**Base Classes:**
- ImportExportModelAdmin, ImportExportGuardMixin

**List Display:**
- code, name_localized (current language), active

**Filters:**
- active

**Search:**
- code, name, name_en

**Readonly After Creation:**
- code, name (prevents renumbering chaos)

**Computed Display:**

**name_localized:**
- Shows display_name (language-aware)

**Permissions:**
- No delete (dictionary preservation)
- Managers only (hidden from sidebar)

---

### 3.10 PersonRole Admin

**Registration:** `@admin.register(PersonRole)`

**Base Classes:**
- SimpleHistoryAdmin, DjangoObjectActions, ImportExportModelAdmin
- ConcurrentModelAdmin, ImportExportGuardMixin, HistoryGuardMixin

**List Display:**
- person, role, start_merged (date + reason), confirm_date
- end_merged (date + reason), updated_at, active_text

**Filters:**
- ActiveFilter, role, start_reason, end_reason, dates

**Search:**
- person names, role name, notes

**Autocomplete:**
- person, role, start_reason, end_reason, elected_via

**Readonly:**
- signatures_box, election_reference, created_at, updated_at

**Fieldsets:**

1. **Scope:** person, role
2. **Dates:** start_date, effective_start, end_date, effective_end
3. **Reasons:** start_reason, end_reason
4. **Election Details:** confirm_date, elected_via, election_reference
5. **Notes:** notes
6. **Workflow & HankoSign:** signatures_box
7. **System:** version, created_at, updated_at

**Inlines:**
- AnnotationInline

**Computed Displays:**

**start_merged / end_merged:**
- Template: admin/people/_date_reason_cell.html
- Shows date (effective or actual) with reason
- Visual indicator if effective date used

**election_reference:**
- Link to assembly.SessionItem if elected_via set
- Shows full session item identifier

**active_text:**
- Active (green) / Ended (gray) badge

**Queryset Optimization:**
- Annotates start_display = Coalesce(effective_start, start_date)
- Annotates end_display = Coalesce(effective_end, end_date)

**FY-Aware Search:**
- GET parameter: ?fy={fiscal_year_id}
- Filters assignments overlapping fiscal year
- Used by payment plan autocomplete

**Permissions:**
- No delete (preserves assignment history)

**Lock Behavior:**
- Respects parent Person lock
- Managers bypass
- Readonly fields when locked

---

### 3.11 PersonRole Admin - Object Actions

**print_appointment_regular:**
- Managers only
- For DEPT_CLERK and OTHER roles
- Template: people/certs/appointment_regular.html
- Filename: B_{role}_{lastname}-{date}.pdf
- Label: "🧾 Print certificate (non-conf.) PDF"
- Color: Warning (yellow)

**print_appointment_ad_interim:**
- Managers only
- For DEPT_HEAD roles (before confirmation)
- Template: people/certs/appointment_ad_interim.html
- Filename: B_interim_{role}_{lastname}-{date}.pdf
- Label: "💥 Print certificate (ad interim) PDF"
- Color: Warning (yellow)

**print_confirmation:**
- Managers only
- For DEPT_HEAD roles (after confirmation)
- Requires: confirm_date set, role.kind=DEPT_HEAD
- Template: people/certs/appointment_confirmation.html
- Filename: B_Beschluss_{ref}_{role}_{lastname}-{date}.pdf
- Label: "☑️ Print certificate (post-conf.) PDF"
- Color: Warning (yellow)

**print_resignation:**
- Managers only
- For ended assignments (end_date set)
- Template: people/certs/resignation.html
- Filename: R_{role}_{lastname}-{date}.pdf
- Label: "🏁 Print resignation PDF"
- Color: Warning (yellow)

**All Certificate Actions:**
- Create RELEASE:-@people.person signature (on parent Person)
- Idempotent (sign_once with RID_JS)
- Include org context from OrgInfo

**Action Visibility:**
- Managers only
- regular: DEPT_CLERK and OTHER
- ad_interim + confirmation: DEPT_HEAD only
- resignation: Only if end_date set

---

### 3.12 PersonRole Admin - Bulk Actions

**offboard_today:**
- Sets end_date = today for active assignments
- Auto-sets end_reason to O01 (Austritt) or X99 (fallback) if missing
- Reports: "Ended N active assignment(s)."
- Requires: O01 or X99 reason seeded

---

### 3.13 PersonRole Admin - Special Features

**Person Autocomplete Filtering:**
- Non-managers: Only shows unlocked People
- Python-side check via state_snapshot()
- Conservative: Excludes on error

**Save Protection:**
- Final server-side check: Blocks save if Person locked (non-managers)
- Raises PermissionDenied

**Readonly Logic:**
- person, role: Readonly after creation
- Lock cascades to all date/reason/note fields

---

## 4. Workflow Patterns

### 4.1 Person Lifecycle

**Creation:**
1. Add Person via admin
2. personal_access_code auto-generated
3. Optionally link Django User account
4. Optionally add matric_no (validated, unique)

**Assignment:**
1. Add PersonRole via inline or direct admin
2. Set person, role, start_date
3. Optionally set effective_start (official date)
4. Set start_reason (I##)
5. Optionally set confirm_date + elected_via (for elected roles)

**Offboarding:**
1. Set end_date (or use bulk offboard_today action)
2. Set end_reason (O##) - required with end_date
3. Optionally set effective_end

**Lock/Unlock:**
1. Lock Person (LOCK signature)
2. All assignments become readonly
3. Managers can still edit
4. Unlock to re-enable editing

---

### 4.2 Certificate Generation

**Non-Confirmation Appointment (Regular):**
- Role: DEPT_CLERK or OTHER
- Use: print_appointment_regular
- Certificate: Bestellung (non-confirmation)

**Ad Interim Appointment:**
- Role: DEPT_HEAD (before confirmation)
- Use: print_appointment_ad_interim
- Certificate: Bestellung ad interim

**Post-Confirmation:**
- Role: DEPT_HEAD (after assembly confirmation)
- Requires: confirm_date + elected_via
- Use: print_confirmation
- Certificate: Bestätigung nach Beschluss

**Resignation:**
- Any ended assignment
- Requires: end_date
- Use: print_resignation
- Certificate: Rücktritt

---

### 4.3 Reason Codes

**Start Reasons (I##):**
- I01: Eintritt (Entry)
- I02: Wiedereintritt (Re-entry)
- X99: Other

**End Reasons (O##):**
- O01: Austritt (Exit)
- O02: Rücktritt (Resignation)
- O03: Amtszeitende (Term end)
- X99: Other

**Change Reasons (C##):**
- C01: Rollenwechsel (Role change)
- X99: Other

**Validation:**
- start_reason: Must be I## or X99
- end_reason: Must be O## or X99
- Cannot be same (except both X99)

---

## 5. Access Code System

### 5.1 Generation

**Algorithm:**
- Alphabet: ABCDEFGHJKLMNPQRSTUVWXYZ23456789 (excludes 0/O, 1/I/l)
- Default: 2 groups × 4 chars = XXXX-XXXX
- Fallback: 3 groups × 4 chars = XXXX-XXXX-XXXX
- Collision retry: 20 attempts per format

**Uniqueness:**
- Checked against existing codes
- Extremely low collision probability
- Raises ValidationError if all attempts fail

---

### 5.2 Usage

**Purpose:**
- External filing systems (payment plans, ECTS)
- Public-facing URLs without authentication
- Shared with personnel for self-service

**Regeneration:**
- Managers only
- JavaScript confirm warning
- Old code immediately invalidated
- New code shown in success message

**Security:**
- 32-bit entropy (8 chars × 32-char alphabet)
- No sequential guessing
- One-time share recommended

---

## 6. Business Rules

### 6.1 System Roles

**Definition:** Internal/admin roles (is_system=True)

**Restrictions:**
- Must have kind=OTHER
- Cannot be stipend-reimbursed
- Must have ects_cap=0
- Must have default_monthly_amount=null
- Cannot have confirm_date or elected_via
- Cannot have effective dates (use start/end only)

**Use Cases:**
- Technical admin
- System accounts
- Non-personnel roles

---

### 6.2 Elected Positions

**Definition:** Roles with is_elected=True

**Requirements:**
- Must have confirm_date when assembly-confirmed
- Can have elected_via (session item link)
- Can print confirmation certificate (DEPT_HEAD only)

**Workflow:**
1. Initial appointment (ad interim if DEPT_HEAD)
2. Assembly confirmation
3. Set confirm_date + elected_via
4. Print post-confirmation certificate

---

### 6.3 Stipend Eligibility

**Definition:** is_stipend_reimbursed=True AND is_system=False

**Properties:**
- default_monthly_amount can be set
- Used by finances module for payment plans
- Excluded if is_system

**is_financially_relevant property:**
- True if eligible for stipend
- Used by payment plan workflows

---

### 6.4 Date Constraints

**Core Dates:**
- end_date >= start_date (always)
- end_date null = active assignment

**Effective Dates:**
- effective_start >= start_date (if set)
- effective_end >= effective_start (if both set)
- Display: Coalesce(effective, actual)

**Confirmation:**
- confirm_date >= start_date (if set)

---

## 7. Configuration

### 7.1 Django Settings

**INSTALLED_APPS:**

```python
INSTALLED_APPS = [
    # ...
    "people",
    "hankosign",  # For signatures
    "annotations",  # For comments
    "assembly",  # For elected_via
    # ...
]
```

---

### 7.2 Bootstrap Requirements

**Actions (HankoSign):**

```
LOCK:-@people.person
UNLOCK:-@people.person
RELEASE:-@people.person
```

**Reasons (RoleTransitionReason):**

Minimal set:
- I01: Eintritt (Entry)
- O01: Austritt (Exit)
- X99: Sonstiges (Other)

**Roles:**

Define organizational structure before assignments.

---

## 8. Dependencies

**Django Framework:**
- Django auth (User model)
- ContentType framework

**Internal Modules:**
- hankosign (LOCK/UNLOCK/RELEASE actions)
- annotations (comments on records)
- assembly (SessionItem for elected_via)
- organisation (OrgInfo for PDFs)
- finances (FiscalYear for FY-aware filters)

**External Packages:**
- simple_history - model history
- django-object-actions - admin action buttons
- import_export - CSV/Excel
- concurrency - optimistic locking
- django_admin_inline_paginator_plus - paginated inlines

**Core Utilities:**
- core.pdf - PDF generation
- core.admin_mixins - guards, safe actions, help widgets
- core.utils.authz - is_people_manager()
- core.utils.bool_admin_status - status badges

---

## 9. Notes

**No Delete Permission:**
- Person: Preserves personnel records
- Role: Preserves role definitions
- PersonRole: Preserves assignment history
- RoleTransitionReason: Preserves reason dictionary

**Lock Cascade:**
- LOCK:-@people.person signature
- Affects Person and all PersonRole inlines
- Managers bypass
- UNLOCK re-enables editing

**Concurrency:**
- AutoIncVersionField on all models
- Atomic duplicate checks on save
- select_for_update() for race prevention

**History Tracking:**
- simple_history on all models
- Audit trail for all changes
- Preserved even when records "deleted" (via is_active=False)

**Import/Export:**
- Person: Export only (no import for safety)
- Role: Full import/export
- PersonRole: Exports reason codes, imports by code
- RoleTransitionReason: Full import/export

**Manager Privileges:**
- Lock/unlock people
- Regenerate access codes
- Print PAC info PDFs
- Print all certificates
- Bypass lock restrictions

**Prefetching:**
- Person admin: Prefetches active assignments
- Optimizes "active_roles" display
- No N+1 queries

**Templates:**
- admin/people/_mail_cell.html - dual email display
- admin/people/_role_kind.html - role kind badge
- admin/people/_date_reason_cell.html - date + reason display
- people/person_pdf.html - personnel dossier
- people/person_action_code_notice_pdf.html - PAC info
- people/people_list_pdf.html - roster
- people/certs/appointment_regular.html - non-confirmation
- people/certs/appointment_ad_interim.html - ad interim
- people/certs/appointment_confirmation.html - post-confirmation
- people/certs/resignation.html - resignation

---

## 10. File Structure

```
people/
├── __init__.py
├── apps.py                          # Standard config
├── models.py                        # 502 lines
│   ├── Person (identity + access code)
│   ├── Role (org positions)
│   ├── RoleTransitionReason (I/O/C/X codes)
│   └── PersonRole (time-bound assignments)
├── admin.py                         # 1141 lines
│   ├── Import/Export resources (4)
│   ├── Custom filters (2)
│   ├── PersonRoleInline
│   ├── PersonAdmin (lock/unlock, PDFs)
│   ├── RoleAdmin
│   ├── RoleTransitionReasonAdmin
│   └── PersonRoleAdmin (certificates, offboard)
├── views.py                         # Empty placeholder
├── urls.py                          # Empty (404)
└── tests.py                         # Test suite (24K)
```

Total lines: ~1,643 (excluding tests)

---

**Version:** 1.0.5  
**Last Updated:** 2025-12-08  
**Author:** Sven (vas)