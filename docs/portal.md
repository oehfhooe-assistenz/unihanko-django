# PORTAL.md

**Module:** `portal`  
**Purpose:** Public self-service portal for ECTS filing and payment plan management  
**Version:** 1.0.0  
**Dependencies:** academia (InboxRequest), finances (PaymentPlan), people (Person), organisation (OrgInfo)

---

## 1. Overview

The portal module provides external, unauthenticated access for personnel to file ECTS reimbursement requests and manage payment plan banking details. It operates as a **public filing platform** with no models of its own, acting as a gateway to other modules.

**Key Features:**
- **No authentication required** - Access via codes (semester codes, reference codes, PACs)
- **CAPTCHA protection** - django-simple-captcha for form submissions
- **Rate limiting** - django-ratelimit prevents abuse
- **Session-based access** - Temporary authentication via access codes
- **PDF generation** - Public access to forms via reference/plan codes
- **Security validation** - PDF upload scanning for embedded files/JavaScript

**Two Main Portals:**

1. **ECTS Reimbursement Center** (`/portal/academia/`)
   - File ECTS reimbursement requests
   - Upload signed forms
   - Track request status

2. **Payment Plan Portal** (`/portal/payments/`)
   - View payment plans
   - Complete banking details
   - Upload signed payment plan forms

---

## 2. Structure

**No Models:** Portal has no database models - it operates entirely on models from other modules.

**File Organization:**

```
portal/
├── __init__.py
├── apps.py                          # Standard config
├── models.py                        # Empty placeholder
├── admin.py                         # Empty placeholder
├── views.py                         # 530 lines - main logic
├── urls.py                          # 14 lines - main router
├── academia_urls.py                 # 16 lines - ECTS endpoints
├── payments_urls.py                 # 24 lines - payment endpoints
├── forms.py                         # 347 lines - all forms
├── utils.py                         # 48 lines - PDF validation
└── tests.py                         # Test suite
```

Total lines: ~939 (excluding tests)

---

## 3. URL Structure

### 3.1 Main Router (urls.py)

**Namespace:** `portal`

```python
/portal/                              # Portal home (landing page)
/portal/academia/...                  # ECTS Reimbursement Center
/portal/payments/...                  # Payment Plan Portal
```

---

### 3.2 ECTS Academia URLs (academia_urls.py)

**Namespace:** `portal:academia`

```python
/portal/academia/                     # Semester list (landing)
/portal/academia/semester/<int:semester_id>/access/
                                      # Access code entry
/portal/academia/semester/<int:semester_id>/file/
                                      # File new request
/portal/academia/status/<str:reference_code>/
                                      # Status check and upload
/portal/academia/pdf/<str:reference_code>/
                                      # Download PDF
```

---

### 3.3 Payment Portal URLs (payments_urls.py)

**Namespace:** `portal:payments`

```python
/portal/payments/                     # Fiscal year list (landing)
/portal/payments/<str:fy_code>/access/
                                      # PAC entry
/portal/payments/<str:fy_code>/plans/
                                      # Plan list (authenticated)
/portal/payments/plan/<str:plan_code>/pdf/
                                      # Download PDF (public)
```

---

## 4. Views

### 4.1 Common Utilities

**get_client_ip(request):**

Extracts client IP for audit trails.

**Logic:**
1. Tries HTTP_X_FORWARDED_FOR (proxy-aware)
2. Falls back to REMOTE_ADDR
3. Splits comma-separated IPs, takes first

**Used by:** file_request, plan_list (submission_ip field)

---

### 4.2 Portal Landing

**portal_home**

- **URL:** `/portal/`
- **Rate limit:** 30/min per IP
- **Template:** portal/home.html
- **Purpose:** Landing page with menu to choose ECTS or payments

---

## 5. ECTS Reimbursement Center Views

### 5.1 semester_list

**URL:** `/portal/academia/`

**Rate limit:** 30/min per IP

**Purpose:** Landing page showing open semesters.

**Query Logic:**
- Filters Semester.objects by filing_start <= now <= filing_end
- Orders by -start_date (newest first)

**Status Check:**
- GET params: ?check_status=1&reference_code=XXXX
- Redirects to status page if found
- Error message if not found

**Template:** portal/semester_list.html

**Context:**
- open_semesters
- page_title

---

### 5.2 access_login

**URL:** `/portal/academia/semester/<int:semester_id>/access/`

**Rate limit:** 30/min per IP

**Methods:** GET, POST

**Purpose:** Access code entry page (dual-purpose).

**Access Types:**

1. **Semester code** (new filing):
   - Validates against semester.access_password
   - Sets session: semester_id, semester_authenticated
   - Redirects to file_request

2. **Reference code** (status check):
   - Format: XXXX-YYYY-#### (InboxRequest.reference_code)
   - Validates against InboxRequest
   - Redirects to status page

**Form:** AccessCodeForm

**Template:** portal/access_login.html

**Context:**
- form
- semester
- page_title

**Validation:**
- Semester must have filing window open
- Access code must match semester or be valid reference

---

### 5.3 file_request

**URL:** `/portal/academia/semester/<int:semester_id>/file/`

**Rate limit:** 20/min per IP

**Methods:** GET, POST

**Purpose:** File new ECTS reimbursement request (first step).

**Session Check:**
- Requires semester_authenticated=True in session
- Requires semester_id match

**Workflow:**

1. **Select PersonRole:**
   - Filtered by overlap with semester dates
   - Excludes system roles
   - Shows name, role, dates, ECTS cap

2. **Add Courses:**
   - CourseFormSet (up to 6 courses)
   - Fields: course_code, course_name, ects_amount
   - Validation: At least one course required

3. **Confirm Affidavit:**
   - affidavit1_confirmed checkbox (required)
   - Text from OrgInfo.ects_affidavit_1

4. **Create InboxRequest:**
   - Atomic transaction
   - Duplicate check: person+semester
   - Sets filing_source='PUBLIC'
   - Records affidavit1_confirmed_at + submission_ip
   - Creates InboxCourse objects

5. **Validate ECTS:**
   - Calls validate_ects_total()
   - Shows warning if exceeds role cap

6. **Redirect:**
   - Clears session (semester_authenticated)
   - Redirects to status page with reference_code

**Forms:**
- FileRequestForm (person_role, notes, affidavit)
- CourseFormSet (6 courses)

**Template:** portal/file_request.html

**Context:**
- form
- course_formset
- semester
- org
- affidavit_1
- page_title

**Duplicate Handling:**
- Shows existing reference code
- Redirects to status page

**IntegrityError Handling:**
- Catches race condition duplicates
- Redirects to existing request

---

### 5.4 status

**URL:** `/portal/academia/status/<str:reference_code>/`

**Rate limit:** 30/min per IP

**Methods:** GET, POST

**Purpose:** Status check and form upload (second step).

**Display:**
- Request details (person, role, courses, ECTS)
- Current stage (DRAFT/SUBMITTED/PROCESSED/COMPLETED/CANCELLED)
- ECTS validation message
- Upload form (if DRAFT or SUBMITTED and not yet uploaded)
- Download PDF link

**Upload Logic (POST):**
- Only if stage in (DRAFT, SUBMITTED)
- Only if uploaded_form not already present
- Validates PDF (security checks)
- Sets uploaded_form_at, affidavit2_confirmed_at
- Success message: "Form uploaded successfully!"

**Form:** UploadFormForm

**Template:** portal/status.html

**Context:**
- inbox_request
- stage
- org
- affidavit_2
- upload_form
- is_valid, max_ects, total_ects, validation_message
- page_title

**Affidavit 2:**
- Text from OrgInfo.ects_affidavit_2
- Shown during upload step

---

### 5.5 request_pdf

**URL:** `/portal/academia/pdf/<str:reference_code>/`

**Rate limit:** 60/min per IP

**Method:** GET

**Purpose:** Generate and download ECTS request PDF.

**Access:** Public (no authentication) via reference_code.

**Content:**
- Request details (person, role, semester)
- Course list with ECTS
- HankoSign attestation seal (if signatures exist)
- Signer lines: Person + LV-Leitung

**Template:** academia/inboxrequest_form_pdf.html

**Filename:** ECTS_{reference_code}_{lastname}_{date}.pdf

---

## 6. Payment Plan Portal Views

### 6.1 fy_list

**URL:** `/portal/payments/`

**Rate limit:** 30/min per IP

**Purpose:** Landing page showing active fiscal years.

**Query Logic:**
- Filters FiscalYear.objects by is_active=True
- Orders by -start (newest first)

**Template:** portal/payments/fy_list.html

**Context:**
- fiscal_years
- page_title

---

### 6.2 payment_access

**URL:** `/portal/payments/<str:fy_code>/access/`

**Rate limit:** 20/min per IP

**Methods:** GET, POST

**Purpose:** Enter Personal Access Code (PAC).

**Workflow:**

1. **Validate PAC:**
   - Looks up Person by personal_access_code
   - Case-insensitive match

2. **Set Session:**
   - payment_person_id
   - payment_fiscal_year_id

3. **Redirect:**
   - To plan_list for authenticated access

**Form:** PaymentAccessForm

**Template:** portal/payments/access.html

**Context:**
- form
- fiscal_year
- page_title

**CAPTCHA:** Required (django-simple-captcha)

---

### 6.3 plan_list

**URL:** `/portal/payments/<str:fy_code>/plans/`

**Rate limit:** 30/min per IP

**Methods:** GET, POST

**Purpose:** Consolidated payment plans view with inline editing.

**Session Check:**
- Requires payment_person_id in session
- Requires payment_fiscal_year_id match

**Display:**
- All PaymentPlan objects for person+fiscal_year
- Status: DRAFT, PENDING, ACTIVE, FINISHED, CANCELLED
- Inline forms for DRAFT plans

**POST Actions:**

**1. save_banking (action=save_banking):**
- Only for DRAFT status
- Validates banking details form
- Auto-generates reference if empty: REF-{plan_code}
- Sets submission_ip
- Success: "Banking details saved! Now: review terms, download PDF, upload signed form"
- Redirects with ?plan_saved={plan_code} to keep accordion open

**2. upload_form (action=upload_form):**
- For plans with banking complete but not yet signed
- Validates PaymentUploadForm (pdf_file + signed_person_at)
- Sets pdf_file and signed_person_at
- Success: "Payment plan completed! Form uploaded and being processed"
- Redirects to plan_list

**Forms per Plan:**
- plan_forms: BankingDetailsForm for DRAFT plans
- upload_forms: PaymentUploadForm for plans ready to upload

**Template:** portal/payments/plan_list.html

**Context:**
- person
- fiscal_year
- all_plans (all PaymentPlan objects)
- draft_plans (filtered DRAFT only)
- plan_forms (dict: plan_id → form)
- upload_forms (dict: plan_id → form)
- org
- page_title

**Accordion Design:**
- Anti-ping-pong: All steps visible on one page
- Expand/collapse per plan
- Query param ?plan_saved={code} auto-expands plan

---

### 6.4 plan_pdf

**URL:** `/portal/payments/plan/<str:plan_code>/pdf/`

**Rate limit:** 60/min per IP

**Method:** GET

**Purpose:** Generate and download payment plan PDF.

**Access:** Public (no authentication) via plan_code.

**Content:**
- Payment plan details (person, role, fiscal year)
- Banking details (if set)
- Monthly breakdown with proration
- HankoSign attestation seal (shows workflow status)
- Signer lines: Person + WiRef + Chair

**Template:** finances/paymentplan_pdf.html

**Filename:** FUGEB_{plan_code}_{role}_{lastname}_{datetime}.pdf

**Note:** Works for all stages (DRAFT → FINISHED), reflects current state.

---

## 7. Forms

### 7.1 ECTS Forms

**AccessCodeForm:**

**Fields:**
- access_code: CharField(50) - semester code or reference code
- captcha: CaptchaField

**Validation:**
- Dual-purpose detection:
  1. If format XXXX-YYYY-#### → Try as reference code
  2. Else → Try as semester.access_password
- Sets self.access_type ('semester' or 'reference')
- Sets self.inbox_request if reference code valid

**CourseForm:**

**Fields:**
- course_code: CharField(20) optional - e.g., LV101
- course_name: CharField(200) optional - e.g., Advanced Mathematics
- ects_amount: DecimalField(4,1) optional - 0.5 to 15.0, step 0.5

**Validation:**
- If ECTS provided: At least one of code or name required
- If code or name provided: ECTS required
- Converts whole numbers to .0 format

**CourseFormSet:**
- Factory: formset_factory(CourseForm)
- extra=6, max_num=6

**FileRequestForm:**

**Fields:**
- person_role: ModelChoiceField - filtered by semester overlap
- student_note: CharField textarea optional
- affidavit1_confirmed: BooleanField required

**Custom Label:**
- "{Last}, {First} - {Role} ({start} → {end}) - {ECTS} ECTS"

**Filtering:**
- Overlaps semester dates
- Excludes role.is_system=True

**UploadFormForm:**

**Fields:**
- uploaded_form: FileField - PDF, max 20MB
- affidavit2_confirmed: BooleanField required

**Validation:**
- Calls validate_pdf_upload()
- Security checks: no embedded files, no JavaScript

---

### 7.2 Payment Forms

**PaymentAccessForm:**

**Fields:**
- pac: CharField(19) - personal access code
- captcha: CaptchaField

**Validation:**
- Looks up Person by personal_access_code
- Case-insensitive
- Sets self.person if valid

**BankingDetailsForm:**

**ModelForm:** PaymentPlan

**Fields:**
- payee_name: CharField - account holder name
- iban: CharField - Austrian IBAN (AT + 18 digits)
- bic: CharField - 8 or 11 chars
- address: TextField - full postal address

**Validation:**
- IBAN: Must start with AT, exactly 20 chars, normalized (spaces removed, uppercase)
- BIC: 8 or 11 chars, uppercase
- Address: Min 5 chars, required

**Note:** Does NOT include reference field (ÖH manages this).

**PaymentUploadForm:**

**Fields:**
- pdf_file: FileField - PDF, max 20MB
- signed_person_at: DateField - signature date

**Validation:**
- Calls validate_pdf_upload()
- Security checks: no embedded files, no JavaScript

---

## 8. Utilities

### 8.1 validate_pdf_upload

**Function:** `validate_pdf_upload(uploaded_file, max_size_mb=20)`

**Purpose:** Validate and sanitize PDF uploads.

**Checks:**

1. **Size:** Max 20MB (configurable)
2. **Extension:** Must be .pdf
3. **Valid PDF:** pikepdf.open() must succeed
4. **Security:**
   - No embedded files (/EmbeddedFiles)
   - No JavaScript (/JavaScript)

**Returns:** uploaded_file (rewound to position 0)

**Raises:** ValidationError with specific message

**Used by:**
- UploadFormForm.clean_uploaded_form()
- PaymentUploadForm.clean_pdf_file()

---

## 9. Security Features

### 9.1 Rate Limiting

**Package:** django-ratelimit

**Limits:**
- Landing pages: 30/min per IP
- Form submissions: 20/min per IP
- PDF downloads: 60/min per IP

**Method:** Decorator `@ratelimit(key='ip', rate='N/m', method=['GET', 'POST'])`

---

### 9.2 CAPTCHA

**Package:** django-simple-captcha

**Usage:**
- AccessCodeForm (ECTS and payment access)
- PaymentAccessForm

**Purpose:** Bot protection on access code entry.

---

### 9.3 Session-Based Access

**ECTS:**
- Session keys: semester_id, semester_authenticated
- Set on successful access code entry
- Cleared after request submission
- Checked on file_request view

**Payment:**
- Session keys: payment_person_id, payment_fiscal_year_id
- Set on successful PAC entry
- Persist across plan_list interactions
- Checked on plan_list view

**Benefits:**
- No user accounts needed
- Temporary authentication
- Auto-expires with session

---

### 9.4 PDF Validation

**Security Risks:**
- Embedded files (malware)
- JavaScript (XSS, phishing)
- Corrupted PDFs (DoS)

**Mitigation:**
- pikepdf inspection
- Reject dangerous features
- Size limit (20MB)
- Extension check (.pdf)

---

## 10. Workflow Patterns

### 10.1 ECTS Filing Workflow

**Step 1: Access**
1. Browse to /portal/academia/
2. Select open semester
3. Enter semester access code
4. CAPTCHA verification

**Step 2: File Request**
1. Select PersonRole (filtered by semester overlap)
2. Add courses (up to 6)
3. Confirm affidavit 1
4. Submit → Creates InboxRequest with reference_code

**Step 3: Download & Sign**
1. Redirected to status page
2. Download PDF (via reference_code)
3. Sign PDF offline
4. Return to status page (bookmark or status check)

**Step 4: Upload**
1. Enter reference code (if not bookmarked)
2. Confirm affidavit 2
3. Upload signed PDF
4. Done → Admin team processes

**Status Tracking:**
- DRAFT → SUBMITTED → PROCESSED → COMPLETED
- Or CANCELLED at any stage

---

### 10.2 Payment Plan Workflow

**Step 1: Access**
1. Browse to /portal/payments/
2. Select fiscal year
3. Enter Personal Access Code (PAC)
4. CAPTCHA verification

**Step 2: View Plans**
1. See all payment plans for person+FY
2. Each plan shows status (DRAFT, PENDING, ACTIVE, etc.)

**Step 3: Complete Banking (DRAFT plans)**
1. Expand plan accordion
2. Fill banking details form:
   - Payee name
   - IBAN (AT + 18 digits)
   - BIC (8 or 11 chars)
   - Address
3. Submit → Saves details, auto-generates reference

**Step 4: Download & Sign**
1. Download PDF (public access via plan_code)
2. Review terms and payment details
3. Sign PDF offline

**Step 5: Upload**
1. Upload signed PDF
2. Enter signature date
3. Submit → Completes plan, triggers admin workflow

**Status Flow:**
- DRAFT → (submit) → PENDING → ACTIVE → FINISHED
- Or CANCELLED at admin discretion

---

## 11. Templates

**Referenced (not in portal module, but used):**

**ECTS:**
- portal/home.html - landing page
- portal/semester_list.html - semester selection
- portal/access_login.html - access code entry
- portal/file_request.html - request form
- portal/status.html - status check and upload
- academia/inboxrequest_form_pdf.html - PDF template

**Payment:**
- portal/payments/fy_list.html - fiscal year selection
- portal/payments/access.html - PAC entry
- portal/payments/plan_list.html - consolidated plan view
- finances/paymentplan_pdf.html - PDF template

---

## 12. Dependencies

**Django Framework:**
- Sessions (session-based authentication)
- Forms (all form handling)

**Internal Modules:**
- academia.models (InboxRequest, InboxCourse, Semester)
- academia.utils (validate_ects_total)
- finances.models (FiscalYear, PaymentPlan)
- people.models (Person, PersonRole)
- organisation.models (OrgInfo)
- hankosign.utils (seal_signatures_context for PDFs)

**External Packages:**
- django-ratelimit - rate limiting
- django-simple-captcha - CAPTCHA fields
- pikepdf - PDF validation and security checks

**Core Utilities:**
- core.pdf.render_pdf_response - PDF generation

---

## 13. Configuration

### 13.1 Django Settings

**INSTALLED_APPS:**

```python
INSTALLED_APPS = [
    # ...
    "captcha",  # django-simple-captcha
    "portal",
    # ...
]
```

**CAPTCHA Settings:**

```python
CAPTCHA_IMAGE_SIZE = (120, 50)
CAPTCHA_FONT_SIZE = 28
CAPTCHA_BACKGROUND_COLOR = '#ffffff'
CAPTCHA_FOREGROUND_COLOR = '#001100'
CAPTCHA_CHALLENGE_FUNCT = 'captcha.helpers.math_challenge'
```

**Rate Limit Settings:**

```python
RATELIMIT_ENABLE = True
RATELIMIT_USE_CACHE = 'default'  # Redis recommended
```

---

### 13.2 URL Configuration

**Project urls.py:**

```python
urlpatterns = [
    # ...
    path('portal/', include('portal.urls')),
    path('captcha/', include('captcha.urls')),
    # ...
]
```

---

## 14. Notes

**No Authentication:**
- Portal views do NOT require Django User login
- Access via temporary codes (semester, reference, PAC)
- Session-based temporary authentication

**Public Access PDFs:**
- request_pdf: Accessible via reference_code (InboxRequest)
- plan_pdf: Accessible via plan_code (PaymentPlan)
- No authentication check on PDF views
- Used for downloading forms before signing

**Anti-Ping-Pong Design:**
- Payment plan_list shows all steps on one page
- Inline editing with accordions
- No navigation between pages for multi-step process
- Reduces user frustration

**Duplicate Prevention:**
- ECTS: One request per person+semester
- Payment: Handled by PaymentPlan constraints (in finances module)
- IntegrityError handling for race conditions

**IP Logging:**
- submission_ip recorded on file_request
- submission_ip recorded on banking save
- Used for audit trails and abuse detection

**Reference Code Format:**
- ECTS: {SemesterCode}-{PersonInitials}-{Number} (e.g., WS24-MUEL-0001)
- Payment: {FYCode}-{Number} (e.g., WJ24_25-00001)
- Both auto-generated by respective modules

**PAC (Personal Access Code):**
- Stored on Person model (people.Person.personal_access_code)
- Format: XXXX-XXXX (8 chars + hyphen)
- Generated on Person creation
- Shared with personnel for self-service
- Can be regenerated by managers

**ECTS Validation:**
- Calls academia.utils.validate_ects_total()
- Compares total ECTS against role.ects_cap
- Shows warning if exceeded (soft limit)

**Affidavits:**
- ECTS has 2 affidavits (from OrgInfo):
  - affidavit_1: Shown during filing (course list submission)
  - affidavit_2: Shown during upload (signed form submission)
- Payment has disclaimer (from OrgInfo.payment_plan_disclaimer)

**Workflow Integration:**
- ECTS: Creates InboxRequest (DRAFT) → Admin processes
- Payment: Updates PaymentPlan (DRAFT) → Admin approves → ACTIVE

**PDF Generation:**
- Uses core.pdf.render_pdf_response
- Includes HankoSign attestation seal
- Shows workflow status (signatures)
- Timestamped filenames for versioning

---

## 15. File Structure

```
portal/
├── __init__.py
├── apps.py                          # Standard config
├── models.py                        # Empty (8 lines)
├── admin.py                         # Empty (150 bytes)
├── views.py                         # 530 lines - all view logic
├── urls.py                          # 14 lines - main router
├── academia_urls.py                 # 16 lines - ECTS endpoints
├── payments_urls.py                 # 24 lines - payment endpoints
├── forms.py                         # 347 lines - all forms
├── utils.py                         # 48 lines - PDF validation
└── tests.py                         # Test suite
```

Total lines: ~939 (excluding tests)

---

**Version:** 1.0.5  
**Last Updated:** 2025-12-08  
**Author:** Sven (vas)