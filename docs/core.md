# Core Application - System Glue & Infrastructure

## 1. Overview

The `core` app provides foundational infrastructure, utilities, and shared functionality for UniHanko. It contains no database models but serves as the "glue" binding the system together through middleware, signal handlers, context processors, management commands, and utility functions.

**Purpose:** System-wide infrastructure, landing page, admin customization, authorization, and developer tools.

**Package Structure:**

```
core/
├── __init__.py
├── apps.py                  # App configuration
├── admin.py                 # FlatPage admin customization
├── admin_mixins.py          # Reusable admin mixins/decorators
├── context_processors.py    # Template context processors
├── middleware.py            # Custom middleware classes
├── pdf.py                   # PDF rendering helper
├── signals.py               # Authentication signal handlers
├── urls.py                  # URL routing
├── views.py                 # Landing page view
├── management/
│   └── commands/
│       ├── bootstrap_unihanko.py    # Master bootstrap orchestrator
│       ├── bootstrap_acls.py        # ACL sync from YAML
│       ├── maintenance.py           # Maintenance mode control
│       ├── validate_templates.py    # Template validation
│       ├── version_python.py        # Python file versioning
│       └── version_template.py      # Template versioning
├── templatetags/
│   ├── help_tags.py         # Help accordion rendering
│   ├── md.py                # Markdown filter
│   └── privacy.py           # IBAN masking filter
└── utils/
    ├── authz.py             # Authorization helpers
    ├── bool_admin_status.py # Boolean status display
    ├── privacy.py           # IBAN masking function
    └── weekday_helper.py    # Weekday counting utility
```

---

## 2. App Configuration (apps.py)

```python
class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Core"
    
    def ready(self):
        """Import signals when Django starts"""
        import core.signals
```

**Behavior:**

- Imports `core.signals` on app startup to connect signal handlers

---

## 3. Signal Handlers (signals.py)

### 3.1 Authentication Logging

**Logger:** `unihanko.auth`

**Signal Handlers:**

```python
def log_user_login(sender, request, user, **kwargs):
    ip = request.META.get('REMOTE_ADDR', 'unknown')
    auth_logger.info(f"User '{user.username}' logged in from {ip}")

def log_user_logout(sender, request, user, **kwargs):
    auth_logger.info(f"User '{user.username}' logged out")

def log_user_login_failed(sender, credentials, request, **kwargs):
    ip = request.META.get('REMOTE_ADDR', 'unknown')
    username = credentials.get('username', 'unknown')
    auth_logger.warning(f"Failed login attempt for '{username}' from {ip}")
```

**Connections:**

```python
user_logged_in.connect(log_user_login)
user_logged_out.connect(log_user_logout)
user_login_failed.connect(log_user_login_failed)
```

**Purpose:**

- Logs successful logins with username and IP
- Logs logouts with username
- Logs failed login attempts with username and IP (WARNING level)

---

## 4. Context Processors (context_processors.py)

### 4.1 Version Info Context Processor

```python
def version_info(request):
    """Make version info available in all templates."""
    return {
        'UNIHANKO_VERSION': settings.UNIHANKO_VERSION,
        'UNIHANKO_CODENAME': settings.UNIHANKO_CODENAME,
        'UNIHANKO_VERSION_FULL': settings.UNIHANKO_VERSION_FULL,
        'ENVIRONMENT': getattr(settings, 'ENVIRONMENT', 'development'),
    }
```

**Purpose:**

- Exposes version constants to all templates
- Provides environment indicator

**Usage in Templates:**

```django
{{ UNIHANKO_VERSION }}  {# 1.0.0 #}
{{ UNIHANKO_CODENAME }} {# Sakura #}
{{ UNIHANKO_VERSION_FULL }} {# v1.0.0 "Sakura" #}
{{ ENVIRONMENT }} {# development/production/staging #}
```

---

## 5. Middleware (middleware.py)

### 5.1 ConstraintErrorMiddleware

**Purpose:** Catch database constraint violations and display user-friendly error pages.

**Catches:**

- UNIQUE constraint violations
- FOREIGN KEY constraint violations
- CHECK constraint violations
- NOT NULL constraint violations

**Implementation:**

```python
class ConstraintErrorMiddleware:
    def process_exception(self, request, exception):
        if not isinstance(exception, IntegrityError):
            return None  # Let Django handle other exceptions
        
        # Log full error for debugging
        admin_logger.error(f"Database constraint violation: {exception}", ...)
        
        # Parse error message for user-friendly display
        error_message = str(exception)
        user_message, error_type = self._parse_constraint_error(error_message)
        
        context = {
            'error_type': error_type,
            'user_message': user_message,
            'technical_details': error_message if request.user.is_superuser else None,
        }
        
        return render(request, 'error_constraint.html', context, status=400)
```

**Error Parsing:**

```python
def _parse_constraint_error(self, error_message):
    # Returns (user_message, error_type)
    
    # UNIQUE constraints
    if 'unique constraint' in error_lower:
        # Extract field name from constraint: uq_<table>_<field>
        return ("A record with this ... already exists.", 'unique')
    
    # FOREIGN KEY constraints
    if 'foreign key constraint' in error_lower:
        if 'delete' in error_lower:
            return ("This record cannot be deleted because other records depend on it.", 'foreign_key')
        return ("The selected related record does not exist.", 'foreign_key')
    
    # CHECK constraints
    if 'check constraint' in error_lower:
        return ("The data you entered violates business rules.", 'check')
    
    # NOT NULL constraints
    if 'not null constraint' in error_lower:
        return ("A required field is missing.", 'not_null')
    
    # Generic fallback
    return ("A database error occurred. Please check your input.", 'generic')
```

**Template:** `templates/error_constraint.html`

**Superuser Bonus:** Technical details shown to superusers only.

---

### 5.2 MaintenanceModeMiddleware

**Purpose:** Enable/disable maintenance mode via file flag.

**Flag File:** `{temp_dir}/maintenance.flag`

**Implementation:**

```python
class MaintenanceModeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.flag_file = os.path.join(tempfile.gettempdir(), 'maintenance.flag')
    
    def __call__(self, request):
        # Check if maintenance mode is enabled
        if os.path.exists(self.flag_file):
            # Allow superusers to still access the site
            if request.user.is_authenticated and request.user.is_superuser:
                return self.get_response(request)
            
            # Show maintenance page to everyone else
            return render(request, 'maintenance.html', status=503)
        
        return self.get_response(request)
```

**Behavior:**

- Non-superusers see maintenance page (503 status)
- Superusers bypass and access site normally
- Controlled via `python manage.py maintenance on|off|status`

**Template:** `templates/maintenance.html`

---

## 6. Views (views.py)

### 6.1 Home/Landing Page View

```python
def home(request):
    ctx = {
        "flat_about":   FlatPage.objects.filter(url="/pages/about/").first(),
        "flat_privacy": FlatPage.objects.filter(url="/pages/privacy/").first(),
        "flat_contact": FlatPage.objects.filter(url="/pages/contact/").first(),
    }
    return render(request, "core/home.html", ctx)
```

**Purpose:** Landing page view that loads FlatPages for about, privacy, and contact.

**Template:** `templates/core/home.html`

**FlatPages Expected:**

- `/pages/about/`
- `/pages/privacy/`
- `/pages/contact/`

---

## 7. URL Routing (urls.py)

```python
urlpatterns = [
    path("", views.home, name="home"),
]
```

**Routes:**

| Path | View | Name |
|------|------|------|
| `/` | `core.views.home` | `home` |

**Note:** Duplicate import statement on line 8 (harmless but redundant).

---

## 8. PDF Rendering (pdf.py)

### 8.1 PDF Response Helper

```python
def render_pdf_response(template, context, request, filename, download=True, print_ref=None):
    """
    Render template to PDF and return HTTP response.
    
    Args:
        template: Template path
        context: Template context dict
        request: HttpRequest object
        filename: PDF filename for download
        download: True for attachment, False for inline display
        print_ref: Optional reference text for PDF header
    
    Returns:
        HttpResponse with PDF content
    """
```

**Implementation:**

```python
# Enrich context
ctx = {
    **(context or {}),
    "request": request,                 # Access {{ request.user.email }}
    "now": timezone.localtime(),        # Access {{ now|date:"Y-m-d H:i" }}
    "print_ref": print_ref,             # Optional header line
}

html = render_to_string(template, ctx, request=request)
pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()

resp = HttpResponse(pdf, content_type="application/pdf")
disp = "attachment" if download else "inline"

# RFC 6266 / 5987: UTF-8 filename support
safe = filename.replace('"', '')
resp["Content-Disposition"] = (
    f'{disp}; filename="{safe}"; filename*=UTF-8\'\'{quote(safe)}'
)
resp["X-Content-Type-Options"] = "nosniff"
resp["Cache-Control"] = "private, max-age=10, must-revalidate"
resp["Expires"] = http_date(time.time() + 180)  # 3 minutes
return resp
```

**Dependencies:**

- `weasyprint` for PDF generation
- Templates must use `base_url` for static files

**Response Headers:**

- `Content-Type: application/pdf`
- `Content-Disposition: attachment/inline` with UTF-8 filename
- `X-Content-Type-Options: nosniff`
- `Cache-Control: private, max-age=10, must-revalidate`
- `Expires: <3 minutes from now>`

---

## 9. Admin Customization

### 9.1 FlatPage Admin with MarkdownX (admin.py)

```python
class FlatPageForm(forms.ModelForm):
    """Custom form to use MarkdownX for content field"""
    content = forms.CharField(widget=AdminMarkdownxWidget)
    
    class Meta:
        model = FlatPage
        fields = '__all__'

class CustomFlatPageAdmin(FlatPageAdmin):
    """FlatPage admin with MarkdownX editor"""
    form = FlatPageForm

# Replace default admin
admin.site.unregister(FlatPage)
admin.site.register(FlatPage, CustomFlatPageAdmin)
```

**Purpose:** Replaces default FlatPage admin with MarkdownX editor for content field.

---

### 9.2 Admin Mixins (admin_mixins.py)

**Constants:**

```python
FEATURE_IMPORT_GROUP = "feature:import"
FEATURE_EXPORT_GROUP = "feature:export"
FEATURE_HISTORY_GROUP = "feature:history"
```

---

#### 9.2.1 ImportExportGuardMixin

**Purpose:** Hide Import/Export buttons unless user is in feature group.

```python
class ImportExportGuardMixin:
    import_feature_group = FEATURE_IMPORT_GROUP
    export_feature_group = FEATURE_EXPORT_GROUP
    
    def has_import_permission(self, request, *args, **kwargs):
        parent = super().has_import_permission(request, *args, **kwargs)
        if not parent:
            return False
        if request.user.is_superuser:
            return True
        return self._user_in_group(request, self.import_feature_group)
    
    def has_export_permission(self, request, *args, **kwargs):
        # Similar logic for export
```

**Usage:**

```python
class MyAdmin(ImportExportGuardMixin, ImportExportModelAdmin):
    pass
```

**Behavior:**

- Superusers always allowed
- Non-superusers must be in `feature:import` / `feature:export` groups
- Can override group names with class attributes

---

#### 9.2.2 HistoryGuardMixin

**Purpose:** Hide history button unless user is in feature:history group.

```python
class HistoryGuardMixin:
    history_feature_group = FEATURE_HISTORY_GROUP
    
    def has_view_history_permission(self, request, obj=None):
        parent = super().has_view_history_permission(request, obj)
        if not parent:
            return False
        if request.user.is_superuser:
            return True
        return self._user_in_group(request, self.history_feature_group)
```

**Usage:**

```python
class MyAdmin(HistoryGuardMixin, admin.ModelAdmin):
    pass
```

---

#### 9.2.3 safe_admin_action Decorator

**Purpose:** Add consistent error handling to admin object actions.

```python
@safe_admin_action
def my_action(self, request, obj):
    # Action code
    # Exceptions caught automatically
    # Auto-redirects to change page if returns None
```

**Features:**

```python
def safe_admin_action(func):
    @wraps(func)
    def wrapper(self, request, obj):
        try:
            result = func(self, request, obj)
            # Auto-redirect if action doesn't return response
            if result is None:
                change_url = reverse(f'admin:{app_label}_{model_name}_change', args=[obj.pk])
                return HttpResponseRedirect(change_url)
            return result
        except PermissionDenied as e:
            self.message_user(request, str(e), level=messages.ERROR)
            # Redirect back
        except Exception as e:
            self.message_user(request, f"An error occurred: {e}", level=messages.ERROR)
            admin_logger.exception(f"Error in {self.__class__.__name__}.{func.__name__}: {e}")
            # Redirect back
```

**Catches:**

- `PermissionDenied` - Shows error message
- All other exceptions - Shows error message + logs to `unihanko.admin`

---

#### 9.2.4 with_help_widget Decorator

**Purpose:** Add help widget context to admin views.

```python
@with_help_widget
class MyAdmin(admin.ModelAdmin):
    pass
```

**Behavior:**

- Wraps `changelist_view` and `changeform_view`
- Sets `extra_context['show_help_widget'] = True`
- Enables help accordion rendering via `render_admin_help` template tag

---

#### 9.2.5 log_deletions Decorator

**Purpose:** Add deletion logging to any ModelAdmin.

```python
@log_deletions
class MyAdmin(admin.ModelAdmin):
    pass
```

**Behavior:**

```python
# Single deletion
admin_logger.warning(
    f"User '{request.user.username}' deleted {obj._meta.verbose_name} "
    f"#{obj.pk}: {str(obj)[:100]}"
)

# Bulk deletion
admin_logger.warning(
    f"User '{request.user.username}' bulk deleted {count} {model_name_plural}"
)
```

**Logger:** `unihanko.admin`

---

## 10. Utilities

### 10.1 Authorization (utils/authz.py)

**ACL Configuration:**

```python
ACL_PATH = settings.ACL_CONFIG_PATH or BASE_DIR / "config" / "access.yaml"
```

**Core Functions:**

```python
def is_in_group(user, group_name: str) -> bool:
    """
    True iff user is in Django group AND group is declared in access.yaml.
    Fail-closed if ACL missing.
    """
    if not (user and user.is_authenticated):
        return False
    if not _group_in_acl(group_name):
        return False
    return user.groups.filter(name=group_name).exists()

def is_module_manager(user, module_code: str) -> bool:
    """Check if user is manager of specific module."""
    return is_in_group(user, f"module:{module_code}:manager")
```

**Module Manager Shortcuts:**

```python
def is_people_manager(user) -> bool:
    return is_module_manager(user, "personnel")

def is_finances_manager(user) -> bool:
    return is_module_manager(user, "finances")

def is_employees_manager(user) -> bool:
    return is_module_manager(user, "employees")

def is_assembly_manager(user) -> bool:
    return is_module_manager(user, "assembly")

def is_academia_manager(user) -> bool:
    return is_module_manager(user, "academia")

def is_academia_audit_manager(user) -> bool:
    return is_module_manager(user, "academia_audit")
```

**Cache Management:**

```python
def refresh_acl_cache() -> None:
    """Call after changing access.yaml at runtime."""
    _load_acl.cache_clear()
```

**ACL Loading:**

```python
@lru_cache(maxsize=1)
def _load_acl() -> Dict[str, Set[str]]:
    """Parse YAML once. On error, return empty sets (fail-closed)."""
    try:
        with open(ACL_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        groups = set((data.get("groups") or {}).keys())
        return {"groups": groups}
    except Exception:
        return {"groups": set()}
```

**Security Model:**

- Requires BOTH Django group membership AND ACL declaration
- Fail-closed: missing/invalid ACL = no access
- Cached for performance (LRU cache)

---

### 10.2 Boolean Admin Status (utils/bool_admin_status.py)

```python
def boolean_status_span(value: bool, *, true_label: str, false_label: str,
                        true_code: str = "ok", false_code: str = "off"):
    """
    Return <span class="js-state" data-state="...">Label</span>.
    The code is machine-readable; CSS/JS can decorate rows globally.
    """
    label = true_label if value else false_label
    code  = true_code if value else false_code
    return format_html('<span class="js-state" data-state="{}">{}</span>', code, label)

def row_state_attr_for_boolean(value: bool, *, true_code: str = "ok", false_code: str = "off"):
    """Return dict for row-level data attributes."""
    return {"data-state": (true_code if value else false_code)}
```

**Purpose:** Generate consistent HTML/data attributes for boolean status displays in admin.

---

### 10.3 Privacy (utils/privacy.py)

```python
def mask_iban(iban: str | None, head: int = 6, tail: int = 4, fill: str = "*") -> str:
    """
    Show first `head` and last `tail` characters; mask middle.
    Returned string grouped in blocks of 4 for readability.
    
    Example:
        AT6260000000001234567 -> AT6260 **** **** **4567
    """
    s = re.sub(r"\s+", "", (iban or ""))
    if not s:
        return ""
    n_mask = max(0, len(s) - head - tail)
    masked = s if n_mask <= 0 else s[:head] + (fill * n_mask) + (s[-tail:] if tail else "")
    return " ".join(textwrap.wrap(masked, 4))
```

**Usage:**

```python
mask_iban("AT6260000000001234567")  # "AT6260 **** **** **4567"
mask_iban("AT6260000000001234567", head=8, tail=2)  # "AT626000 **** ****67"
```

---

### 10.4 Weekday Helper (utils/weekday_helper.py)

```python
WEEKDAYS_MON_FRI: Set[int] = {0, 1, 2, 3, 4}  # Monday=0 ... Friday=4

def weekdays_between(
    start: Optional[date],
    end: Optional[date],
    *,
    inclusive: bool = False,
    weekday_mask: Iterable[int] = WEEKDAYS_MON_FRI,
    clamp_negative: bool = True,
) -> Optional[int]:
    """
    Count days whose weekday() is in `weekday_mask` between two dates.
    
    Range semantics:
        - inclusive=False (default): [start, end)  → end NOT included
        - inclusive=True:            [start, end]  → end included
    
    Examples:
        weekdays_between(date(2025,10,20), date(2025,10,24))  # 4 (Mon-Thu)
        weekdays_between(date(2025,10,20), date(2025,10,24), inclusive=True)  # 5 (Mon-Fri)
        weekdays_between(date(2025,10,25), date(2025,10,27))  # 1 (only Mon counted)
    """
```

**Algorithm:**

1. Handle None dates (return None)
2. Adjust for inclusive/exclusive
3. Validate start <= end (or clamp to 0)
4. Calculate full weeks * mask length
5. Count extra days in remainder window

**Use Case:** Calculate working days for employee timesheets.

---

## 11. Template Tags

### 11.1 Help Tags (templatetags/help_tags.py)

```python
@register.simple_tag(takes_context=True)
def render_admin_help(context):
    """Render help accordion + legend for current admin page."""
    request = context.get('request')
    
    # Extract app_label and model_name from path
    path_parts = request.path.strip('/').split('/')
    if len(path_parts) < 3 or path_parts[0] != 'admin':
        return ''
    
    app_label = path_parts[1]
    model_name = path_parts[2]
    
    # Get ContentType
    ct = ContentType.objects.get(app_label=app_label, model=model_name)
    
    # Get active HelpPage
    help_page = HelpPage.objects.get(content_type=ct, is_active=True)
    
    # Get language-specific content
    title = help_page.get_title()
    legend_text = help_page.get_legend()
    content_text = help_page.get_content()
    
    # Render markdown to HTML
    md = markdown.Markdown(extensions=[
        'markdown.extensions.extra',
        'markdown.extensions.nl2br',
        'markdown.extensions.sane_lists',
    ])
    legend_html = md.convert(legend_text)
    md.reset()
    content_html = md.convert(content_text)
    
    return mark_safe(render_to_string("helppages/help_widget.html", {...}))
```

**Usage in Templates:**

```django
{% load help_tags %}
{% render_admin_help %}
```

**Requirements:**

- `helppages` app installed
- HelpPage exists for model with `is_active=True`
- Used in admin changelist/changeform views

---

### 11.2 Markdown Filter (templatetags/md.py)

```python
@register.filter
def markdown(text):
    """Convert markdown to HTML."""
    if not text:
        return ""
    return mark_safe(md.markdown(text, extensions=["extra","sane_lists","smarty"]))
```

**Usage:**

```django
{% load md %}
{{ flatpage.content|markdown }}
```

**Extensions:**

- `extra` - Tables, fenced code blocks, etc.
- `sane_lists` - Better list parsing
- `smarty` - Smart quotes/dashes

---

### 11.3 Privacy Filter (templatetags/privacy.py)

```python
@register.filter(name="mask_iban")
def mask_iban_filter(value, args="6,4"):
    """
    Usage: {{ pp.iban|mask_iban }} or {{ pp.iban|mask_iban:"8,4" }}
    """
    try:
        head, tail = (int(x) for x in (args.split(",") + ["6", "4"])[:2])
    except Exception:
        head, tail = 6, 4
    return _mask_iban(value, head=head, tail=tail)
```

**Usage:**

```django
{% load privacy %}
{{ payment_plan.iban|mask_iban }}          {# Default 6,4 #}
{{ payment_plan.iban|mask_iban:"8,2" }}    {# Custom 8,2 #}
```

---

## 12. Management Commands

### 12.1 bootstrap_unihanko.py

**Purpose:** Master orchestrator for UniHanko system bootstrap.

**Execution Order:**

```python
commands = [
    ("bootstrap_orginfo", "Organization Master Data"),
    ("bootstrap_acls", "ACL Permissions"),
    ("bootstrap_actions", "HankoSign Actions"),
    ("bootstrap_roles", "Organizational Roles"),
    ("bootstrap_reasons", "Role Transition Reasons"),
    ("bootstrap_holidays", "Holiday Calendar"),
    ("bootstrap_fiscalyears", "Fiscal Years"),
    ("bootstrap_semesters", "Academic Semesters"),
    ("bootstrap_terms", "Assembly Terms"),
    ("bootstrap_helppages", "Help Pages"),
    ("bootstrap_people", "People"),
    ("bootstrap_assignments", "Assignments (PersonRole)"),
]
```

**Usage:**

```bash
python manage.py bootstrap_unihanko --dry-run  # Preview
python manage.py bootstrap_unihanko            # Apply
```

**Features:**

- Executes all bootstrap commands in dependency order
- Captures output from each command
- Passes `--dry-run` flag to sub-commands
- Shows summary with ✓/✗ status
- Returns exit code 1 if any failures

---

### 12.2 bootstrap_acls.py

**Purpose:** Sync Django Groups & Permissions from YAML file (idempotent).

**YAML Format:**

```yaml
groups:
  group-name:
    inherits:
      - parent-group
    models:
      app.Model:
        - view
        - add
        - change
        - delete
    custom_perms:
      app.Model:
        - custom_permission_codename
```

**Usage:**

```bash
python manage.py bootstrap_acls --dry-run
python manage.py bootstrap_acls
python manage.py bootstrap_acls --file /custom/access.yaml
```

**Features:**

```python
def get_fixture_path(filename, *, sensitive=False):
    """Resolve fixture location."""
    if sensitive and not settings.DEBUG:
        # Production: mount only
        return settings.BOOTSTRAP_DATA_DIR / filename
    else:
        # Dev or non-sensitive: repo fixtures
        return Path(__file__).parent.parent.parent / "fixtures" / filename
```

**Permission Resolution:**

- Supports group inheritance (circular detection)
- Maps model labels to permissions: `app.Model` → `view_model`, `add_model`, etc.
- Validates custom permissions exist
- Exact sync: adds missing, removes extra

**Validation:**

- Checks migrations ran (permissions exist)
- Validates model labels
- Detects circular inheritance
- Fails if required file missing in production

---

### 12.3 maintenance.py

**Purpose:** Enable, disable, or check maintenance mode.

**Usage:**

```bash
python manage.py maintenance on      # Enable
python manage.py maintenance off     # Disable
python manage.py maintenance status  # Check
```

**Flag File:** `{temp_dir}/maintenance.flag`

**Implementation:**

```python
class Command(BaseCommand):
    FLAG_FILE = os.path.join(tempfile.gettempdir(), 'maintenance.flag')
    
    def enable_maintenance(self):
        open(self.FLAG_FILE, 'a').close()
        # "✓ Maintenance mode ENABLED"
    
    def disable_maintenance(self):
        if os.path.exists(self.FLAG_FILE):
            os.remove(self.FLAG_FILE)
            # "✓ Maintenance mode DISABLED"
    
    def check_status(self):
        if os.path.exists(self.FLAG_FILE):
            # Shows enabled timestamp
        else:
            # "✓ Maintenance mode is DISABLED"
```

---

### 12.4 validate_templates.py

**Purpose:** Validate Django templates for common issues.

**Usage:**

```bash
python manage.py validate_templates
python manage.py validate_templates --portal-only
python manage.py validate_templates --extract-text
python manage.py validate_templates --output-report validation_report.md
```

**Checks:**

**HIGH Priority:**

- Missing `{% load i18n %}` when using `{% trans %}`
- Missing `{% load static %}` when using `{% static %}`

**MEDIUM Priority:**

- Hardcoded URLs (should use `{% url %}`)
- Hardcoded static paths (should use `{% static %}`)

**LOW Priority:**

- Untranslated strings (text not wrapped in `{% trans %}`)

**Features:**

```python
# VALIDATOR_IGNORE marker
{# VALIDATOR_IGNORE: reason_here #}

# Text extraction for content review
--extract-text  # Extracts trans, help_text, placeholder, button text

# Full markdown report
--output-report validation_report.md
```

**Statistics Tracked:**

- Total files scanned
- Ignored files (VALIDATOR_IGNORE)
- Missing i18n load
- Missing static load
- Hardcoded URLs
- Hardcoded static paths
- Possibly untranslated strings

---

### 12.5 version_python.py

**Purpose:** Add/update version headers in Python files.

**Usage:**

```bash
# Add version header
python manage.py version_python core/models.py --author vas

# Dry run
python manage.py version_python core/models.py --dry-run

# Update existing (auto-increments version)
python manage.py version_python core/models.py

# Batch update directory
python manage.py version_python core/ --author vas

# Set custom version
python manage.py version_python core/models.py --set-version 2.5.0
```

**Header Format:**

```python
# File: core/models.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-12-08
```

**Features:**

- Auto-increments patch version (1.0.0 → 1.0.1)
- Searches only first 20 lines (safety)
- Automatically skips all migration files
- Preserves existing author if not changed
- Detects existing file path comments
- Inserts after shebang/encoding/docstring

**Safety:**

```python
# Only searches/modifies first 20 lines
lines = content.split('\n')
top_section = '\n'.join(lines[:20])

# Auto-excludes migrations
py_files = [f for f in py_files if '/migrations/' not in str(f)]
```

---

### 12.6 version_template.py

**Purpose:** Add/update version headers in HTML templates.

**Usage:**

```bash
# Add version header
python manage.py version_template templates/portal/home.html --author vas

# Dry run
python manage.py version_template templates/portal/home.html --dry-run

# Update existing
python manage.py version_template templates/portal/home.html

# Batch update directory
python manage.py version_template templates/portal/ --author vas

# Set custom version
python manage.py version_template templates/portal/home.html --set-version 2.5.0
```

**Header Format:**

```html
<!--
Template: home.html
Version: 1.0.0
Author: vas
Modified: 2025-12-08
-->
```

**Features:**

- Auto-increments patch version
- Preserves existing author if not changed
- Inserts after Django template tags/extends
- Works with files anywhere in templates directory

---

## 13. Critical Notes

### 13.1 Middleware Order

Both custom middleware must be in correct position in `settings.MIDDLEWARE`:

- `ConstraintErrorMiddleware` - Late in stack (catches exceptions)
- `MaintenanceModeMiddleware` - Late in stack (intercepts requests)

---

### 13.2 Authorization Model

**Fail-Closed Design:**

- Missing `access.yaml` → all checks return False
- Invalid YAML → all checks return False
- Group not in ACL → check returns False even if Django group exists

**Purpose:** Prevent accidental privilege escalation.

---

### 13.3 PDF Rendering

**Requirements:**

- WeasyPrint installed
- Templates use `base_url` for static files
- Static files must be accessible at build time

**Performance:**

- No server-side caching
- Client-side cache: 10 seconds max-age
- Expires header: 3 minutes

---

### 13.4 Template Validation

**VALIDATOR_IGNORE Usage:**

```django
{# VALIDATOR_IGNORE: This is a base template with no translatable content #}
```

Validator skips file and notes it in report.

---

### 13.5 Version Management

**Best Practices:**

- Run `version_python` before commits
- Use `--dry-run` to preview changes
- Set initial version with `--set-version 1.0.0`
- Auto-increment handles patch versions only

**Version Format:** Semantic versioning `MAJOR.MINOR.PATCH`

---

## 14. Integration Summary

**core** provides infrastructure for:

- **Authentication logging** - Signal handlers to `unihanko.auth` logger
- **Error handling** - Constraint errors → user-friendly messages
- **Maintenance mode** - File-based flag system
- **PDF generation** - Shared helper for all modules
- **Authorization** - YAML-based ACL with fail-closed security
- **Admin utilities** - Mixins, decorators, Boolean displays
- **Template filters** - Markdown, IBAN masking, help rendering
- **Bootstrap system** - Master orchestrator + ACL sync
- **Development tools** - Template validation, versioning
- **Landing page** - Home view with FlatPages

All other modules depend on core for these shared services.

---

**Version:** 1.0.0  
**Last Updated:** 2025-12-08  
**Author:** Sven (vas)