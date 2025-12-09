# FINANCES.md

**Module:** `finances`  
**Purpose:** Fiscal year management and payment plan workflows for function fees (Funktionsgebühren)  
**Version:** 1.0.1 (models), 1.0.0 (admin)  
**Dependencies:** people.PersonRole, hankosign, annotations, organisation.OrgInfo

---

## 1. Overview

The finances module manages fiscal year periods and payment plans for student union personnel receiving regular function fees. It provides:

- **Fiscal year management** with start/end dates and active year tracking
- **Payment plan workflows** from draft through approval to activation
- **30-day proration** for partial-month payments (accounting standard)
- **Banking verification** before payments become active
- **Year-end locking** to freeze all plans in a closed fiscal year
- **Portal submission** tracking for payee-completed forms

---

## 2. Models

### 2.1 Helper Functions

```python
def calculate_proration_breakdown(
    start: date,
    end: date,
    *,
    accounting_month_days: int = 30
) -> list[dict]
```

**Purpose:** Calculate monthly proration breakdown for a date range using fixed accounting month (30 days).

**Arguments:**
- `start`: First day of coverage (inclusive)
- `end`: Last day of coverage (inclusive, day 1 normalized to previous month end)
- `accounting_month_days`: Days per month for proration (default 30)

**Returns:** List of dicts with keys:
- `year` (int): Calendar year
- `month` (int): Calendar month
- `days` (int): Actual calendar days covered in that month
- `month_days` (int): Actual calendar days in that month
- `fraction` (Decimal): days / accounting_month_days (quantized to 0.0001)

**Example:**
```python
calculate_proration_breakdown(date(2024, 7, 15), date(2024, 9, 14))
# [
#     {"year": 2024, "month": 7, "days": 17, "month_days": 31, "fraction": Decimal("0.5667")},
#     {"year": 2024, "month": 8, "days": 31, "month_days": 31, "fraction": Decimal("1.0333")},
#     {"year": 2024, "month": 9, "days": 14, "month_days": 30, "fraction": Decimal("0.4667")},
# ]
```

**Normalization:** If `end.day == 1`, treated as last day of previous month.

```python
def auto_end_from_start(start: date) -> date
```
Returns end date = one year minus one day after start. Robust across leap years.

```python
def default_start() -> date
```
Returns FY start containing today (July 1 boundary): if today >= July 1, use current year; else use previous year.

```python
def stored_code_from_dates(start: date, end: date) -> str
```
Generate German-style fiscal year code: `WJ24_25` (Wirtschaftsjahr = business year).

```python
def localized_code(start: date, end: date, lang: str | None = None) -> str
```
Display code based on language:
- English: `FY24_25` (Fiscal Year)
- German/other: `WJ24_25` (Wirtschaftsjahr)

---

### 2.2 Payment Plan Status Machine

```python
def paymentplan_status(pp: PaymentPlan) -> str
```

**Purpose:** Determine PaymentPlan workflow status from HankoSign signatures and dates.

**Returns:** One of:
- `DRAFT`: No SUBMIT signature (or withdrawn)
- `PENDING`: Submitted but missing APPROVE:WIREF, APPROVE:CHAIR, or VERIFY:WIREF
- `ACTIVE`: All approvals + verify done, within date range
- `FINISHED`: All approvals + verify done, past end date
- `CANCELLED`: REJECT signature exists

**Logic Flow:**
1. If rejected → `CANCELLED` (terminal)
2. If not submitted → `DRAFT`
3. If submitted but missing WIREF approval → `PENDING`
4. If submitted but missing CHAIR approval → `PENDING`
5. If approvals done but missing VERIFY:WIREF → `PENDING`
6. If all complete and past end date → `FINISHED`
7. If all complete and within date range → `ACTIVE`

---

### 2.3 FiscalYear

**Purpose:** Define fiscal year periods for payment plan organization and year-end locking.

**Fields:**
- `code`: CharField(20) unique - auto-generated WJyy_yy format
- `label`: CharField(200) blank - optional descriptive label
- `start`: DateField - fiscal year start (typically July 1)
- `end`: DateField nullable - fiscal year end (auto-calculated if not provided)
- `is_active`: BooleanField default=False unique_if_true - current fiscal year marker
- `created_at`, `updated_at`: DateTimeField auto

**Unique Constraint:** Only one FiscalYear can have `is_active=True` at a time.

**Methods:**

```python
def display_code(self, lang: str | None = None) -> str
```
Returns localized code: `FY24_25` (en) or `WJ24_25` (de/other).

```python
def clean(self)
```
Validation:
- Ensures `end >= start` if both set
- Auto-fills `end` from `start` if missing (one year minus one day)
- Auto-generates `code` from dates if missing

```python
def save(self, *args, **kwargs)
```
On creation:
1. Auto-fills `end` from `start` if not set
2. Auto-generates `code` from dates if not set

**History:** simple_history tracked

**Workflow:** Can be locked via LOCK:-@finances.fiscalyear signature (cascades to all PaymentPlans).

---

### 2.4 PaymentPlan

**Purpose:** Payment plan for function fees with approval workflow, banking details, and proration.

**Status Enum:**

```python
class Status(models.TextChoices):
    DRAFT = "DRAFT", _("Draft")
    PENDING = "PENDING", _("Pending Approval")
    ACTIVE = "ACTIVE", _("Active")
    FINISHED = "FINISHED", _("Finished")
    CANCELLED = "CANCELLED", _("Cancelled")
```

**Fields:**

**Scope:**
- `plan_code`: CharField(80) unique blank - auto-generated WJyy_yy-00001 format
- `person_role`: ForeignKey(PersonRole, PROTECT) - assignment receiving payment
- `fiscal_year`: ForeignKey(FiscalYear, PROTECT) - containing fiscal year
- `cost_center`: CharField(60) blank - budget allocation code

**Budget:**
- `monthly_amount`: DecimalField(10,2) nullable - monthly function fee amount
- `total_override`: DecimalField(12,2) nullable - manual override of calculated total

**Payment Window:**
- `pay_start`: DateField nullable - payment start (auto-filled from PersonRole ∩ FiscalYear)
- `pay_end`: DateField nullable - payment end (auto-filled from PersonRole ∩ FiscalYear)

**Banking:**
- `payee_name`: CharField(200) blank - account holder name
- `iban`: CharField(34) blank - IBAN (mod-97 validated)
- `bic`: CharField(11) blank - BIC/SWIFT code
- `address`: TextField blank - payee postal address
- `reference`: CharField(160) default="Funktionsgebühr" - payment reference text

**Submission (from portal):**
- `signed_person_at`: DateTimeField nullable - when payee signed
- `pdf_file`: FileField nullable upload_to="finances/paymentplans/" - signed PDF from portal
- `submission_ip`: GenericIPAddressField nullable - IP address of portal submission

**Workflow:**
- `status`: CharField(20) default=DRAFT - computed from signatures

**System:**
- `status_note`: TextField blank - manual notes about status changes
- `created_at`, `updated_at`: DateTimeField auto
- `version`: AutoIncVersionField - concurrency control

**Constraints:**
- unique_together: (person_role, fiscal_year) for non-finished/cancelled plans (enforced in clean())
- check: pay_end >= pay_start (if both set)
- check: monthly_amount >= 0 (if set)

**Indexes:**
- person_role, fiscal_year, plan_code

**Methods:**

```python
def resolved_window(self) -> tuple[date, date]
```
Compute effective payment window clamped to FiscalYear bounds:
1. Start = max(pay_start or PersonRole.start, fiscal_year.start)
2. End = min(pay_end or PersonRole.end, fiscal_year.end)

Returns (start, end) tuple.

```python
def months_breakdown(self) -> list[dict]
```
Calculate 30-day proration breakdown for the resolved window.

Returns list of dicts with keys:
- year, month, days, month_days, fraction (from helper)
- amount: monthly_amount × fraction (quantized to 0.01)

```python
def recommended_total(self) -> Decimal
```
Sum of all prorated month amounts ("richtwert" = guideline value).

```python
@property
def effective_total(self) -> Decimal
```
Returns total_override if set, otherwise recommended_total().

```python
@property
def bank_reference_long(self) -> str
```
Full bank reference: `{reference} - {payee_name}` (max 140 chars).

```python
def bank_reference_short(self, limit: int = 140) -> str
```
Truncated reference ensuring it fits within limit:
- Truncates reference part only, keeps " - {payee_name}" intact
- If too long, further truncates to fit limit

```python
def clean(self)
```
Comprehensive validation:

1. **Duplicate check:** Prevents creating new plan if open plan exists for same (person_role, fiscal_year)
   - Draft conflict: "Please edit or delete the existing draft plan first"
   - Active conflict: "Please edit the existing plan or cancel it via workflow actions"

2. **FY immutability:** Cannot change fiscal_year after creation (keeps plan_code stable)

3. **FY required:** fiscal_year must be set

4. **Auto-fill monthly_amount:** On creation, pulls from person_role.role.default_monthly_amount if not set

5. **Window validation:**
   - pay_start must be within or before FY end
   - pay_end must be within or after FY start
   - Resolved window must not be inverted (start > end)

6. **Money validation:**
   - monthly_amount must be non-negative
   - IBAN checksum validation (mod-97)

7. **Overlap check:** PersonRole dates must overlap fiscal_year dates

8. **Required fields (when leaving DRAFT):**
   - payee_name, address, reference, cost_center, iban, bic, monthly_amount all required

```python
def mark_active(self, note: str | None = None)
def mark_finished(self, note: str | None = None)
def mark_cancelled(self, note: str | None = None)
```
State transition helpers: set status and optional status_note, save with atomic update.

```python
def _generate_plan_code(self) -> str
```
Generate next sequential code per fiscal year:
- Format: `{FY.code}-{serial:05d}` (e.g., WJ24_25-00001)
- Row-locks FiscalYear to serialize concurrent creates
- Parses existing codes with regex to find max serial

```python
def _default_window_from_pr_and_fy(self) -> tuple[date, date]
```
Calculate default payment window from PersonRole ∩ FiscalYear overlap:
1. pr_start = max(PersonRole.effective_start, FiscalYear.start)
2. pr_end = min(PersonRole.effective_end or FiscalYear.end, FiscalYear.end)

```python
def save(self, *args, **kwargs)
```
On creation:
1. Validates fiscal_year exists
2. Auto-fills monthly_amount from role default if not set
3. Auto-fills pay_start/pay_end from PersonRole ∩ FiscalYear if not set
4. Generates plan_code

Always (every save):
- Updates status = paymentplan_status(self)
- Logs creation with payments_logger

**History:** simple_history tracked  
**Versioning:** concurrency control  
**Logger:** `unihanko.payments`

**Workflow:** SUBMIT:WIREF → APPROVE:WIREF → APPROVE:CHAIR → VERIFY:WIREF → ACTIVE

---

### 2.5 IBAN Validation Helper

```python
def _iban_checksum_ok(iban: str) -> bool
```
Validates IBAN using mod-97 algorithm per ISO 13616:
1. Move first 4 chars to end
2. Convert letters to numbers (A=10, B=11, ..., Z=35)
3. Calculate mod 97 of resulting number
4. Valid if remainder == 1

---

## 3. Admin Interface

### 3.1 Import/Export Resources

**FiscalYearResource:**
- Fields: id, code, label, start, end, is_active, created_at, updated_at

**PaymentPlanResource:**
- Fields: id, plan_code, person_role, fiscal_year, cost_center, payee_name, address, iban, bic, reference, pay_start, pay_end, monthly_amount, total_override, status, status_note, signed_person_at, signed_wiref_at, signed_chair_at, created_at, updated_at

---

### 3.2 Custom Forms

#### 3.2.1 FiscalYearForm

**Help Texts:**
- `end`: "Leave blank to auto-fill (1 year − 1 day)."
- `code`: "Leave blank to auto-generate (WJyy_yy)."

#### 3.2.2 PaymentPlanForm

**Help Texts (after save):**
- `monthly_amount`: "Auto-filled from role default. Adjust if needed for this specific plan."
- `pay_start`: "Auto-calculated from assignment dates ∩ fiscal year. Adjust if needed."
- `pay_end`: "Auto-calculated from assignment dates ∩ fiscal year. Adjust if needed."

**Default Values (on add):**
- `reference`: "Funktionsgebühr" (if not already set)

**Suggestion Chips (after save):**

Displays clickable chips next to fields that auto-populate the field via JavaScript:
- `payee_name`: Shows "Use name" chip → fills with `{first_name} {last_name}` from PersonRole.person
- `reference`: Shows "Use 'Funktionsgebühr'" chip → fills with default reference

**Field Cleaning:**
- `iban`: Removes spaces, converts to uppercase
- `bic`: Removes spaces, converts to uppercase
- `reference`: Strips whitespace, defaults to "Funktionsgebühr" if empty

**Stricter Validation (when leaving DRAFT):**

When status != DRAFT, validates required fields at form level:
- payee_name, address, reference, cost_center, iban, bic all must be non-empty
- monthly_amount must be set

---

### 3.3 Custom Filters

#### 3.3.1 FYChipsFilter

**Purpose:** Show fiscal years as clickable chips (most recent 4 years).

**Template:** `admin/filters/fy_chips.html`

**Parameter:** `fy` (fiscal_year ID)

**Behavior:**
- Fetches 4 most recent FiscalYears ordered by -start
- Displays as chips with display_code() labels
- Filters PaymentPlan queryset by fiscal_year_id

---

### 3.4 PaymentPlan Admin

**Registration:** `@admin.register(PaymentPlan)`

**Mixins:**
- SimpleHistoryAdmin
- DjangoObjectActions
- ImportExportModelAdmin
- ConcurrentModelAdmin
- ImportExportGuardMixin
- HistoryGuardMixin

**List Display:**
- status_text (workflow badge), plan_code, person_role, fiscal_year, cost_center, monthly_amount, effective_total_display (bold with €), updated_at, active_text (FY lock indicator)

**Filters:**
- FYChipsFilter (custom)
- status, pay_start, pay_end, cost_center

**Search:**
- plan_code, person_role person/role names, payee_name, reference, cost_center, address

**Autocomplete:**
- person_role, fiscal_year

**Readonly Fields:**
- plan_code_or_hint, created_at, updated_at, window_preview, breakdown_preview, recommended_total_display, role_monthly_hint, bank_reference_preview_full, pdf_file, submission_ip, signatures_box, status

**Fieldsets:**

1. **Scope:** plan_code_or_hint, person_role, fiscal_year, status
2. **Budget:** cost_center, monthly_amount, role_monthly_hint, total_override, recommended_total_display, breakdown_preview  
   Description: "Financial parameters set by WiRef."
3. **Payment Window:** pay_start, pay_end, window_preview
4. **Banking:** payee_name, iban, bic, address, reference, bank_reference_preview_full  
   Description: "Payee details completed via portal. Reference text set by admin."
5. **Submission:** signed_person_at, pdf_file, submission_ip  
   Description: "Received from payee via public portal."
6. **Workflow & HankoSign:** signatures_box
7. **System:** created_at, updated_at, version

**Inline:**
- AnnotationInline

**Actions:**
- export_selected_pdf (bulk PDF export)

**Object Actions:**
- submit_plan, withdraw_plan, approve_wiref, approve_chair, verify_banking, cancel_plan, print_paymentplan

#### 3.4.1 Computed Display Methods

```python
@admin.display
def status_text(obj)
```
Workflow status badge using `object_status_span(obj, final_stage="CHAIR", tier1_stage="WIREF")`.

Shows colored badge: Draft (gray), Submitted (yellow), WiRef (blue), Chair (green).

```python
@admin.display
def active_text(obj)
```
FY lock cascade indicator:
- Checks if obj.fiscal_year has explicit_locked=True signature
- Returns "Open" (green) if unlocked, "Locked" (red) if locked

```python
@admin.display
def window_preview(obj)
```
Template: `admin/finances/window_preview.html`

Shows resolved payment window with visual indicators:
- Window start/end dates
- FY boundaries
- Overlap status

```python
@admin.display
def plan_code_or_hint(obj)
```
Shows plan_code if exists, otherwise displays "— will be generated after saving —" in muted red.

```python
@admin.display
def role_monthly_hint(obj)
```
Shows role.default_monthly_amount as "XXX.XX €" for comparison with monthly_amount.

```python
@admin.display
def breakdown_preview(obj)
```
Template: `admin/finances/breakdown_preview.html`

Shows month-by-month proration table:
- Year-Month, Days covered, Fraction, Amount (€)

```python
@admin.display
def recommended_total_display(obj)
```
Shows recommended_total() as yellow code text: "XXX.XX €" (richtwert).

```python
@admin.display
def bank_reference_preview_full(obj)
```
Template: `admin/finances/bank_reference_preview.html`

Shows two reference formats:
- Full: bank_reference_long (140 chars)
- Short: bank_reference_short(140)

#### 3.4.2 Readonly Rules

**FY Locked (year-end close):**

If fiscal_year has explicit_locked signature:
- Lock ALL editable fields (full tombstone)
- Only readonly fields visible

**Workflow-Driven Readonly:**

**DRAFT:**
- After creation: person_role, fiscal_year locked (scope immutable)

**PENDING:**
- Lock: person_role, fiscal_year, cost_center, banking fields, payment window, monthly_amount, total_override, signed_person_at

**ACTIVE/FINISHED/CANCELLED:**
- Lock: person_role, fiscal_year, cost_center, banking fields, pay_start, monthly_amount, total_override, signed_person_at
- FINISHED only: Also lock pay_end (money already paid)
- CANCELLED: Allow pay_end adjustment (fine-tune cancellation date)

#### 3.4.3 Object Actions

**submit_plan:**
- Label: "Submit"
- Color: Warning (yellow)
- Action: SUBMIT:WIREF@finances.paymentplan
- Preconditions:
  - Not already submitted
  - signed_person_at and pdf_file must exist (payee completed form)
- Creates system annotation

**withdraw_plan:**
- Label: "Withdraw"
- Color: Secondary (gray)
- Action: WITHDRAW:WIREF@finances.paymentplan
- Preconditions:
  - Must be submitted
  - No approvals exist
- Creates system annotation

**approve_wiref:**
- Label: "Approve (WiRef)"
- Color: Success (green)
- Action: APPROVE:WIREF@finances.paymentplan
- Preconditions:
  - Must be submitted
  - Not already approved by WiRef
- Creates system annotation

**approve_chair:**
- Label: "Approve (Chair)"
- Color: Success (green)
- Action: APPROVE:CHAIR@finances.paymentplan
- Preconditions:
  - Must be submitted
  - Not already approved by Chair
- Creates system annotation

**verify_banking:**
- Label: "Verify banking"
- Color: Primary (blue)
- Action: VERIFY:WIREF@finances.paymentplan
- Preconditions:
  - Both WIREF and CHAIR approvals must exist
  - Not already verified
- Creates system annotation
- Message: "Banking verified. Plan is now ACTIVE."

**cancel_plan:**
- Label: "Cancel plan"
- Color: Danger (red)
- Action: REJECT:-@finances.paymentplan
- Behavior:
  - If ACTIVE and pay_end > today: Automatically sets pay_end = today
  - Message: "Payment end date automatically set to {date}. You can adjust if needed."
- Creates system annotation

**print_paymentplan:**
- Label: "🖨️ Print PDF"
- Color: Info (cyan)
- Action: RELEASE:-@finances.paymentplan (10s window)
- Template: finances/paymentplan_pdf.html
- Filename: `FGEB-BELEG_{plan_code}_{role_short}_{lastname}-{date}.pdf`
- Context: pp, signatures, org, signers (Person, WiRef, Chair)

**export_selected_pdf (bulk action):**
- Description: "Export selected to PDF"
- Action: RELEASE:-@finances.paymentplan (10s window per plan)
- Template: finances/paymentplans_list_pdf.html
- Filename: `FGEB_SELECT-{date}.pdf`
- Context: rows (queryset), org
- Behavior: Signs each plan in the export (doesn't fail if one signature fails)

#### 3.4.4 Action Visibility Logic

**FY Locked:**
- Only show: print_paymentplan

**DRAFT:**
- Show: submit_plan, cancel_plan, print_paymentplan
- Hide: withdraw, approvals, verify

**PENDING:**
- Hide: submit_plan (already submitted)
- Show withdraw_plan ONLY if no approvals exist
- Hide approve_wiref if WIREF approval exists
- Hide approve_chair if CHAIR approval exists
- Show verify_banking ONLY if both WIREF and CHAIR approvals exist
- Show: print_paymentplan

**ACTIVE:**
- Show: cancel_plan, print_paymentplan
- Hide: all workflow actions

**FINISHED/CANCELLED:**
- Show: print_paymentplan only
- Hide: all workflow actions including cancel

#### 3.4.5 Status-Specific Banners

**change_view() messages:**

**DRAFT:**
- Info: "Draft: please wait for payment plan filing by person, then review if all fields are present and correct."

**CANCELLED:**
- Warning: "⚠️ **Cancelled:** Verify the payment end date is correct, and ensure all standing orders (Daueraufträge) are cancelled with the bank."

#### 3.4.6 Delete Permission

**Policy:**
- Only allow deletion for DRAFT status plans
- Check FY lock first (no delete if FY locked)
- Once submitted, must use Cancel action for audit trail

#### 3.4.7 FY-Aware Add Behavior

**has_add_permission():**
- Show green "Add" button on changelist ONLY if ?fy={id} parameter present
- Always allow actual /add/ view itself

**changelist_view():**
- Stores selected ?fy parameter in session as `paymentplans_selected_fy`
- Passes `selected_fy_label` (e.g., FY24_25) and `selected_fy_id` to template for custom Add button

**get_form() on add:**
- Pre-fills and hides fiscal_year field using ?fy or session value
- Forwards FY to person_role autocomplete endpoint (filters PersonRoles by FY overlap)

**get_fields() on add:**
- Ultra-minimal: person_role, fiscal_year, cost_center, reference
- After save: shows full fieldsets

**get_fieldsets() on add:**
- Minimal fieldsets:
  1. Scope: person_role, fiscal_year, cost_center
  2. Banking: reference (optional, defaults to "Funktionsgebühr")

---

### 3.5 FiscalYear Admin

**Registration:** `@admin.register(FiscalYear)`

**Mixins:**
- SimpleHistoryAdmin
- DjangoObjectActions
- ImportExportModelAdmin
- ImportExportGuardMixin
- HistoryGuardMixin

**List Display:**
- display_code, start, end, is_active, updated_at, active_text (lock indicator)

**Filters:**
- is_active, start, end

**Search:**
- code, label

**Ordering:** -start (newest first)

**Date Hierarchy:** start

**Readonly Fields:**
- created_at, updated_at, active_text, signatures_box

**Fieldsets:**

1. **Scope:** start, end, code, label, is_active
2. **Workflow & HankoSign:** signatures_box
3. **System:** created_at, updated_at

**Inline:**
- AnnotationInline

**Bulk Actions:**
- export_selected_pdf, make_active

**Object Actions:**
- print_fiscalyear, lock_year, unlock_year

#### 3.5.1 Computed Display Methods

```python
@admin.display
def active_text(obj)
```
Lock indicator:
- Checks if obj has explicit_locked=True signature
- Returns "Open" (green) if unlocked, "Locked" (red) if locked

```python
@admin.display
def signatures_box(obj)
```
Renders HankoSign signature box.

#### 3.5.2 Object Actions

**print_fiscalyear:**
- Label: "🖨️ Print receipt PDF"
- Color: Secondary (gray)
- Action: RELEASE:-@finances.fiscalyear (10s window)
- Template: finances/fiscalyear_pdf.html
- Filename: `WJFY-STATUS_{display_code}-{date}.pdf`
- Context: fy, org, signatures

**export_selected_pdf (bulk action):**
- Description: "Print selected as overview PDF"
- Action: RELEASE:-@finances.fiscalyear (10s window per FY)
- Template: finances/fiscalyears_list_pdf.html
- Filename: `WJFY-SELECT-{date}.pdf`
- Context: rows (ordered by -start), org
- Behavior: Signs each FY (doesn't fail if one signature fails)

**make_active (bulk action):**
- Description: "Set selected as active (and clear others)"
- Permission: Managers only
- Validation:
  - Must select exactly 1 fiscal year
  - Target cannot be locked
  - If already active, shows info message
- Behavior:
  - Clears is_active from all other FiscalYears
  - Sets target.is_active = True
  - Atomic transaction
- Messages:
  - Success: "Activated {code} as the current fiscal year."
  - Error: "Could not set active due to a database constraint..."

**lock_year:**
- Label: "Lock year"
- Color: Warning (yellow)
- Action: LOCK:-@finances.fiscalyear
- Permission: Managers only
- Precondition: Not already locked
- Creates system annotation
- **Cascade Effect:** Locks ALL PaymentPlans in this FY

**unlock_year:**
- Label: "Unlock year"
- Color: Success (green)
- Action: UNLOCK:-@finances.fiscalyear
- Permission: Managers only
- Precondition: Currently locked
- Creates system annotation
- **Cascade Effect:** Unlocks all PaymentPlans in this FY

#### 3.5.3 Action Visibility

**Non-managers:**
- Show: print_fiscalyear only

**Managers:**
- If locked: unlock_year, print_fiscalyear
- If unlocked: lock_year, print_fiscalyear

#### 3.5.4 Delete Permission

**Policy:** No delete permission (consistent with People module).

#### 3.5.5 Row Attributes

**get_changelist_row_attrs():**

Priority order:
1. If locked: show locked state (red)
2. Otherwise: show is_active state (green if active, gray if inactive)

---

## 4. Management Commands

### 4.1 bootstrap_fiscalyears

**Command:** `python manage.py bootstrap_fiscalyears [--file FILE] [--dry-run]`

**Purpose:** Load/update FiscalYears from YAML (idempotent).

**YAML Format:**

```yaml
fiscal_years:
  - start: "2024-07-01"
    label: "Academic Year 2024/25"
    is_active: true
  
  - start: "2025-07-01"
    label: "Academic Year 2025/26"
    is_active: false
```

**Fields:**
- `start` (required): ISO date string or date object
- `label` (optional): Descriptive label
- `is_active` (optional): Boolean, default false

**File Resolution:**

Non-sensitive (default): `finances/fixtures/fiscal_years.yaml`

**Code Generation:**

Automatically generates code from start date:
- Format: `WJyy_yy`
- Example: start=2024-07-01 → code=WJ24_25

**Behavior:**
- Creates new FiscalYears if code doesn't exist
- Updates changed fields (label, start, is_active) if code exists
- Reports: created, updated, unchanged counts
- Validates with model's clean() before save
- `--dry-run`: shows changes without applying

**Output:**
```
Created: WJ24_25
Updated: WJ23_24
✓ Bootstrap complete! 2 created, 1 updated, 3 unchanged.
```

**Transaction Safety:** Each create/update wrapped in atomic transaction.

---

## 5. Workflow States

### 5.1 PaymentPlan States

**DRAFT → PENDING (via Submit):**
- Preconditions:
  - Portal submission complete (signed_person_at + pdf_file)
- Action: SUBMIT:WIREF@finances.paymentplan
- Next: Awaiting WIREF approval

**PENDING → DRAFT (via Withdraw):**
- Preconditions:
  - No approvals exist yet
- Action: WITHDRAW:WIREF@finances.paymentplan
- Effect: Returns to draft for editing

**PENDING → PENDING (via Approve WiRef):**
- Action: APPROVE:WIREF@finances.paymentplan
- Next: Awaiting CHAIR approval

**PENDING → PENDING (via Approve Chair):**
- Action: APPROVE:CHAIR@finances.paymentplan
- Next: Awaiting banking verification

**PENDING → ACTIVE (via Verify Banking):**
- Preconditions:
  - Both WIREF and CHAIR approvals exist
- Action: VERIFY:WIREF@finances.paymentplan
- Effect: Plan becomes active, payments can begin

**ACTIVE → FINISHED (automatic):**
- Trigger: Current date > pay_end
- Effect: Auto-transitions to FINISHED

**DRAFT/ACTIVE → CANCELLED (via Cancel):**
- Action: REJECT:-@finances.paymentplan
- ACTIVE plans: Automatically sets pay_end = today if in future
- Effect: Terminal state, payments stop

### 5.2 FiscalYear Lock States

**Open → Locked (via Lock Year):**
- Action: LOCK:-@finances.fiscalyear
- Permission: Managers only
- Effect: All PaymentPlans in this FY become read-only

**Locked → Open (via Unlock Year):**
- Action: UNLOCK:-@finances.fiscalyear
- Permission: Managers only
- Effect: Unlocks all PaymentPlans in this FY

---

## 6. Key Features

### 6.1 30-Day Proration System

**Purpose:** Standardized partial-month calculations for accounting.

**Method:**
- Uses fixed 30-day accounting month (not calendar month days)
- Calculates fraction: actual_days_covered / 30
- Allows fractions > 1.0 (e.g., 31 days = 1.0333 months)

**Example:**
```
Jul 15 - Sep 14, monthly = €500

July:   17 days / 30 = 0.5667 → €283.35
August: 31 days / 30 = 1.0333 → €516.65
Sept:   14 days / 30 = 0.4667 → €233.35
Total: €1033.35 (recommended)
```

**Override:**
- Managers can set total_override to adjust final amount
- effective_total uses override if set, otherwise recommended_total

### 6.2 Fiscal Year Locking Cascade

**Hierarchy:**
1. FiscalYear receives LOCK signature
2. All PaymentPlans check fiscal_year lock in admin
3. If FY locked: ALL plans become read-only (tombstone)
4. No workflow actions available (except print)

**Use Case:** Year-end close prevents any modifications to completed fiscal year.

**Unlock:** Managers can unlock FY, restoring full access to all plans.

### 6.3 Portal Integration

**Fields for Portal:**
- `signed_person_at`: Timestamp when payee completed form
- `pdf_file`: Signed PDF uploaded by payee
- `submission_ip`: IP address of submission (audit trail)

**Workflow:**
1. Admin creates draft plan (minimal fields)
2. Payee completes banking details + signs via portal
3. Portal saves signed_person_at, pdf_file, submission_ip
4. Admin reviews and submits for approval

**Validation:**
- Cannot submit until signed_person_at and pdf_file exist

### 6.4 Banking Reference Formats

**Long Format (140 chars):**
```
{reference} - {payee_name}
```
Example: "Funktionsgebühr - Max Mustermann"

**Short Format (variable limit):**
- Truncates reference part only
- Preserves " - {payee_name}" suffix
- If still too long, truncates further

**Use Case:**
- Long: Admin display, internal records
- Short: Banking software character limits

### 6.5 Auto-Fill from PersonRole & FiscalYear

**On Creation:**
1. **monthly_amount:** Pulled from person_role.role.default_monthly_amount
2. **pay_start:** max(PersonRole.effective_start, FiscalYear.start)
3. **pay_end:** min(PersonRole.effective_end or FiscalYear.end, FiscalYear.end)
4. **plan_code:** Sequential per FY (WJ24_25-00001, WJ24_25-00002, etc.)

**Editable After:**
- monthly_amount can be adjusted if needed
- pay_start/pay_end can be fine-tuned
- plan_code NEVER changes

### 6.6 Duplicate Prevention

**Rule:** Only ONE open plan per (person_role, fiscal_year).

**Enforcement:**
- clean() checks for existing non-finished/cancelled plans
- Friendly error messages:
  - Draft conflict: "edit or delete the existing draft"
  - Active conflict: "edit or cancel via workflow actions"

**Allows:**
- Multiple FINISHED plans (historical)
- Multiple CANCELLED plans (failed attempts)
- Plans in different fiscal years

### 6.7 Concurrency Control

**Version Fields:**
- PaymentPlan.version (AutoIncVersionField)

**Race Conditions:**
- plan_code generation: Row-locks FiscalYear during serial lookup
- Concurrent updates: Optimistic locking prevents lost updates

### 6.8 Status Computation

**Always Computed:**
- status field computed from signatures on EVERY save
- Never manually set (except via mark_active/mark_finished/mark_cancelled helpers)

**Benefits:**
- Source of truth is HankoSign signatures
- No status drift or inconsistencies
- Audit trail via signatures

---

## 7. Bootstrap Integration

Called from master `bootstrap_unihanko` command:

```bash
# Standalone
python manage.py bootstrap_fiscalyears [--dry-run]

# Via master orchestrator
python manage.py bootstrap_unihanko [--dry-run]
```

**Order in Master:**
1. orginfo
2. acls
3. actions
4. roles
5. reasons
6. holidays
7. **fiscalyears** ← this command
8. ...

---

## 8. Dependencies

**Imports:**
- `people.models.PersonRole` - assignment link
- `hankosign.utils` - workflow signature functions
- `hankosign.models.Signature` - signature queries
- `annotations.admin.AnnotationInline` - comment support
- `annotations.views.create_system_annotation` - workflow annotations
- `organisation.models.OrgInfo` - PDF headers
- `core.admin_mixins` - safe actions, guards, decorators
- `core.pdf.render_pdf_response` - PDF generation
- `core.utils.authz.is_finances_manager` - permission check
- `core.utils.bool_admin_status` - status badge helpers
- `core.utils.privacy.mask_iban` - IBAN privacy masking

**External Packages:**
- simple_history - model history tracking
- concurrency - version fields for optimistic locking
- django_object_actions - admin object actions
- import_export - CSV/Excel import/export

---

## 9. Notes

**German Fiscal Year Convention:**
- Stored code: `WJ24_25` (Wirtschaftsjahr)
- Display code: `FY24_25` (English) or `WJ24_25` (German)
- Typical start: July 1 (academic calendar)
- Typical end: June 30 next year

**Banking Standards:**
- IBAN: Max 34 chars, mod-97 checksum validated
- BIC: Max 11 chars
- Reference: Max 140 chars for long format

**Proration Edge Cases:**
- Day 1 of month: Normalized to last day of previous month
- Empty range: Returns empty breakdown list
- Leap years: Handled by auto_end_from_start()

**Status Transitions:**
- DRAFT → PENDING: Submit (after portal)
- PENDING → ACTIVE: Approve(WIREF) + Approve(CHAIR) + Verify(WIREF)
- ACTIVE → FINISHED: Auto (past end date)
- Any → CANCELLED: Cancel action

**Manager Privileges:**
- Full access to all plans
- Can lock/unlock fiscal years
- Can set active fiscal year
- Can bypass readonly restrictions

**Audit Trail:**
- simple_history tracks all changes
- HankoSign signatures track workflow
- System annotations document actions
- payments_logger logs plan creation
- submission_ip tracks portal submissions

---

## 10. File Structure

```
finances/
├── __init__.py
├── apps.py                                    # Standard config
├── models.py                                  # 750 lines
│   ├── helpers (calculate_proration_breakdown, auto_end_from_start, etc.)
│   ├── paymentplan_status (state machine)
│   ├── FiscalYear
│   ├── PaymentPlan
│   └── _iban_checksum_ok (validation)
├── admin.py                                   # 1248 lines
│   ├── Import/Export resources
│   ├── FiscalYearForm
│   ├── PaymentPlanForm (with suggestion chips)
│   ├── FYChipsFilter (custom filter)
│   ├── PaymentPlanAdmin (with all object actions)
│   └── FiscalYearAdmin (with lock/unlock)
├── views.py                                   # Empty placeholder
├── tests.py                                   # Empty placeholder
├── management/
│   └── commands/
│       └── bootstrap_fiscalyears.py           # 135 lines
└── migrations/                                # Django migrations
```

Total lines: ~2,133 (excluding migrations)

---

**Version:** 1.0.0  
**Last Updated:** 2025-12-08  
**Author:** Sven (vas)