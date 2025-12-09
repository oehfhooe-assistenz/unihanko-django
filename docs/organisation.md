# ORGANISATION.md

**Module:** `organisation`  
**Purpose:** Singleton master data for organisation details, banking, and official signatories  
**Version:** 1.0.0  
**Dependencies:** people (PersonRole), django-solo (SingletonModel)

---

## 1. Overview

Organisation provides a singleton model storing master data for the entire UniHanko installation. This includes:

- **Bilingual organisation names** - German and English, long and short forms
- **Banking details** - IBAN, BIC, bank name/address with validation
- **Legal signatories** - Chair, deputies, financial officer (WiRef) via PersonRole FKs
- **Affidavit texts** - ECTS self-service disclaimers
- **Payment plan disclaimer** - Shown when completing banking details
- **Public filing URL** - External filing endpoint

The singleton pattern ensures only one OrgInfo record exists, accessed via `OrgInfo.get_solo()` or `OrgInfo.get()`.

---

## 2. Model

### 2.1 OrgInfo (Singleton)

**Purpose:** Single source of truth for organisation configuration.

**Base Class:** SingletonModel (from django-solo)

**Fields:**

**Organisation Names (Bilingual):**
- `org_name_long_de`: CharField(200) blank - German long name
- `org_name_short_de`: CharField(80) blank - German short name
- `org_name_long_en`: CharField(200) blank - English long name
- `org_name_short_en`: CharField(80) blank - English short name

**University Names (Bilingual):**
- `uni_name_long_de`: CharField(200) blank - German long name
- `uni_name_short_de`: CharField(120) blank - German short name
- `uni_name_long_en`: CharField(200) blank - English long name
- `uni_name_short_en`: CharField(120) blank - English short name

**Addresses:**
- `org_address`: TextField blank - organisation address (multiline for PDFs/letters)
- `bank_address`: TextField blank - bank address

**Banking & Tax:**
- `bank_name`: CharField(120) blank - bank name
- `bank_iban`: CharField(34) blank - IBAN with format validation
- `bank_bic`: CharField(11) blank - BIC with format validation
- `org_tax_id`: CharField(40) blank - VAT/Tax ID
- `default_reference_label`: CharField(80) blank - default reference for payment plans (e.g., "Rechnung")

**Legal Signatories (PersonRole FKs):**
- `org_chair`: FK(PersonRole, PROTECT) nullable - Chair
- `org_dty_chair1`: FK(PersonRole, PROTECT) nullable - 1st Deputy Chair
- `org_dty_chair2`: FK(PersonRole, PROTECT) nullable - 2nd Deputy Chair
- `org_dty_chair3`: FK(PersonRole, PROTECT) nullable - 3rd Deputy Chair
- `org_wiref`: FK(PersonRole, PROTECT) nullable - Financial Officer (WiRef)
- `org_dty_wiref`: FK(PersonRole, PROTECT) nullable - Deputy Financial Officer

**Public Filing:**
- `org_public_filing_url`: CharField(128) blank - public filing URL (do not change without permission)

**ECTS Self-Service Affidavits:**
- `ects_affidavit_1`: TextField blank - affidavit text for initial course list submission
- `ects_affidavit_2`: TextField blank - affidavit text for signed form upload

**Payment Plan:**
- `payment_plan_disclaimer`: TextField blank - disclaimer shown when completing banking details

**Validation Patterns:**

```python
IBAN_SHAPE = r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$"
BIC_SHAPE  = r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$"
```

**History:** simple_history tracked

**Meta:**
- verbose_name: "Master data"
- verbose_name_plural: "Master data"

---

### 2.2 Methods

**__str__():**

```python
def __str__(self) -> str
```

Returns org_name_short_de or org_name_short_en or "Organisation settings".

**clean():**

```python
def clean(self)
```

1. **IBAN normalization:**
   - Removes spaces
   - Converts to uppercase
   - Validates with _iban_checksum_ok()
   - Raises ValidationError if checksum fails

2. **BIC normalization:**
   - Removes spaces
   - Converts to uppercase

**get() (class method):**

```python
@classmethod
def get(cls) -> "OrgInfo"
```

Convenience accessor, equivalent to `cls.get_solo()`.

**Returns:** The singleton OrgInfo instance.

---

### 2.3 IBAN Validation

**_iban_checksum_ok():**

```python
def _iban_checksum_ok(iban: str) -> bool
```

Validates IBAN using mod-97 algorithm per ISO 13616.

**Algorithm:**
1. Move first 4 chars to end: `AT611904300234573201` → `1904300234573201AT61`
2. Replace letters with numbers: A=10, B=11, ..., Z=35
3. Compute modulo 97 of resulting number
4. Valid if remainder == 1

**Returns:** True if valid, False otherwise.

---

## 3. Admin Interface

### 3.1 OrgInfoAdmin

**Registration:** `@admin.register(OrgInfo)`

**Base Classes:**
- SingletonModelAdmin - ensures single instance
- SimpleHistoryAdmin - history tracking
- HistoryGuardMixin - history protection

**Form:** OrgInfoForm

Custom widgets:
- org_address: Textarea(rows=3)
- bank_address: Textarea(rows=3)

**Autocomplete Fields:**
- org_chair, org_dty_chair1, org_dty_chair2, org_dty_chair3
- org_wiref, org_dty_wiref

**Fieldsets:**

1. **Organisation names:**
   - org_name_long_de
   - org_name_short_de
   - org_name_long_en
   - org_name_short_en

2. **University names:**
   - uni_name_long_de
   - uni_name_short_de
   - uni_name_long_en
   - uni_name_short_en

3. **Addresses:**
   - org_address

4. **Banking & tax:**
   - bank_name
   - bank_address
   - bank_iban
   - bank_bic
   - org_tax_id
   - default_reference_label
   - payment_plan_disclaimer

5. **Legal signatories:**
   - org_chair
   - org_dty_chair1
   - org_dty_chair2
   - org_dty_chair3
   - org_wiref
   - org_dty_wiref

6. **ECTS Self Service Affidavits:**
   - ects_affidavit_1
   - ects_affidavit_2

**Permissions:**

```python
def has_view_permission(request, obj=None)
```
Checks `organisation.view_orginfo` permission.

```python
def has_change_permission(request, obj=None)
```
Checks `organisation.change_orginfo` permission.

```python
def get_model_perms(request)
```
Controls sidebar visibility:
- Hides menu entry if user has no view permission
- Returns {"view": True} for users with view access

```python
def get_readonly_fields(request, obj=None)
```
Makes all fields readonly for users with only view permission (no change permission).

**Decorators:**
- @log_deletions - logs deletion attempts
- @with_help_widget - adds help widget

---

## 4. Usage Patterns

### 4.1 Accessing Organisation Data

**From anywhere in code:**

```python
from organisation.models import OrgInfo

org = OrgInfo.get_solo()
# or
org = OrgInfo.get()

# Access fields
org_name = org.org_name_short_de
chair_person = org.org_chair.person if org.org_chair else None
iban = org.bank_iban
```

**In templates:**

```python
# In view context
context["org"] = OrgInfo.get_solo()

# In template
{{ org.org_name_long_de }}
{{ org.bank_iban }}
```

**In PDF generation:**

```python
from organisation.models import OrgInfo

def generate_pdf(request):
    org = OrgInfo.get_solo()
    context = {
        "org": org,
        "org_address": org.org_address,
        "bank_details": f"{org.bank_name}, IBAN: {org.bank_iban}",
    }
    return render_pdf_response("template.html", context, request, "file.pdf")
```

---

### 4.2 Legal Signatories

**Chair and Deputies:**

```python
org = OrgInfo.get_solo()

# Primary chair
if org.org_chair:
    chair_name = org.org_chair.person.display_name
    chair_role = org.org_chair.role.name

# Deputy chairs (up to 3)
deputies = [
    org.org_dty_chair1,
    org.org_dty_chair2,
    org.org_dty_chair3,
]
deputy_names = [d.person.display_name for d in deputies if d]
```

**Financial Officers:**

```python
org = OrgInfo.get_solo()

# Financial officer
if org.org_wiref:
    wiref_name = org.org_wiref.person.display_name

# Deputy
if org.org_dty_wiref:
    deputy_wiref_name = org.org_dty_wiref.person.display_name
```

**Use Cases:**
- Signature lines on PDFs
- Approval workflow authorization
- Contact information on documents

---

### 4.3 Banking Information

**For Payment Plans:**

```python
org = OrgInfo.get_solo()

default_ref = org.default_reference_label or "Rechnung"
disclaimer = org.payment_plan_disclaimer

# In payment plan form
form_initial = {
    "reference": default_ref,
    "payee_name": person.display_name,
}

# Show disclaimer on submission
if disclaimer:
    messages.info(request, disclaimer)
```

**For PDF Documents:**

```python
org = OrgInfo.get_solo()

banking_text = f"""
Bank: {org.bank_name}
{org.bank_address}
IBAN: {org.bank_iban}
BIC: {org.bank_bic}
"""
```

---

### 4.4 ECTS Affidavits

**Self-Service Portal:**

```python
from organisation.models import OrgInfo

def ects_submit_view(request):
    org = OrgInfo.get_solo()
    
    # Step 1: Course list submission
    affidavit_text_1 = org.ects_affidavit_1
    
    # Step 2: Form upload
    affidavit_text_2 = org.ects_affidavit_2
    
    context = {
        "affidavit": affidavit_text_1,  # or 2, depending on step
    }
    return render(request, "template.html", context)
```

---

## 5. Singleton Behavior

### 5.1 Django-Solo

**Package:** django-solo

**Features:**
- Ensures only one instance exists
- Creates instance automatically if missing
- Provides `get_solo()` class method
- Custom admin interface (no add/delete buttons)

**Database:**
- Table has single row
- ID always 1
- Updates only (never create/delete in normal use)

---

### 5.2 Accessing Singleton

**Standard method:**

```python
OrgInfo.get_solo()
```

**Shorthand (provided by model):**

```python
OrgInfo.get()
```

**No need to check existence:**
- Always returns an instance
- Creates with defaults if missing
- Thread-safe

---

### 5.3 Admin Behavior

**Single instance admin:**
- No "Add" button (instance exists)
- No "Delete" button (singleton cannot be deleted)
- Only "Change" available
- Breadcrumbs show "Master data" instead of object name

---

## 6. Validation

### 6.1 IBAN Validation

**Format:** 2-letter country code + 2 check digits + up to 30 alphanumeric

**Examples:**
- Austria: AT611904300234573201 (20 chars)
- Germany: DE89370400440532013000 (22 chars)

**Validation Steps:**
1. Regex: `^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$`
2. Checksum: mod-97 per ISO 13616
3. Normalization: uppercase, no spaces

**Errors:**
- Regex fails: "Enter a valid IBAN (e.g. AT.., DE..)"
- Checksum fails: "IBAN checksum failed."

---

### 6.2 BIC Validation

**Format:** 4-letter bank code + 2-letter country + 2-char location + optional 3-char branch

**Examples:**
- GIBAATWWXXX (11 chars with branch)
- GIBAATWW (8 chars without branch)

**Validation:**
- Regex: `^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$`
- Normalization: uppercase, no spaces

**Error:**
- "Enter a valid BIC (8 or 11 chars)."

---

## 7. Configuration Requirements

### 7.1 Django Settings

**INSTALLED_APPS:**

```python
INSTALLED_APPS = [
    # ...
    "solo",
    "organisation",
    "people",  # Required for PersonRole
    # ...
]
```

---

### 7.2 Initial Setup

**Create singleton instance:**

```python
from organisation.models import OrgInfo

org = OrgInfo.get_solo()
org.org_name_short_de = "ÖH FH OÖ"
org.org_name_long_de = "Österreichische Hochschüler_innenschaft an der FH Oberösterreich"
org.bank_iban = "AT611904300234573201"
org.save()
```

**Via admin:**
1. Navigate to "Master data" in sidebar
2. Fill in organisation details
3. Select legal signatories from PersonRole autocomplete
4. Save

---

## 8. Dependencies

**Django Framework:**
- ContentType framework
- Django validation (RegexValidator)

**Internal Modules:**
- people (PersonRole for signatories)

**External Packages:**
- django-solo - singleton model pattern
- simple_history - model history tracking

**Core Utilities:**
- core.admin_mixins (HistoryGuardMixin, with_help_widget, log_deletions)

---

## 9. Notes

**Singleton Pattern:**
- Only one OrgInfo instance allowed
- Always accessible via get_solo() or get()
- No manual create/delete via admin

**Bilingual Support:**
- Stores both DE and EN versions
- No automatic translation
- No language-based accessor (use fields directly)
- Frontend decides which language to display

**Legal Signatories:**
- References PersonRole (assignment), not Person
- PROTECT on delete (cannot delete person while signatory)
- Nullable (org can have unfilled positions)
- Related_name="+" prevents reverse relation

**Banking Normalization:**
- IBAN/BIC automatically uppercased
- Spaces removed
- Validation on save (clean())

**Affidavit Flexibility:**
- Plain text fields (no markup)
- Shown in self-service portals
- Can include legal language
- Two separate texts for different workflow stages

**Public Filing URL:**
- External endpoint for public document access
- Warning: "Do not change without permission"
- Used for sharing public documents

**Default Reference:**
- Used in payment plan forms
- Typically "Rechnung" (invoice) or similar
- Overridable per payment plan

**Permission Model:**
- View permission controls sidebar visibility
- Change permission controls edit access
- Users with only view get readonly fields

**No Delete Permission:**
- Singleton cannot be deleted
- Data preserved permanently
- Deactivate fields instead of deleting record

---

## 10. File Structure

```
organisation/
├── __init__.py
├── apps.py                          # Standard config
├── models.py                        # 140 lines
│   ├── _iban_checksum_ok()
│   └── OrgInfo (singleton)
├── admin.py                         # 121 lines
│   ├── OrgInfoForm (custom widgets)
│   └── OrgInfoAdmin (singleton admin)
├── views.py                         # Empty (404)
├── urls.py                          # Empty (404)
└── tests.py                         # Empty placeholder
```

Total lines: ~261 (excluding empty files)

---

**Version:** 1.0.5  
**Last Updated:** 2025-12-08  
**Author:** Sven (vas)