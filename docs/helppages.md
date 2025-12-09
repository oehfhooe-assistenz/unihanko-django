# HELPPAGES.md

**Module:** `helppages`  
**Purpose:** Bilingual (DE/EN) help system for admin pages with Markdown support  
**Version:** 1.0.1 (models), 1.0.0 (admin)  
**Dependencies:** ContentType framework, markdownx

---

## 1. Overview

HelpPages provides contextual help documentation for admin interfaces throughout UniHanko. It offers:

- **Bilingual content** - German and English with automatic language detection
- **Markdown editing** - Rich text formatting with preview
- **Per-model help** - One help page per ContentType (app + model)
- **Legend system** - Quick reference always visible (status badges, icons)
- **Accordion content** - Detailed help text in collapsible section
- **Audit trail** - simple_history tracking

The system integrates with admin pages to display context-sensitive help for users.

---

## 2. Model

### 2.1 HelpPage

**Purpose:** Store bilingual help content for a specific admin page (identified by ContentType).

**Fields:**

**Target:**
- `content_type`: OneToOneField(ContentType, CASCADE) - target app + model (unique)

**Titles (Bilingual):**
- `title_de`: CharField(200) default="Hilfe" - German title
- `title_en`: CharField(200) default="Help" - English title

**Metadata:**
- `author`: CharField(100) blank - help content author
- `help_contact`: CharField(150) blank - contact for questions

**Legends (Bilingual):**
- `legend_de`: MarkdownxField blank default='' - German quick reference
- `legend_en`: MarkdownxField blank default='' - English quick reference

**Content (Bilingual):**
- `content_de`: MarkdownxField default="-" - German detailed help
- `content_en`: MarkdownxField default="-" - English detailed help

**Settings:**
- `is_active`: BooleanField default=True - enable/disable help page
- `show_legend`: BooleanField default=True - show legend section

**Timestamps:**
- `created_at`: DateTimeField auto_now_add
- `updated_at`: DateTimeField auto

**Constraints:**
- OneToOneField on content_type ensures one help page per model

**Ordering:** ['content_type__app_label', 'content_type__model']

**String Representation:**
```
finances.paymentplan: Hilfe zu Funktionsgebühren
```

**History:** simple_history tracked

---

### 2.2 Methods

**get_title():**

```python
def get_title(self)
```

Returns title in current user language with fallback.

**Logic:**
1. Gets current language via get_language()
2. If German (de): returns title_de or title_en or "-"
3. If English: returns title_en or title_de or "-"
4. Exception handler: returns title_de or title_en or "Help"

**get_legend():**

```python
def get_legend(self)
```

Returns legend in current user language with fallback.

**Logic:**
1. Gets current language via get_language()
2. If German (de): returns legend_de or legend_en or ''
3. If English: returns legend_en or legend_de or ''
4. Exception handler: returns legend_de or legend_en or ''

**get_content():**

```python
def get_content(self)
```

Returns content in current user language with fallback.

**Logic:**
1. Gets current language via get_language()
2. If German (de): returns content_de or content_en or '-'
3. If English: returns content_en or content_de or '-'
4. Exception handler: returns content_de or content_en or '-'

**Language Detection:**
- Uses Django's get_language() for user language
- Checks if language starts with 'de' (handles de, de-AT, de-DE, etc.)
- Falls back to German if language detection fails
- Always provides fallback to other language if primary is empty

---

### 2.3 Properties

**app_label:**

```python
@property
def app_label(self)
```

Returns content_type.app_label (e.g., "finances").

**model_name:**

```python
@property
def model_name(self)
```

Returns content_type.model (e.g., "paymentplan").

---

### 2.4 Save Behavior

**Duplicate Prevention:**

On creation (not self.pk):
1. Atomic transaction with select_for_update()
2. Checks if HelpPage already exists for content_type
3. Raises ValidationError if duplicate found
4. Prevents multiple help pages for same model

**After Creation:**
- Normal save operation
- No duplicate check needed (OneToOneField enforces)

---

## 3. Admin Interface

### 3.1 HelpPageAdmin

**Registration:** `@admin.register(HelpPage)`

**Base Classes:**
- SimpleHistoryAdmin - history tracking
- MarkdownxModelAdmin - markdown editor with preview
- HistoryGuardMixin - history protection

**List Display:**
- content_type, get_title (current language), author, is_active, updated_at

**Filters:**
- is_active, content_type__app_label, show_legend

**Search:**
- title_de, title_en, content_de, content_en, author

**Readonly:**
- created_at, updated_at

**Readonly After Creation:**
- content_type (target immutable once created)

**Fieldsets:**

1. **Target:**
   - content_type

2. **Metadata:**
   - author, help_contact, is_active, show_legend

3. **Titles:**
   - (title_de, title_en) - side-by-side

4. **Quick Reference (Always Visible):**
   - legend_de
   - legend_en
   - Description: "Short text explaining status badges, icons, etc."

5. **Full Help Content (Accordion):**
   - content_de
   - content_en
   - Description: "Detailed help text. Use AI to translate between languages!"

6. **System:** (collapsed)
   - created_at, updated_at

**Computed Display:**

```python
def get_title(self, obj)
```
Shows title in current user language (calls obj.get_title()).

**Permissions:**
- No delete (preserves help documentation)

**Decorators:**
- @log_deletions - logs deletion attempts
- @with_help_widget - adds help widget to admin

---

## 4. Usage Patterns

### 4.1 Creating Help Page

**Steps:**
1. Navigate to HelpPages admin
2. Click "Add Help Page"
3. Select target model from content_type dropdown
4. Enter titles in German and English
5. Write legend (always visible quick reference)
6. Write detailed help content
7. Set author and contact (optional)
8. Save

**ContentType Selection:**
- Format: app_label | model
- Example: finances | paymentplan
- OneToOne constraint prevents duplicates

---

### 4.2 Bilingual Content Strategy

**Legend (Quick Reference):**
- Always visible above admin interface
- Explains status badges, color codes, icons
- Keep short (1-3 paragraphs)
- Use bullet points for clarity

**Content (Detailed Help):**
- Collapsible accordion section
- Full documentation of features
- Step-by-step instructions
- Common tasks and workflows
- Troubleshooting tips

**Translation Workflow:**
1. Write in primary language (usually German)
2. Use AI translation for other language
3. Review and adjust technical terms
4. Verify examples and screenshots

---

### 4.3 Markdown Features

**Supported by MarkdownxField:**
- Headers: # H1, ## H2, ### H3
- Bold: **text** or __text__
- Italic: *text* or _text_
- Lists: - item or 1. item
- Links: [text](url)
- Code: `inline` or ```block```
- Images: ![alt](url)
- Tables: | col1 | col2 |

**Preview:**
- Live preview in admin
- Split screen view
- Markdown syntax highlighting

---

### 4.4 Language Fallback

**Scenario 1: User Language = German**
- Shows title_de → title_en → "-"
- Shows legend_de → legend_en → ''
- Shows content_de → content_en → '-'

**Scenario 2: User Language = English**
- Shows title_en → title_de → "-"
- Shows legend_en → legend_de → ''
- Shows content_en → content_de → '-'

**Scenario 3: No German Content**
- German users see English content
- Gradual translation supported

**Scenario 4: No English Content**
- English users see German content
- Single-language deployment supported

---

## 5. Integration Points

### 5.1 Admin Pages

**Display Logic:**
1. Admin template requests help for current model
2. Looks up HelpPage by ContentType
3. Checks is_active flag
4. If show_legend: displays legend above changelist
5. If accordion: displays collapsible full content

**Language Handling:**
- Uses Django's get_language() for current user
- Automatic language switching in UI
- No manual language selection needed

---

### 5.2 ContentType Resolution

**From Model Class:**
```python
from django.contrib.contenttypes.models import ContentType
from finances.models import PaymentPlan

ct = ContentType.objects.get_for_model(PaymentPlan)
help_page = HelpPage.objects.filter(content_type=ct, is_active=True).first()
```

**From App Label + Model Name:**
```python
ct = ContentType.objects.get(app_label='finances', model='paymentplan')
help_page = HelpPage.objects.filter(content_type=ct, is_active=True).first()
```

---

### 5.3 Template Usage

**Getting Help Content:**
```python
# In admin view
help_page = HelpPage.objects.filter(
    content_type__app_label='finances',
    content_type__model='paymentplan',
    is_active=True
).first()

if help_page and help_page.show_legend:
    legend = help_page.get_legend()
    # Display legend above admin interface

if help_page:
    content = help_page.get_content()
    # Display in accordion/modal
```

**Rendering Markdown:**
```python
from markdownx.utils import markdownify

html_legend = markdownify(help_page.get_legend())
html_content = markdownify(help_page.get_content())
```

---

## 6. Configuration

### 6.1 Required Settings

**INSTALLED_APPS:**
```python
INSTALLED_APPS = [
    # ...
    'markdownx',
    'helppages',
    # ...
]
```

**MIDDLEWARE:**
```python
MIDDLEWARE = [
    # ...
    'django.middleware.locale.LocaleMiddleware',  # For language detection
    # ...
]
```

---

### 6.2 MarkdownX Settings (Optional)

**In settings.py:**
```python
MARKDOWNX_MARKDOWN_EXTENSIONS = [
    'markdown.extensions.extra',
    'markdown.extensions.codehilite',
]

MARKDOWNX_MARKDOWN_EXTENSION_CONFIGS = {}

MARKDOWNX_MEDIA_PATH = 'markdownx/'
```

---

## 7. Data Model

**Database Structure:**

```
helppages_helppage
├── id (PK)
├── content_type_id (FK, unique)
├── title_de
├── title_en
├── author
├── help_contact
├── legend_de (text)
├── legend_en (text)
├── content_de (text)
├── content_en (text)
├── is_active
├── show_legend
├── created_at
└── updated_at
```

**Constraints:**
- OneToOne on content_type_id
- No cascading deletes (content_type cannot be deleted if help page exists)

**Indexes:**
- Primary key (id)
- Unique index on content_type_id
- Ordering index on (app_label, model)

---

## 8. File Structure

```
helppages/
├── __init__.py
├── apps.py                          # Standard config
├── models.py                        # 117 lines
│   └── HelpPage (bilingual help)
├── admin.py                         # 65 lines
│   └── HelpPageAdmin (Markdown editor)
├── views.py                         # Empty placeholder
├── urls.py                          # Empty (404)
└── tests.py                         # Empty placeholder
```

Total lines: ~182 (excluding empty files)

---

## 9. Notes

**Singleton Per Model:**
- OneToOneField ensures one help page per ContentType
- Cannot create duplicate help for same model
- Atomic save with select_for_update prevents race conditions

**Immutable Target:**
- content_type cannot be changed after creation
- Prevents reassigning help to wrong model
- Delete and recreate if needed (permission restricted)

**No Delete Permission:**
- Help pages cannot be deleted via admin
- Preserves documentation
- Use is_active=False to hide instead

**Markdown Storage:**
- Raw markdown stored in database
- Rendered to HTML on display
- Preview in admin for editing

**Language Detection:**
- Automatic via Django's LocaleMiddleware
- Respects user browser language
- Session language overrides if set

**Empty Fallbacks:**
- Title: "-" or "Help"
- Legend: '' (empty string)
- Content: '-' (dash)

**Use Cases:**
- Explaining status badges and icons
- Documenting workflow stages
- Field-level help (what to enter)
- Common tasks and procedures
- Troubleshooting guides

**Best Practices:**
- Keep legends short (1-3 paragraphs)
- Use detailed content for full docs
- Include screenshots (via markdown images)
- Link to external resources where appropriate
- Update help when features change

---

**Version:** 1.0.5  
**Last Updated:** 2025-12-08  
**Author:** Sven (vas)