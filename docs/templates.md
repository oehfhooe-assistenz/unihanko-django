# TEMPLATES.md

**Directory:** `templates/`  
**Purpose:** Template system for UniHanko with Neo-Japanese neobrutalist design  
**Total Files:** 76 templates across 27 directories  
**Version:** 1.0.0

---

## 1. Overview

UniHanko's template system serves three distinct rendering contexts:
1. **Django Admin** - Internal staff interface with custom widgets and displays
2. **PDF Generation** - WeasyPrint-rendered documents with paged media CSS
3. **Public Portal** - External self-service interface with no authentication

**Design Philosophy:**
- **Neo-Japanese Neobrutalist** aesthetic throughout
- Chunky borders (4-5px solid black)
- High contrast color palette (ÖH orange #f2a535, black, white)
- Animated elements (falling cherry blossoms on landing, soup bowls on 404)
- Typography: Noto Sans JP for headers, system fonts for body
- Brutal shadows and text outlines for emphasis

---

## 2. Structure Overview

```
templates/
├── 403.html, 404.html, 500.html           # Error pages (5 files)
├── error_constraint.html                  # DB constraint violation handler
├── maintenance.html                       # Maintenance mode page
├── _includes/                             # Reusable PDF partials (9 files)
├── admin/                                 # Django admin customizations (13 files)
├── pdf/                                   # PDF base templates (3 files)
├── portal/                                # Public portal (10 files)
├── hankosign/                             # Signature UI components (3 files)
├── helppages/                             # Help system widget (1 file)
├── core/                                  # Home landing page (1 file)
├── Module-specific templates:
│   ├── academia/                          # ECTS request PDFs (1 file)
│   ├── academia_audit/                    # ECTS audit PDFs (1 file)
│   ├── assembly/                          # Assembly protocols and certs (5 files)
│   ├── employees/                         # Employee documents (5 files)
│   ├── finances/                          # Payment plan PDFs (4 files)
│   ├── people/                            # Personnel certs and PDFs (7 files)
├── flatpages/                             # Static content (1 file)
├── pages/                                 # About/contact/privacy (3 files)
├── simple_history/                        # History UI (2 files)
└── tane/                                  # Schema and dedup display (2 files)
```

**File Count by Category:**

| Category | Files | Purpose |
|----------|-------|---------|
| Root | 5 | Error pages, maintenance |
| _includes | 9 | Reusable PDF partials |
| admin | 13 | Django admin customizations |
| pdf | 3 | PDF base templates |
| portal | 10 | Public self-service |
| hankosign | 3 | Signature UI |
| helppages | 1 | Help widget |
| Module PDFs | 30 | Document generation |
| Other | 2 | Flatpages, static pages, history, tane |
| **TOTAL** | **76** | |

---

## 3. Error Pages (Root Level)

### 3.1 404.html (354 lines)

**Purpose:** Page Not Found with animated Neo-Japanese theme.

**Design Features:**
- Dark background (#0a0a0a) with radial gradients
- Falling soup bowls (🍜) animation - parallax effect
- Large "404" with brutal text shadow
- Noto Sans JP typography
- Animated "Return Home" button
- Wave pattern overlay

**Animation:** 12 soup bowl emojis falling at different speeds and positions.

**Copy:** "The page wandered off the beaten path. Like a bowl of ramen that escaped the kitchen."

---

### 3.2 403.html (Similar structure)

**Purpose:** Forbidden access error.

**Theme:** Dark with animated background elements.

---

### 3.3 500.html (Similar structure)

**Purpose:** Internal Server Error.

**Theme:** Dark with animated background elements.

---

### 3.4 error_constraint.html (273 lines)

**Purpose:** Database constraint violation handler (custom error page).

**Extends:** admin/base_site.html

**Design:**
- Neo-brutalist card layout with chunky borders
- Grid layout (2fr 1fr) for message + suggestions
- Error icon (⚠️) with brutal styling
- Constraint type detection and friendly explanations:
  - UNIQUE violations
  - FOREIGN KEY violations
  - CHECK constraints
  - NOT NULL violations
- "What This Means" + "What To Do" sections
- Technical details in collapsible section
- Related objects display

**Use Case:** Triggered by core.middleware.ConstraintViolationMiddleware.

---

### 3.5 maintenance.html (284 lines)

**Purpose:** Maintenance mode page with status updates.

**Design:**
- Dark theme with cherry blossom animation
- Falling petals (🌸) like landing page
- Countdown timer if end_time provided
- Status badge (🔧 Under Maintenance)
- Animated progress indicator
- Contact information

**Context Variables:**
- message: Custom maintenance message
- start_time, end_time: Window (optional)
- estimated_duration: Display text

**Use Case:** Shown when MAINTENANCE_MODE=True in settings.

---

## 4. PDF System

### 4.1 Base Templates (pdf/)

**pdf/base.html (445 lines):**

**Purpose:** Master PDF template for WeasyPrint with paged media CSS.

**Features:**

**@page Rules:**
- Size: A4
- Margins: 26mm top, 15mm sides, 20mm bottom
- Running headers: @top-center
- Running footers: @bottom-left (content), @bottom-right (page numbers)
- First page: Hero header (42mm margin-top)

**CSS Variables:**
```css
--brand: #f2a535;    /* ÖH orange */
--ink: #111;
--muted: #6b7280;
--rule: #e5e7eb;
```

**Typography:**
- Font: DejaVu Sans (embeddable), Arial fallback
- Base size: 11px
- Line height: 1.2
- H1: 20px, H2: 16px, H3: 13px

**Components:**
- `.hero-wrap` - First page header with logo + title
- `.header-std` - Running header for subsequent pages
- `.pdf-footer` - Contact info footer
- Tables: Full width, bordered, 10px text
- `.info-table` - Two-column key-value tables
- `.section` - Content sections with borders
- `.signature-boxes` - Signature line grid

**Blocks:**
- `{% block pdf_title %}` - Document title
- `{% block pdf_org_name %}` - Organization name
- `{% block pdf_doc_type %}` - Document type label
- `{% block pdf_header_right %}` - Hero header metadata
- `{% block content %}` - Main content

**Running Elements:**
- `header.header-hero` → position: running(header-hero) - Page 1 only
- `header.header-std` → position: running(header-std) - Pages 2+
- `footer.pdf-footer` → position: running(page-footer) - All pages

---

**pdf/certificate_base.html:**

**Extends:** pdf/base.html

**Purpose:** Base for personnel certificates (appointments, resignations).

**Customizations:**
- Certificate-specific styling
- Official seal placement
- Signature block layouts

---

**pdf/protocol_base.html:**

**Extends:** pdf/base.html

**Purpose:** Base for assembly protocols and session documents.

**Customizations:**
- Protocol header with session metadata
- Agenda item numbering
- Decision recording blocks

---

### 4.2 PDF Includes (_includes/)

**Reusable partials for PDF documents:**

**_org_header.html (19 lines):**
- Organization name and logo
- Used in hero header

**_person_info_section.html:**
- Person details (name, email, matric_no, role)
- Used in personnel documents

**_banking_information.html:**
- IBAN, BIC, payee name, address
- Used in payment plan PDFs

**_date_period.html:**
- Start/end date display
- Used in fiscal year, semester documents

**_info_table.html:**
- Two-column key-value table
- Generic metadata display

**_section.html:**
- Content section with title and border
- Consistent styling

**_disclaimer.html:**
- Legal disclaimers for payment plans
- GDPR notices

**_signature_boxes.html:**
- Grid of signature lines
- Supports 2-6 signers
- Labels: name, role, date

**_signature_seal.html (71 lines):**
- HankoSign attestation seal
- Table: Signatory | Action | When | ID
- Disclaimer about non-qualified signatures
- Used at bottom of all workflow PDFs
- CSS: hankosign/hs_seal.css

---

## 5. Django Admin Templates

### 5.1 Admin Root (admin/)

**change_list.html (16 lines):**

**Extends:** admin/change_list.html (Django default)

**Purpose:** Inject help widget into all model list views.

**Logic:**
```django
{% if show_help_widget %}
    {% render_admin_help %}
{% endif %}
{{ block.super }}
```

**Use:** Shows HelpPage content if exists for model.

---

**change_form.html:**

**Extends:** admin/change_form.html (Django default)

**Purpose:** Inject help widget into all model edit forms.

**Similar to change_list.html** - renders help widget in content block.

---

### 5.2 Admin Subdirectories

**admin/employees/ (4 files):**
- `pto_infobox.html` - PTO balance display widget
- `timesheet_calendar.html` - Monthly timesheet calendar grid
- `timesheet_totals.html` - Totals summary bar
- `work_infobox.html` - Work assignment summary

**admin/filters/ (1 file):**
- `fy_chips.html` - Fiscal year filter chips (horizontal buttons)

**admin/finances/ (3 files):**
- `bank_reference_preview.html` - Live preview of reference field
- `breakdown_preview.html` - Payment plan month breakdown
- `window_preview.html` - Filing window dates preview

**admin/finances/paymentplan/ (2 files):**
- `change_list.html` - Custom payment plan list with FY chips
- `change_list_object_tools.html` - Custom toolbar (bulk actions)

**admin/people/ (3 files):**
- `_date_reason_cell.html` - PersonRole date+reason display
- `_mail_cell.html` - Dual email cell (primary + student)
- `_role_kind.html` - Role kind badge with system indicator

---

## 6. Portal Templates (Public)

### 6.1 Portal Base (portal/)

**base.html:**

**Purpose:** Base template for all public portal pages.

**Features:**
- No authentication UI
- Clean, minimal header
- Language switcher
- Neo-brutalist card styling
- Responsive grid layouts
- Footer with contact

**Blocks:**
- `{% block content %}` - Main content
- `{% block extra_css %}` - Page-specific styles
- `{% block extra_js %}` - Page-specific scripts

---

**home.html (47 lines):**

**Extends:** portal/base.html

**Purpose:** Portal landing page with two main options.

**Layout:**
- Grid: 2 cards side-by-side
- Card 1: 🏛️ ECTS Reimbursement Center
- Card 2: 🪙 Payment Plans Center
- Each card: Header + description + CTA button
- Footer: Contact email

**Design:**
- `.portal-card` - Chunky bordered cards with hover effect
- `.portal-card-header` - Icon + title with accent underline
- `.portal-card-btn` - CTA button with brutal styling

---

### 6.2 Academia Portal (portal/)

**semester_list.html:**
- List of open semesters
- Access code entry or status check form
- Card-based layout

**access_login.html:**
- Access code entry form
- CAPTCHA
- Dual-purpose (semester code or reference code)
- Instructions

**file_request.html:**
- PersonRole selection dropdown
- Course formset (6 rows)
- Affidavit 1 checkbox
- Submit button
- Dynamic course add/remove

**status.html:**
- Request details display
- Stage progress indicator
- ECTS validation message
- Upload form (if applicable)
- PDF download link

---

### 6.3 Payment Portal (portal/payments/)

**fy_list.html:**
- List of active fiscal years
- Card-based layout
- Access links

**access.html:**
- Personal Access Code entry
- CAPTCHA
- Instructions

**plan_list.html:**
- Accordion layout (all plans)
- Per-plan cards:
  - Status badge
  - Banking details form (if DRAFT)
  - PDF download link
  - Upload form (if ready)
- Anti-ping-pong design: all steps visible

---

### 6.4 Portal Includes (portal/includes/)

**stage_progress.html:**
- ECTS request stage indicator
- Visual progress bar
- Status badges: DRAFT → SUBMITTED → PROCESSED → COMPLETED

---

## 7. HankoSign Templates

**signature_box.html (29 lines):**

**Purpose:** Admin interface signature audit trail.

**Display:**
- List of signatures for object
- Table: Signatory | Action | Date | Note
- Empty state: "No signatures recorded"
- Used in admin fieldsets

**Context:** Expects `object` with signatures GenericRelation.

---

**_attestation_seal.html:**

**See:** _includes/_signature_seal.html (same purpose, different location).

---

**specimen_pdf.html:**

**Purpose:** Blank specimen form for signatory PDF signature sample.

**Content:**
- Signatory details
- Blank signature box
- Instructions
- Official seal placeholder

---

## 8. Help System

**helppages/help_widget.html (1 file):**

**Purpose:** Render HelpPage content in admin.

**Display:**
- Collapsible accordion
- Legend (always visible) - quick reference
- Content (collapsible) - detailed help
- Markdown rendering
- Bilingual (DE/EN based on language)

**Usage:**
- Called by admin change_list.html and change_form.html
- Conditional: Only if HelpPage exists for model

---

## 9. Module-Specific Templates

### 9.1 Academia (1 file)

**inboxrequest_form_pdf.html:**
- ECTS reimbursement request PDF
- Person + role + semester info
- Course list table
- ECTS totals
- Signature boxes (Person + LV-Leitung)
- HankoSign attestation seal

---

### 9.2 Academia Audit (1 file)

**audit_semester_pdf.html:**
- Semester-wide ECTS audit report
- Aggregated statistics
- Request breakdown by person/role
- ECTS totals and aliquotation
- Compliance checks

---

### 9.3 Assembly (5 files)

**composition_pdf.html:**
- Assembly composition roster
- Member list with roles
- Term dates
- Signature boxes

**protocol_editor.html:**
- Custom protocol editor UI (PROTOKOL-KUN)
- Session item management
- Inline editing
- Drag-and-drop reordering
- Decision recording

**term_pdf.html:**
- Legislative term overview
- Assembly members
- Session list
- Statistics

**certs/dispatchreceipt_pdf.html:**
- Protocol dispatch confirmation
- Attendee signatures
- Date and session reference

**protocol/session_pdf.html:**
- Full session protocol
- Agenda items
- Decisions and votes
- Attendance list
- Signature boxes

---

### 9.4 Employees (5 files)

**employee_pdf.html:**
- Employee record overview
- Contract details
- Work assignments
- PTO summary

**document_receipt_pdf.html:**
- Document receipt acknowledgment
- Document type and date
- Signature boxes

**leaverequest_receipt_pdf.html:**
- Leave request confirmation
- Dates and reason
- Approval status

**sicknote_receipt_pdf.html:**
- Sick note confirmation
- Dates and doctor info

**timesheet_pdf.html:**
- Monthly timesheet
- Day-by-day grid
- Hours worked
- PTO taken
- Totals
- Signature boxes (Employee + Supervisor)

---

### 9.5 Finances (4 files)

**fiscalyear_pdf.html:**
- Fiscal year details
- Date range
- Active status
- Associated payment plans count

**fiscalyears_list_pdf.html:**
- Roster of fiscal years
- Table: Code | Start | End | Status

**paymentplan_pdf.html:**
- Payment plan form
- Person + role + FY
- Banking details
- Monthly breakdown with proration
- Total amounts
- Disclaimer
- Signature boxes (Person + WiRef + Chair)
- HankoSign attestation seal

**paymentplans_list_pdf.html:**
- Roster of payment plans
- Table: Person | Role | FY | Status | Amount

---

### 9.6 People (7 files)

**person_pdf.html:**
- Personnel record
- Person details
- Role assignments (current and historical)
- Contact info
- Signature boxes

**people_list_pdf.html:**
- Personnel roster
- Table: Name | Email | Matric No | Active Roles

**person_action_code_notice_pdf.html:**
- Personal Access Code info sheet
- PAC displayed prominently
- Usage instructions
- Security notice
- Attestation seal

**certs/appointment_regular.html:**
- Appointment certificate (non-confirmation)
- For: DEPT_CLERK, OTHER roles
- Person + role + dates
- Signature boxes
- Official seal

**certs/appointment_ad_interim.html:**
- Ad interim appointment certificate
- For: DEPT_HEAD (before confirmation)
- Person + role + dates
- "Pending confirmation" notice
- Signature boxes

**certs/appointment_confirmation.html:**
- Post-confirmation certificate
- For: DEPT_HEAD (after confirmation)
- Person + role + dates + confirm_date
- Session reference (elected_via)
- Signature boxes

**certs/resignation.html:**
- Resignation certificate
- Person + role + end_date + end_reason
- Signature boxes

---

### 9.7 Core (1 file)

**home.html:**
- Authenticated staff landing page
- Dashboard with quick links
- Recent activity widgets
- System status

---

### 9.8 Flatpages (1 file)

**default.html:**
- Base template for django.contrib.flatpages
- Markdown content rendering

---

### 9.9 Pages (3 files)

**_about.inc.html:**
- About UniHanko
- System description
- Contact info

**_contact.inc.html:**
- Contact form
- Office hours
- Email addresses

**_privacy.inc.html:**
- Privacy policy
- GDPR compliance statement
- Data handling information

---

### 9.10 Simple History (2 files)

**object_history.html:**
- History view for models with HistoricalRecords
- Timeline of changes
- User and timestamp
- Diff view

**object_history_form.html:**
- Compare two versions
- Side-by-side diff

---

### 9.11 Tane (2 files)

**schema_display.html:**
- Database schema visualization
- Model relationships
- Field details

**dedup_display.html:**
- Duplicate detection results
- Similarity scores
- Merge suggestions

---

## 10. Design System

### 10.1 Color Palette

**Primary:**
- `--brand`: #f2a535 (ÖH orange)
- `--ink`: #111 (near black)
- `--muted`: #6b7280 (gray)
- `--rule`: #e5e7eb (light gray)

**Accents:**
- `--unihanko-accent-primary`: #ff6b35 (orange-red)
- `--unihanko-accent-secondary`: #dc2626 (red)

**Background:**
- `--unihanko-bg-card`: #fafafa (light gray)
- Admin dark mode: #0a0a0a base

---

### 10.2 Typography

**Fonts:**
- Headers: Noto Sans JP (900 weight)
- Body: -apple-system, BlinkMacSystemFont, "Segoe UI"
- PDF: DejaVu Sans (embeddable)

**Scale:**
- H1: 20px (PDF), 1.5-2rem (web)
- H2: 16px (PDF), 1.25-1.5rem (web)
- H3: 13px (PDF), 1.125-1.25rem (web)
- Body: 11px (PDF), 16px (web)

**Styling:**
- Uppercase headers with letter-spacing
- Brutal text shadows for emphasis
- High contrast for readability

---

### 10.3 Brutal Styling

**Borders:**
```css
--brutal-border: 4px solid #000;
border: var(--brutal-border);
```

**Shadows:**
```css
--brutal-shadow: 6px 6px 0 #000;
box-shadow: var(--brutal-shadow);
```

**Text Shadows:**
```css
text-shadow: 
    2px 2px 0 #000,
    3px 3px 0 var(--unihanko-accent-secondary);
```

---

### 10.4 Animations

**Landing Page (core/home.html):**
- Falling cherry blossoms (🌸)
- Parallax effect
- 10 petals at different speeds
- Fade in/out

**404 Page:**
- Falling soup bowls (🍜)
- 12 bowls at different speeds
- Rotate and fade

**Maintenance Page:**
- Falling cherry blossoms
- Countdown timer
- Progress indicator

**Buttons:**
- Hover: scale(1.02)
- Active: scale(0.98)
- Transition: 0.2s ease

---

## 11. Template Tags and Filters

**Used Throughout:**

**Django Built-in:**
- `{% load static %}` - Static files
- `{% load i18n %}` - Internationalization
- `{% load tz %}` - Timezone handling

**Custom (helppages):**
- `{% load help_tags %}` - Help widget rendering
- `{% render_admin_help %}` - Inject HelpPage

**Custom (hankosign):**
- Context processors provide signature rendering helpers

**Admin Widgets:**
- Markdown preview (markdownx)
- Autocomplete selects
- Date/time pickers
- Custom filters

---

## 12. Responsive Design

**Breakpoints:**

```css
/* Mobile first */
@media (min-width: 640px) { /* sm */ }
@media (min-width: 768px) { /* md */ }
@media (min-width: 1024px) { /* lg */ }
@media (min-width: 1280px) { /* xl */ }
```

**Portal:**
- Mobile: Single column
- Tablet: 2-column grid
- Desktop: Full width with max-width: 1200px

**Admin:**
- Django's responsive admin
- Custom mobile-friendly tables
- Collapsible fieldsets

**PDF:**
- Fixed A4 size (210mm x 297mm)
- Print-optimized: No responsive needed

---

## 13. Accessibility

**Features:**
- Semantic HTML5 tags
- ARIA labels where needed
- High contrast colors
- Keyboard navigation
- Screen reader friendly

**WCAG Compliance:**
- Color contrast: AA minimum
- Focus indicators: Visible on all interactive elements
- Alt text: All images (logo, icons)
- Language tags: `<html lang="{{ LANGUAGE_CODE }}">`

---

## 14. Internationalization

**Languages:**
- German (de) - Primary
- English (en) - Secondary

**Coverage:**
- All user-facing strings wrapped in `{% trans %}` or `{% blocktrans %}`
- Portal fully bilingual
- Admin interface bilingual
- PDFs render in selected language

**Language Switcher:**
- Available in portal header
- Session-based
- Persists across pages

---

## 15. PDF Generation

**Process:**
1. Django renders template with context
2. WeasyPrint converts HTML+CSS to PDF
3. Running headers/footers applied
4. Page numbers generated
5. PDF returned via HttpResponse

**Key Utilities:**
- `core.pdf.render_pdf_response()` - Main generator
- Context includes: object, org, signatures

**Challenges Handled:**
- Font embedding (DejaVu Sans)
- Page breaks
- Running elements
- Table splitting
- Image embedding (base64)

**Output:**
- MIME type: application/pdf
- Filename: Dynamic (code_lastname_date.pdf)
- Inline or attachment

---

## 16. Maintenance

**Template Versioning:**
- Header comments: Version, Author, Modified date
- Example:
```html
<!--
Template: base.html
Version: 1.0.0
Author: vas
Modified: 2025-11-27
-->
```

**Consistency:**
- All PDFs extend pdf/base.html
- All portal pages extend portal/base.html
- All admin customizations extend Django defaults
- Includes used for repeated blocks

**Future Expansion:**
- New modules add templates in own directory
- PDF templates extend bases
- Portal templates extend portal/base.html
- Admin templates extend admin/base_site.html

---

## 17. Key Patterns

### 17.1 PDF Document Pattern

```django
{% extends "pdf/base.html" %}
{% load static i18n %}

{% block pdf_title %}Document Title{% endblock %}

{% block pdf_org_name %}{{ org.org_name_long }}{% endblock %}

{% block pdf_doc_type %}Document Type{% endblock %}

{% block pdf_header_right %}
    <div>Reference: {{ object.reference_code }}</div>
    <div>Date: {{ object.created_at|date:"Y-m-d" }}</div>
{% endblock %}

{% block content %}
    {% include "_includes/_person_info_section.html" %}
    
    <!-- Content here -->
    
    {% include "_includes/_signature_boxes.html" with signers=signers %}
    
    {% include "_includes/_signature_seal.html" with signatures=signatures %}
{% endblock %}
```

---

### 17.2 Portal Page Pattern

```django
{% extends "portal/base.html" %}
{% load i18n %}

{% block content %}
<h1 class="page-title">{% trans "Page Title" %}</h1>

<div class="card">
    <form method="post">
        {% csrf_token %}
        {{ form.as_p }}
        <button type="submit" class="btn">
            {% trans "Submit" %}
        </button>
    </form>
</div>
{% endblock %}
```

---

### 17.3 Admin Widget Pattern

```django
<!-- Custom widget for admin display -->
<div class="custom-widget">
    {% if data %}
        <table class="widget-table">
            {% for item in data %}
            <tr>
                <td>{{ item.label }}</td>
                <td>{{ item.value }}</td>
            </tr>
            {% endfor %}
        </table>
    {% else %}
        <p class="empty">No data available.</p>
    {% endif %}
</div>
```

---

## 18. Notes

**Template Inheritance:**
- Deep nesting avoided (max 2 levels)
- Base templates provide blocks
- Child templates override blocks
- No circular inheritance

**Context Processors:**
- OrgInfo available as `org` in many contexts
- Request context always available
- Language in `LANGUAGE_CODE`

**Static Files:**
- Logo: static/img/oeh_logo.png
- HankoSign seal: static/hankosign/hs_seal.css
- Cherry blossoms (CSS animation, no image)

**Security:**
- CSRF tokens in all forms
- No inline JavaScript (CSP-friendly)
- External resources from trusted CDNs only
- User input escaped by default (Django's autoescape)

**Performance:**
- Minimal external dependencies
- Lazy loading for images
- Template fragment caching where appropriate
- Static files served with cache headers

**Browser Support:**
- Modern browsers (last 2 versions)
- IE11 not supported
- Mobile responsive

**PDF Limitations:**
- WeasyPrint: No JavaScript support
- CSS: Subset of web standards
- Fonts: Must be embeddable
- Images: Base64 or filesystem paths

---

## 19. Summary Statistics

**Total Templates:** 76 files

**By Category:**
- Admin: 13 (17%)
- PDF includes: 9 (12%)
- Portal: 10 (13%)
- Module PDFs: 30 (39%)
- Base/Error: 8 (11%)
- Other: 6 (8%)

**By Extension:**
- .html: 76 (100%)

**By Purpose:**
- PDF generation: 42 (55%)
- Admin interface: 13 (17%)
- Portal interface: 10 (13%)
- Error/special: 11 (14%)

**Average File Size:**
- PDF templates: ~150-300 lines
- Portal templates: ~50-150 lines
- Admin widgets: ~20-100 lines
- Error pages: ~300-400 lines

---

**Version:** 1.0.5  
**Last Updated:** 2025-12-08  
**Author:** Sven (vas)