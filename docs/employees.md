# EMPLOYEES.md

**Module:** `employees`  
**Purpose:** Employment contracts, time tracking, PTO management, and document workflows for student union personnel  
**Version:** 1.0.3 (models), 1.0.0 (admin)  
**Dependencies:** people.PersonRole, hankosign, annotations, organisation.OrgInfo

---

## 1. Overview

The employees module manages employment relationships, time tracking, paid time off (PTO), and employment documentation for student union staff. It provides:

- **Employment records** linked to PersonRole assignments
- **Monthly timesheets** with work/leave/sick tracking
- **PTO accounting** with configurable reset dates and carry-over
- **Document workflows** for contracts, leave requests, and sick notes
- **Configurable holiday calendar** for workday calculations

---

## 2. Models

### 2.1 Helper Functions

```python
def minutes_to_hhmm(minutes: int) -> str
```
Format minutes → 'H:MM' string, handles negative values with sign prefix.

```python
def easter_date(year: int) -> date
```
Calculate Western (Gregorian) Easter Sunday using Anonymous Gregorian algorithm.

```python
def month_days(year: int, month: int) -> int
def iter_month_dates(year: int, month: int) -> Iterable[date]
```
Month utilities for calendar operations.

---

### 2.2 HolidayCalendar

**Purpose:** Define public holidays for workday calculations in timesheets.

**Fields:**
- `name`: CharField(120) unique - calendar name
- `is_active`: BooleanField default=False - active calendar (only one allowed)
- `rules_text`: TextField - line-based rule definitions
- `created_at`, `updated_at`: DateTimeField auto

**Constraint:**
- Only one calendar can be active at a time (unique constraint on is_active=True)

**Rules Format (pipe-delimited, one per line):**

```
# Fixed annual dates (MM-DD | EN | DE)
01-06 | Epiphany | Heilige Drei Könige
12-25 | Christmas Day | Weihnachten

# Easter-relative (EASTER±N | EN | DE)
EASTER+1 | Easter Monday | Ostermontag
EASTER+39 | Ascension Day | Christi Himmelfahrt
EASTER+50 | Whit Monday | Pfingstmontag

# One-off dates (YYYY-MM-DD | EN | DE)
2025-05-09 | Bridge Day | Fenstertag
```

**Rule Types:**
- **FIXED:** MM-DD format, applies every year
- **EASTER:** EASTER+N or EASTER-N, offset from Easter Sunday
- **ONEOFF:** YYYY-MM-DD, single occurrence

**Labels:** If only one label provided, used for both languages. Order: English first, German second.

**Methods:**

```python
def holidays_for_year(year: int) -> set[date]
```
Returns set of holiday dates for the given year.

```python
def holidays_for_year_labeled(year: int, lang: str | None = None) -> dict[date, str]
```
Returns {date: localized_label} dictionary for UI/PDF display.

```python
@classmethod
def get_active() -> HolidayCalendar | None
```
Get the currently active calendar (or None).

**History:** simple_history tracked

---

### 2.3 Employee

**Purpose:** Employment container attached to PersonRole with time/PTO accounting.

**Fields:**

**Scope:**
- `person_role`: OneToOneField(PersonRole, PROTECT) - linked assignment
- `is_active`: BooleanField default=True

**Work Terms:**
- `weekly_hours`: DecimalField(5,2) - nominal weekly hours (e.g., 10.00)
- `saldo_minutes`: IntegerField default=0 - running time-account balance (positive=credit, negative=deficit)

**Employment Window Overrides:**
- `start_override`: DateField nullable - override employment start (if misaligned with PersonRole)
- `end_override`: DateField nullable - override employment end

**PTO Terms:**
- `annual_leave_days_base`: PositiveSmallIntegerField default=25 - base PTO days per year (5-day week)
- `annual_leave_days_extra`: PositiveSmallIntegerField default=0 - additional days (disability, agreements)
- `leave_reset_override`: DateField nullable - custom PTO year start (default: Jan 1)

**Personal Data:**
- `insurance_no`: CharField(40) nullable - social insurance number
- `dob`: DateField nullable - date of birth

**Other:**
- `notes`: TextField blank
- `created_at`, `updated_at`: DateTimeField auto

**Properties:**

```python
@property
def effective_start(self) -> date
```
Returns start_override or PersonRole.effective_start or PersonRole.start_date.

```python
@property
def effective_end(self) -> Optional[date]
```
Returns end_override or PersonRole.effective_end or PersonRole.end_date.

```python
@property
def weekly_minutes(self) -> int
```
Convert weekly_hours to minutes (ROUND_HALF_UP).

```python
@property
def daily_expected_minutes(self) -> int
```
weekly_minutes / 5 (assumes 5-day work week).

```python
def saldo_as_hhmm(self) -> str
```
Format saldo_minutes as H:MM string.

**Validation:**
- end_override >= start_override (if both set)

**History:** simple_history tracked

**Related:**
- `leave_years`: reverse FK to EmployeeLeaveYear
- `timesheets`: reverse FK to TimeSheet
- `documents`: reverse FK to EmploymentDocument

---

### 2.4 EmployeeLeaveYear

**Purpose:** Annual PTO snapshot with configurable reset dates and carry-over.

**Fields:**
- `employee`: ForeignKey(Employee, CASCADE) related_name="leave_years"
- `label_year`: PositiveIntegerField - PTO year label (see below)
- `period_start`: DateField - PTO year start date
- `period_end`: DateField - PTO year end (exclusive)
- `entitlement_minutes`: IntegerField - annual entitlement snapshot
- `carry_in_minutes`: IntegerField default=0 - carried from previous year
- `manual_adjust_minutes`: IntegerField default=0 - manual corrections
- `created_at`, `updated_at`: DateTimeField auto

**Label Year Logic:**

If reset date is Jan 1:
- label_year = calendar_year
- 2025-01-01 to 2025-12-31 → label_year=2025

If reset date is July 1:
- label_year = year of reset date
- 2025-07-01 to 2026-06-30 → label_year=2025

Algorithm: If (month, day) >= (reset_month, reset_day), label_year = year, else label_year = year - 1.

**Computed Properties:**

```python
@property
def taken_minutes(self) -> int
```
Sum of TimeEntry.LEAVE minutes within [period_start, period_end).

```python
@property
def remaining_minutes(self) -> int
```
entitlement + carry_in + manual_adjust - taken.

**Class Methods:**

```python
@classmethod
def pto_label_year_for(emp: Employee, any_date: date) -> int
```
Map any date to its PTO label year based on employee's reset date.

```python
@classmethod
def pto_period_for(emp: Employee, label_year: int) -> tuple[date, date]
```
Compute [start, end) dates for the given label_year.

```python
@classmethod
def ensure_for(emp: Employee, label_year: int) -> EmployeeLeaveYear
```
Idempotently create (or return existing) snapshot for label_year.
- Calculates entitlement: (base_days + extra_days) × daily_expected_minutes
- Auto-carries previous year's remaining_minutes as carry_in_minutes (no cap)

**Constraints:**
- unique_together: (employee, label_year)

**History:** simple_history tracked

---

### 2.5 EmploymentDocument

**Purpose:** Document management for contracts, agreements, leave requests, and sick notes.

**Document Kinds:**

```python
class Kind(models.TextChoices):
    ZV = "ZV", _("Supplemental Agreement")      # Zusatzvereinbarung
    DV = "DV", _("Contract of Employment")      # Dienstvertrag
    AA = "AA", _("Leave Request")               # Abwesenheitsantrag
    KM = "KM", _("Sick Note")                   # Krankmeldung
    ZZ = "ZZ", _("Other / Miscellaneous")
```

**Fields:**

**Scope:**
- `employee`: ForeignKey(Employee, PROTECT) related_name="documents"
- `kind`: CharField(2) - document type
- `code`: CharField(80) unique blank - auto-generated identifier

**Content:**
- `title`: CharField(160) blank - document title/subject
- `details`: TextField blank - detailed description
- `start_date`: DateField nullable - start of period (required for AA/KM)
- `end_date`: DateField nullable - end of period (required for AA/KM)

**Lifecycle:**
- `is_active`: BooleanField default=True
- `pdf_file`: FileField upload_to="employee/docs/%Y/%m/" nullable
- `relevant_third_party`: CharField(160) blank - e.g., health insurance, accounting firm

**System:**
- `created_at`, `updated_at`: DateTimeField auto
- `version`: AutoIncVersionField (concurrency)

**Code Generation:**

Format: `{KIND}_{YYYY-MM-DD}_{LASTNAME}` (uppercase)
- Example: `AA_2025-12-08_MUSTERMANN`
- Auto-increments with `-N` suffix if duplicate: `AA_2025-12-08_MUSTERMANN-2`

**Duration Properties:**

```python
@property
def duration_days(self) -> int | None
```
Exclusive span: (end_date - start_date).days

```python
@property
def duration_days_inclusive(self) -> int | None
```
Inclusive: duration_days + 1

```python
@property
def duration_weekdays(self) -> int | None
```
Exclusive weekday count (Mon-Fri) using core.utils.weekday_helper.

```python
@property
def duration_weekdays_inclusive(self) -> int | None
```
Inclusive weekday count.

**Constraints:**
- end_date >= start_date (if both set)
- code must be non-empty

**Indexes:**
- employee, kind, code

**History:** simple_history tracked  
**Versioning:** concurrency control

**Workflow:** AA/KM/ZV flow through SUBMIT → APPROVE(WIREF) → APPROVE(CHAIR) stages (see Admin section).

---

### 2.6 TimeSheet

**Purpose:** Monthly time tracking container with aggregated totals.

**Fields:**

**Scope:**
- `employee`: ForeignKey(Employee, PROTECT) related_name="timesheets"
- `year`: PositiveIntegerField validators=[2000-9999]
- `month`: PositiveSmallIntegerField validators=[1-12]

**Aggregates (minutes):**
- `opening_saldo_minutes`: IntegerField default=0 - snapshot of employee.saldo_minutes at month start
- `expected_minutes`: IntegerField default=0 - computed from workdays × daily_expected_minutes
- `worked_minutes`: IntegerField default=0 - sum of WORK entries
- `credit_minutes`: IntegerField default=0 - sum of LEAVE + SICK entries
- `closing_saldo_minutes`: IntegerField default=0 - opening + worked + credit - expected

**Lifecycle:**
- `pdf_file`: FileField upload_to="employee/timesheets/%Y/%m/" nullable

**System:**
- `created_at`, `updated_at`: DateTimeField auto
- `version`: AutoIncVersionField (concurrency)

**Constraints:**
- unique_together: (employee, year, month)
- month range check: 1-12

**Methods:**

```python
def compute_expected_minutes(self) -> int
```
Count Mon-Fri workdays in month, subtract active holiday calendar dates, multiply by employee.daily_expected_minutes.

```python
def recompute_aggregates(commit: bool = False)
```
Recalculate worked_minutes, credit_minutes, closing_saldo_minutes.
- If commit=True: atomic direct update (no save() to avoid version conflicts)
- Uses DB-level aggregation with row locking

```python
def _active_holidays(self) -> Set[date]
```
Get holidays for this year from active HolidayCalendar (or empty set).

**Save Behavior:**

On create:
- Snapshots opening_saldo_minutes from employee.saldo_minutes
- Computes expected_minutes
- Initializes worked/credit to 0
- Calculates closing_saldo = opening - expected
- Atomic creation with 5-attempt retry for race conditions

On update:
- Calls recompute_aggregates(commit=True)

**History:** simple_history tracked  
**Versioning:** concurrency control

**Related:**
- `entries`: reverse FK to TimeEntry

---

### 2.7 TimeEntry

**Purpose:** Individual time tracking entries within a TimeSheet.

**Entry Kinds:**

```python
class Kind(models.TextChoices):
    WORK = "WORK", _("Work")
    LEAVE = "LEAVE", _("Leave (paid)")         # Credits PTO time
    SICK = "SICK", _("Sick (paid)")            # Credits sick time
    PUBLIC_HOLIDAY = "PUBHOL", _("Public holiday")  # System-generated
    OTHER = "OTHER", _("Other")
```

**Fields:**
- `timesheet`: ForeignKey(TimeSheet, CASCADE) related_name="entries"
- `date`: DateField
- `kind`: CharField(6) default=WORK
- `minutes`: PositiveIntegerField default=0
- `start_time`: TimeField nullable - optional convenience field
- `end_time`: TimeField nullable - optional convenience field
- `comment`: CharField(240) blank
- `created_at`, `updated_at`: DateTimeField auto
- `version`: AutoIncVersionField

**Constraints:**
- unique: (timesheet, date, kind, comment) - prevents duplicate entries
- check: minutes >= 0
- index: (timesheet, date)

**Input Logic:**

Three modes:
1. **Time span:** Both start_time and end_time provided → calculates minutes
2. **Minutes only:** Direct minutes entry
3. **Smart default:** For LEAVE/SICK with no input → uses employee.daily_expected_minutes

**Validation Rules:**

1. **Parent lock:** Cannot add/change if timesheet is workflow-locked (enforced in admin)
2. **Month constraint:** Entry date must be in timesheet's year/month
3. **Holiday policy:** Cannot enter WORK on public holiday dates (prevents double-counting)
4. **Time span validation:**
   - end_time > start_time (same-day only)
   - If both times and minutes given, they must match
   - Seconds normalized to :00
5. **Partial input:** Must provide both start and end, or neither
6. **LEAVE/SICK:** If no minutes/times given, auto-fills employee.daily_expected_minutes

**Save Behavior:**

1. Calculates minutes from start_time/end_time if provided
2. Applies smart default for LEAVE/SICK if minutes=0
3. Auto-provisions EmployeeLeaveYear snapshot if kind=LEAVE
4. Triggers parent TimeSheet.recompute_aggregates(commit=True)

**History:** simple_history tracked  
**Versioning:** concurrency control

---

## 3. Admin Interface

### 3.1 Import/Export Resources

All models have import/export support with these resource classes:
- `EmployeeResource`
- `EmploymentDocumentResource`
- `TimeSheetResource`
- `TimeEntryResource`
- `HolidayCalendarResource`

### 3.2 Mixins & Helpers

**ManagerEditableGateMixin:**
```python
def _is_manager(self, request) -> bool
```
Uses `core.utils.authz.is_employees_manager()` to check manager permissions.

---

### 3.3 Employee Admin

**Registration:** `@admin.register(Employee)`

**List Display:**
- person_role, weekly_hours, saldo_display (formatted as ±HH:MM), updated_at, active_text (with data-state attribute)

**Filters:**
- is_active, weekly_hours

**Search:**
- person_role__person__last_name, first_name
- person_role__role__name

**Fieldsets:**
1. Scope: person_role, is_active
2. Work terms: weekly_hours, saldo_minutes, daily_expected (readonly computed)
3. PTO terms: annual_leave_days_base, annual_leave_days_extra, leave_reset_override
4. Personal data: insurance_no, dob
5. Miscellaneous: notes
6. Workflow & HankoSign: signatures_box (readonly)
7. System: created_at, updated_at (readonly)

**Inlines:**
- `EmployeeLeaveYearInline` (paginated, per_page=1) - visible only to managers
  - Shows: label_year, period_start/end, entitlement/carry_in/manual_adjust/taken/remaining (all readonly except manual_adjust)
  - No add permission
- `EmploymentDocumentInline` (paginated, per_page=3)
  - Shows: kind, title, start_date, end_date, is_active, pdf_file, code (readonly)
  - show_change_link=True, can_delete=False

**Object Actions:**

```python
@safe_admin_action
def print_employee(request, obj)
```
- Records RELEASE:-@employees.employee signature with 10s window
- Generates PDF from employees/employee_pdf.html
- Filename: `EMP_{id}.pdf`
- Context: emp, signatures, org

**Permissions:**
- No delete permission
- Non-superusers: person_role readonly after creation

**Auto-Provisioning:**
On save, ensures current PTO year exists via `EmployeeLeaveYear.ensure_for()`.

---

### 3.4 EmploymentDocument Admin

**Registration:** `@admin.register(EmploymentDocument)`

**Form:** `EmploymentDocumentAdminForm`
- Marks start_date/end_date as required (client-side) for AA/KM kinds
- Validates date range and kind-specific requirements

**List Display:**
- status_text (workflow state badge), code, employee, kind_text, title, period_display (formatted range), updated_at

**Filters:**
- kind, is_active, start_date, end_date

**Search:**
- code, title, employee person/role names

**Fieldsets:**
1. Scope: employee, code (readonly)
2. Document: kind, title, start_date, end_date, is_active, relevant_third_party, pdf_file, details
3. Workflow & HankoSign: signatures_box (readonly)
4. System: version, created_at, updated_at (readonly)

**Inline:**
- AnnotationInline for comments

**Readonly Fields (conditional):**
- Always readonly: employee, kind (after creation), code
- After submit (non-managers): title, start_date, end_date, pdf_file, relevant_third_party, details

**Object Actions:**

#### 3.4.1 Print Actions (flow-enabled kinds only)

```python
@safe_admin_action
def print_receipt(request, obj)  # Generic receipt
```
Template: employees/document_receipt_pdf.html  
Filename: `EDOC__{code}.pdf`

```python
@safe_admin_action
def print_leaverequest_receipt(request, obj)  # AA only
```
Template: employees/leaverequest_receipt_pdf.html  
Calculates: leave_amount_minutes = daily_expected_minutes × duration_weekdays_inclusive  
Converts to hours (Decimal 0.00)

```python
@safe_admin_action
def print_sicknote_receipt(request, obj)  # KM only
```
Template: employees/sicknote_receipt_pdf.html  
Shows duration_weekdays_inclusive

All print actions record RELEASE:-@employees.employmentdocument signature with 10s window.

#### 3.4.2 Workflow Actions (AA/KM/ZV only)

```python
@transaction.atomic
@safe_admin_action
def submit_doc(request, obj)
```
Action: SUBMIT:ASS@employees.employmentdocument  
Creates system annotation

```python
@transaction.atomic
@safe_admin_action
def withdraw_doc(request, obj)
```
Action: WITHDRAW:ASS@employees.employmentdocument  
Blocked if WIREF or CHAIR approvals exist

```python
@transaction.atomic
@safe_admin_action
def approve_wiref_doc(request, obj)
```
Action: APPROVE:WIREF@employees.employmentdocument

```python
@transaction.atomic
@safe_admin_action
def approve_chair_doc(request, obj)
```
Action: APPROVE:CHAIR@employees.employmentdocument

```python
@transaction.atomic
@safe_admin_action
def reject_wiref_doc(request, obj)
```
Action: REJECT:WIREF@employees.employmentdocument  
Blocked if CHAIR approval exists

```python
@transaction.atomic
@safe_admin_action
def reject_chair_doc(request, obj)
```
Action: REJECT:CHAIR@employees.employmentdocument  
Blocked if CHAIR approval exists

**Action Visibility Logic:**

Non-flow kinds (DV, ZZ): Only relevant print action shown  
Flow kinds (AA, KM, ZV):
- Draft: submit, print
- Submitted: withdraw, approve_wiref, reject_wiref, print
- WIREF approved: approve_chair, reject_chair, print
- CHAIR approved (final): print only

**Permissions:**
- Delete allowed only for draft (not submitted) documents
- No bulk delete from changelist

**Versioning:** Concurrency control via AutoIncVersionField

---

### 3.5 TimeSheet Admin

**Registration:** `@admin.register(TimeSheet)`

**List Display:**
- status_text (workflow state badge), employee, period_label (YYYY-MM), minutes_summary (total/expected Δdelta), updated_at

**Filters:**
- `TimeSheetStateFilter` (custom): draft, submitted, approved_wiref, approved_all
- year, month

**Filter Implementation:**

Uses Subqueries to compute:
- `_last_submit_at`: Latest SUBMIT:ASS timestamp
- `_last_withdraw_at`: Latest WITHDRAW:ASS timestamp
- `_has_wiref`: Exists(APPROVE:WIREF)
- `_has_chair`: Exists(APPROVE:CHAIR)
- `_is_submitted`: Boolean expression (SUBMIT exists AND (no WITHDRAW OR SUBMIT > WITHDRAW))

**Search:**
- employee person/role names

**Fieldsets:**
1. Scope: employee, year, month, totals_preview (readonly computed)
2. Work Calendar: work_calendar_preview (readonly), work_infobox (readonly)
3. Leave Calendar: leave_calendar_preview (readonly), pto_infobox (readonly)
4. Workflow & HankoSign: pdf_file (readonly), signatures_box (readonly)
5. System: version, created_at, updated_at (readonly)

**Inline:**
- AnnotationInline for comments

#### 3.5.1 Calendar Previews

Both calendars rendered server-side, weekdays only (Mon-Fri):

```python
@admin.display
def work_calendar_preview(obj)
```
Template: admin/employees/timesheet_calendar.html  
Shows: WORK, OTHER entries  
Allow kinds: "work"

```python
@admin.display
def leave_calendar_preview(obj)
```
Template: admin/employees/timesheet_calendar.html  
Shows: LEAVE, SICK entries  
Allow kinds: "leave"

**Calendar Features:**
- Weekdays only (Mon-Fri), leading/trailing spacers for column alignment
- Public holidays highlighted (from active HolidayCalendar)
- Entry chips showing kind, minutes, comment
- Cell colors: work (blue), leave (orange), sick (red), holiday (gray), empty
- Modal add links: `/admin/employees/timeentry/add/?timesheet={id}&allow_kinds={work|leave}&date={date}`
- Locked calendars: add buttons hidden

#### 3.5.2 Infoboxes

```python
@admin.display
def work_infobox(obj)
```
Template: admin/employees/work_infobox.html  
Shows: expected, worked, credit, total, delta (surplus/deficit), opening/closing saldo, lock status

```python
@admin.display
def pto_infobox(obj)
```
Template: admin/employees/pto_infobox.html  
Shows: PTO year label, period, daily rate, entitlement, carry-in, adjustments, taken, remaining

```python
@admin.display
def totals_preview(obj)
```
Template: admin/employees/timesheet_totals.html  
Summary: total/expected with delta

#### 3.5.3 Lock Logic

```python
def _is_locked(request, obj) -> bool
```
- Returns True if state_snapshot["locked"] AND user is not manager
- Managers bypass all locks
- Locked sheets: no TimeEntry add/change/delete, including via inline

#### 3.5.4 Object Actions

```python
@safe_admin_action
def print_timesheet(request, obj)
```
- Records RELEASE:-@employees.timesheet signature with 10s window
- Template: employees/timesheet_pdf.html
- Filename: `JOURNAL_{lastname}_{YYYY-MM}.pdf`
- Context: ts, employee, person, role, leave_year, entries, signatures, signers

**Workflow Actions:**

```python
@transaction.atomic
@safe_admin_action
def submit_timesheet(request, obj)
```
Action: SUBMIT:ASS@employees.timesheet

```python
@transaction.atomic
@safe_admin_action
def withdraw_timesheet(request, obj)
```
Action: WITHDRAW:ASS@employees.timesheet  
Blocked if WIREF or CHAIR approvals exist

```python
@transaction.atomic
@safe_admin_action
def approve_wiref(request, obj)
```
Action: APPROVE:WIREF@employees.timesheet

```python
@transaction.atomic
@safe_admin_action
def approve_chair(request, obj)
```
Action: APPROVE:CHAIR@employees.timesheet

```python
@transaction.atomic
@safe_admin_action
def reject_wiref(request, obj)
```
Action: REJECT:WIREF@employees.timesheet  
Blocked if CHAIR approval exists

```python
@transaction.atomic
@safe_admin_action
def reject_chair(request, obj)
```
Action: REJECT:CHAIR@employees.timesheet  
Blocked if CHAIR approval exists

```python
@safe_admin_action
def lock_timesheet(request, obj)
```
Action: LOCK:-@employees.timesheet  
Visible only after CHAIR approval

```python
@safe_admin_action
def unlock_timesheet(request, obj)
```
Action: UNLOCK:-@employees.timesheet  
Visible only if explicit_locked=True

**Action Visibility Logic:**

Draft: submit, print  
Submitted: withdraw, approve_wiref, reject_wiref, print  
WIREF approved: approve_chair, reject_chair, print  
CHAIR approved: lock (if not locked), unlock (if locked), print

**Permissions:**
- No delete permission
- Non-superusers: employee, year, month readonly after creation
- Non-superusers: TimeEntry inline hidden (modal access only via calendar)

**Versioning:** Concurrency control via AutoIncVersionField

**Inline Visibility:**
- Superusers see TimeEntryInline in change form
- Non-superusers: inline hidden, must use calendar modals

---

### 3.6 TimeEntry Admin

**Registration:** `@admin.register(TimeEntry)`  
**Visibility:** Hidden from sidebar (`get_model_perms` returns {})

**Purpose:** Backend-only admin for direct edits and modal additions from TimeSheet calendars.

**Form:** `TimeEntryAdminForm`
- Filters kind choices: PUBLIC_HOLIDAY not selectable
- Normalizes start_time/end_time to :00 seconds
- Hidden timesheet field (passed via GET/POST)
- AdminTimeWidget accepting HH:MM or HH:MM:SS formats

**List Display:**
- timesheet, date, minutes, kind, short_comment (60 char truncation), updated_at

**Filters:**
- timesheet, kind, date

**Fields (conditional):**

Default (work/other):
```
timesheet, date, kind, start_time, end_time, minutes, comment, version
```

Leave flow (allow_kinds=leave OR kind in LEAVE/SICK):
```
timesheet, date, kind, comment, version
```
(start_time, end_time, minutes hidden via form modification)

**Query Parameter Support:**

From TimeSheet calendar modals:
- `?timesheet={id}` - auto-fills and hides timesheet field
- `?date={YYYY-MM-DD}` - pre-fills date
- `?allow_kinds=work` - filters kinds to WORK/OTHER, initializes kind=WORK
- `?allow_kinds=leave` - filters kinds to LEAVE/SICK, initializes kind=LEAVE, hides time fields
- `?kind={KIND}` - pre-selects and optionally hides kind field

**Popup/Modal Behavior:**

```python
def response_add(request, obj, post_url_continue=None)
def response_change(request, obj)
```

If `_popup` in GET/POST:
```javascript
// Close Jazzmin modal and refresh parent
window.top.location.reload();
window.close();
```

If `next` parameter present: redirect to that URL (typically back to timesheet).

**Parent Lock Enforcement:**

```python
def _parent_locked(request, obj=None) -> bool
```
- Checks if parent TimeSheet is locked via TimeSheetAdmin._is_locked()
- If locked: blocks add/change/delete permissions
- Managers bypass locks

**Permissions:**
- All CRUD operations blocked if parent timesheet locked (unless manager)

**Inline Usage:**

```python
class TimeEntryInline(StackedInlinePaginated)
```
- per_page=10, pagination_key="time-entry"
- Calls parent TimeSheetAdmin._is_locked() to control add/change/delete
- max_num=200
- ordering=("date",)

**Versioning:** Concurrency control via AutoIncVersionField

---

### 3.7 HolidayCalendar Admin

**Registration:** `@admin.register(HolidayCalendar)`

**List Display:**
- name, is_active, updated_at

**Filters:**
- is_active

**Fieldsets:**
1. Basics: name, is_active
2. Rules: rules_text (TextField)
3. System: created_at, updated_at (readonly)

**Permissions:**
- No delete permission

**Import/Export:** Supported via HolidayCalendarResource

**History:** simple_history tracked

---

## 4. Management Commands

### 4.1 bootstrap_holidays

**Command:** `python manage.py bootstrap_holidays [--file FILE] [--dry-run]`

**Purpose:** Load/update HolidayCalendar from YAML (idempotent).

**YAML Format:**

```yaml
calendars:
  - name: "Austrian Holidays 2025"
    is_active: true
    rules: |
      01-01 | New Year | Neujahr
      01-06 | Epiphany | Heilige Drei Könige
      EASTER+1 | Easter Monday | Ostermontag
      05-01 | Labour Day | Staatsfeiertag
      EASTER+39 | Ascension Day | Christi Himmelfahrt
      EASTER+50 | Whit Monday | Pfingstmontag
      EASTER+60 | Corpus Christi | Fronleichnam
      08-15 | Assumption Day | Mariä Himmelfahrt
      10-26 | National Day | Nationalfeiertag
      11-01 | All Saints' Day | Allerheiligen
      12-08 | Immaculate Conception | Mariä Empfängnis
      12-25 | Christmas Day | Weihnachten
      12-26 | St. Stephen's Day | Stefanitag
```

**File Resolution:**

Non-sensitive (default): `employees/fixtures/holiday_calendar.yaml`  
Sensitive (not applicable): N/A

**Behavior:**
- Creates new calendars
- Updates changed fields (is_active, rules_text)
- Reports: created, updated, unchanged counts
- Validates with full_clean() before save
- `--dry-run`: shows changes without applying

**Output:**
```
Created: Austrian Holidays 2025
✓ Bootstrap complete! 1 created.
```

---

## 5. Workflow States

### 5.1 EmploymentDocument (AA/KM/ZV)

**Draft:**
- Actions: Submit, Print
- Edit: Full access
- Delete: Allowed

**Submitted:**
- Actions: Withdraw, Approve(WiRef), Reject(WiRef), Print
- Edit: Locked (non-managers)
- Delete: Blocked

**WiRef Approved:**
- Actions: Approve(Chair), Reject(Chair), Print
- Edit: Locked
- Delete: Blocked

**Chair Approved (Final):**
- Actions: Print only
- Edit: Locked
- Delete: Blocked

### 5.2 TimeSheet

**Draft:**
- Actions: Submit, Print
- Calendar: Editable
- Entries: Full CRUD

**Submitted:**
- Actions: Withdraw, Approve(WiRef), Reject(WiRef), Print
- Calendar: Locked (non-managers)
- Entries: Locked (non-managers)

**WiRef Approved:**
- Actions: Approve(Chair), Reject(Chair), Print
- Calendar: Locked
- Entries: Locked

**Chair Approved:**
- Actions: Lock, Print
- Calendar: Locked
- Entries: Locked

**Explicit Locked:**
- Actions: Unlock, Print
- Calendar: Locked
- Entries: Locked
- Note: Managers can always bypass locks

---

## 6. Key Features

### 6.1 Time Account System

**Positive Saldo:** Employee has credit (worked more than expected)  
**Negative Saldo:** Employee has deficit (worked less than expected)

**Monthly Flow:**
1. TimeSheet created → snapshots opening_saldo_minutes from Employee.saldo_minutes
2. Expected calculated: workdays (Mon-Fri) - holidays × daily_expected_minutes
3. Worked accumulated: sum of WORK entries
4. Credit accumulated: sum of LEAVE + SICK entries
5. Closing calculated: opening + worked + credit - expected
6. When finalized: Employee.saldo_minutes updated to closing_saldo_minutes

### 6.2 PTO System

**Flexible Reset Dates:**
- Default: Jan 1 (standard calendar year)
- Custom: Any month/day (e.g., July 1 for academic year)

**Automatic Carry-Over:**
- No cap on carry-over
- Previous year's remaining_minutes → next year's carry_in_minutes

**Taken Calculation:**
- Real-time: queries sum of TimeEntry.LEAVE within PTO year [start, end)
- Deducted from: entitlement + carry_in + manual_adjust

**Manual Adjustments:**
- manual_adjust_minutes field for corrections
- Can be positive (grant extra days) or negative (deduct days)

### 6.3 Holiday Calendar

**Flexible Rule System:**
- Fixed annual dates (e.g., Christmas)
- Easter-relative dates (e.g., Easter Monday = EASTER+1)
- One-off dates (e.g., bridge days)
- Bilingual labels (EN/DE)

**Workday Calculation:**
- Mon-Fri minus public holidays
- Used for TimeSheet.expected_minutes
- Used for EmploymentDocument duration calculations
- Blocks WORK entries on holidays (prevents double-counting)

### 6.4 Document Workflows

**Three-Stage Approval:**
1. **ASS (Associate):** Employee submits document
2. **WIREF (Wirtschaftsreferent):** Finance officer approval
3. **CHAIR (Chairperson):** Final executive approval

**Rejection Handling:**
- Can reject at WIREF stage → returns to draft
- Can reject at CHAIR stage → returns to WIREF
- Cannot reject after CHAIR approval (final)

**Withdrawal:**
- Available before any approvals
- Blocked once WIREF or CHAIR approves

### 6.5 Calendar Interface

**Weekday-Only Display:**
- Shows Mon-Fri only (5 columns)
- Auto-calculates leading/trailing spacers
- Highlights holidays from active HolidayCalendar

**Dual Calendar System:**
- **Work Calendar:** WORK + OTHER entries, blue/gray colors
- **Leave Calendar:** LEAVE + SICK entries, orange/red colors

**Modal Entry Creation:**
- Click date → opens TimeEntry admin in modal
- Pre-filled: timesheet, date, appropriate kind filter
- Auto-closes and refreshes parent on save

**Entry Chips:**
- Show: kind badge, minutes (H:MM format), comment preview
- Click → edit entry
- Delete button (if not locked)

### 6.6 Concurrency & Race Conditions

**Version Fields:**
- EmploymentDocument.version (AutoIncVersionField)
- TimeSheet.version (AutoIncVersionField)
- TimeEntry.version (AutoIncVersionField)

**TimeSheet Creation Race:**
- 5-attempt retry with 0.1s delay
- Catches IntegrityError on unique_together(employee, year, month)

**Aggregate Recomputation:**
- Uses DB-level SELECT FOR UPDATE lock
- Direct UPDATE query (bypasses save() version conflicts)
- Triggered on every TimeEntry save/delete

### 6.7 Lock Mechanics

**Workflow Lock:**
- Automatically engaged when submitted or approved
- Based on state_snapshot["locked"]

**Explicit Lock:**
- Manual LOCK action available after CHAIR approval
- Creates LOCK:-@employees.timesheet signature
- Prevents any modifications (even by workflow unlock)
- Only UNLOCK action can release

**Manager Bypass:**
- Managers (via is_employees_manager()) bypass all locks
- Can edit locked sheets
- Can add/delete entries in locked months

---

## 7. Bootstrap Integration

Called from master `bootstrap_unihanko` command:

```bash
# Standalone
python manage.py bootstrap_holidays [--dry-run]

# Via master orchestrator
python manage.py bootstrap_unihanko [--dry-run]
```

**Order in Master:**
1. orginfo
2. acls
3. actions
4. roles
5. reasons
6. **holidays** ← this command
7. fiscalyears
8. ...

---

## 8. Dependencies

**Imports:**
- `people.models.PersonRole` - employee link
- `hankosign.utils` - workflow signature functions
- `hankosign.models.Signature` - signature queries
- `annotations.admin.AnnotationInline` - comment support
- `annotations.views.create_system_annotation` - workflow annotations
- `organisation.models.OrgInfo` - PDF headers
- `core.admin_mixins` - safe actions, guards, decorators
- `core.pdf.render_pdf_response` - PDF generation
- `core.utils.authz.is_employees_manager` - permission check
- `core.utils.bool_admin_status` - status badge helpers
- `core.utils.weekday_helper.weekdays_between` - workday calculation

**External Packages:**
- simple_history - model history tracking
- concurrency - version fields for optimistic locking
- django_object_actions - admin object actions
- import_export - CSV/Excel import/export
- django_admin_inline_paginator_plus - paginated inlines

---

## 9. Notes

**Timesheet Aggregates:**
- Maintained as denormalized fields for performance
- Recomputed atomically on every TimeEntry change
- No race conditions due to SELECT FOR UPDATE + direct UPDATE

**PTO Auto-Provisioning:**
- EmployeeLeaveYear created automatically on first LEAVE entry
- Ensures year exists before saving entry
- Safe to call repeatedly (idempotent)

**Minutes vs. Hours:**
- All internal storage in minutes for precision
- UI displays formatted as H:MM
- PDF reports may show hours as Decimal(0.00)

**5-Day Week Assumption:**
- daily_expected_minutes = weekly_minutes / 5
- Workday calculations use Mon-Fri only
- Holidays reduce expected work time

**Manager Privileges:**
- Full access to all locked sheets
- Can see/edit PTO year inline
- Can bypass all workflow locks
- Determined by ACL group membership

**Document Code Uniqueness:**
- Auto-generated on save if empty
- Sequential suffix (-2, -3, etc.) for duplicates
- Never changes after creation

**Template Locations:**
- PDF templates in global `templates/employees/` directory
- Admin widgets in `templates/admin/employees/` directory
- Not included in module package

---

## 10. File Structure

```
employees/
├── __init__.py
├── apps.py                                    # Standard config
├── models.py                                  # 906 lines
│   ├── helpers (minutes_to_hhmm, easter_date, etc.)
│   ├── HolidayCalendar
│   ├── Employee
│   ├── EmployeeLeaveYear
│   ├── EmploymentDocument
│   ├── TimeSheet
│   └── TimeEntry
├── admin.py                                   # 1653 lines
│   ├── Import/Export resources
│   ├── ManagerEditableGateMixin
│   ├── TimeEntryAdminForm
│   ├── TimeEntryInline
│   ├── EmploymentDocumentInline
│   ├── EmployeeLeaveYearInline
│   ├── EmployeeAdmin
│   ├── EmploymentDocumentAdmin (+ form)
│   ├── TimeSheetAdmin (+ StateFilter)
│   ├── TimeEntryAdmin
│   └── HolidayCalendarAdmin
├── views.py                                   # Empty placeholder
├── tests.py                                   # Empty placeholder
├── management/
│   └── commands/
│       └── bootstrap_holidays.py              # 125 lines
└── migrations/                                # Django migrations
```

Total lines: ~3,480 (excluding migrations)

---

**Version:** 1.0.0  
**Last Updated:** 2025-12-08  
**Author:** Sven (vas)