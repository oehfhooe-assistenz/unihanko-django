# Django Project Configuration

## 1. Overview

The `config` package contains Django project configuration files, including settings, URL routing, WSGI/ASGI application entry points, Jazzmin admin theme customization, and bootstrap fixture data in YAML format.

**Package Structure:**

```
config/
├── __init__.py
├── settings.py              # Main Django settings
├── settings_jazzmin.py      # Jazzmin admin theme config
├── urls.py                  # URL routing
├── wsgi.py                  # WSGI application
├── asgi.py                  # ASGI application
└── fixtures/                # Bootstrap data (YAML)
    ├── access.yaml          # 241 lines
    ├── assignments.yaml     # 29 lines
    ├── fiscal_years.yaml    # 14 lines
    ├── hankosign_actions.yaml   # 476 lines
    ├── holiday_calendar.yaml    # 23 lines
    ├── orginfo.yaml         # 19 lines
    ├── people.yaml          # 15 lines
    ├── roles.yaml           # 706 lines
    ├── semesters.yaml       # 33 lines
    ├── terms.yaml           # 13 lines
    └── transition_reasons.yaml  # 127 lines
```

---

## 2. Main Settings (settings.py)

### 2.1 Project Metadata

```python
UNIHANKO_VERSION = "1.0.0"
UNIHANKO_CODENAME = "Sakura"
UNIHANKO_VERSION_FULL = f"v{UNIHANKO_VERSION} \"{UNIHANKO_CODENAME}\""
```

**Usage:** Available in templates via `core.context_processors.version_info`.

---

### 2.2 Environment Configuration

Uses `django-environ` to read from `.env` file:

```python
env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / '.env')
```

**Core Environment Variables:**

```python
DEBUG = env.bool('DEBUG', default=False)
ENVIRONMENT = env('ENVIRONMENT', default='development')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[])
```

---

### 2.3 Secret Key Handling

**Production (DEBUG=False):**

```python
if not DEBUG:
    SECRET_KEY = env('SECRET_KEY')  # No default - raises error if missing
    HANKOSIGN_SECRET = env('HANKOSIGN_SECRET')
```

Fails loudly if secrets not set.

**Development (DEBUG=True):**

```python
else:
    SECRET_KEY = env('SECRET_KEY', default='django-insecure-rz9r+bbkq_y+p&y&$m98m()h+b2g4n4eedn4c*h51zzzntna*h')
    HANKOSIGN_SECRET = env('HANKOSIGN_SECRET', default='django-insecure-GENERATE_ANOTHER_ONE_HERE')
```

Allows insecure defaults for convenience.

---

### 2.4 Directory Paths

**Logs Directory:**

```python
if DEBUG:
    LOGS_DIR = BASE_DIR / 'logs'
else:
    LOGS_DIR = Path('/var/log/unihanko')  # Docker mount

LOGS_DIR.mkdir(parents=True, exist_ok=True)
```

**Bootstrap Data Directory:**

```python
if DEBUG:
    BOOTSTRAP_DATA_DIR = BASE_DIR / 'config' / 'fixtures'
else:
    BOOTSTRAP_DATA_DIR = Path('/mnt/bootstrap-data')
    BOOTSTRAP_DATA_DIR.mkdir(parents=True, exist_ok=True)
```

Comment notes production uses Docker mount "never in repo" for sensitive data.

---

### 2.5 Logging Configuration

**Formatters:**

```python
'formatters': {
    'verbose': {
        'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
        'style': '{',
    },
    'simple': {
        'format': '{levelname} {asctime} {module} {message}',
        'style': '{',
    },
}
```

**Handlers:**

| Handler | File | Max Size | Backups | Level | Formatter |
|---------|------|----------|---------|-------|-----------|
| `console` | (stdout) | n/a | n/a | INFO | simple |
| `file_django` | django.log | 10 MB | 5 | INFO | verbose |
| `file_auth` | auth.log | 5 MB | 5 | INFO | verbose |
| `file_hankosign` | hankosign.log | 10 MB | 5 | INFO | verbose |
| `file_payments` | payments.log | 5 MB | 5 | INFO | verbose |
| `file_admin` | admin.log | 10 MB | 5 | INFO | verbose |
| `file_errors` | errors.log | 10 MB | 10 | ERROR | verbose |

All file handlers use `logging.handlers.RotatingFileHandler`.

**Loggers:**

```python
'loggers': {
    'django': {
        'handlers': ['console', 'file_django'],
        'level': 'INFO',
        'propagate': False,
    },
    'django.request': {
        'handlers': ['console', 'file_errors'],
        'level': 'ERROR',
        'propagate': False,
    },
    'django.db.backends': {
        'handlers': ['console'] if DEBUG else [],
        'level': 'DEBUG' if DEBUG else 'INFO',
        'propagate': False,
    },
    'unihanko.auth': {
        'handlers': ['console', 'file_auth'],
        'level': 'INFO',
        'propagate': False,
    },
    'unihanko.hankosign': {
        'handlers': ['console', 'file_hankosign'],
        'level': 'INFO',
        'propagate': False,
    },
    'unihanko.payments': {
        'handlers': ['console', 'file_payments'],
        'level': 'INFO',
        'propagate': False,
    },
    'unihanko.admin': {
        'handlers': ['console', 'file_admin'],
        'level': 'INFO',
        'propagate': False,
    },
}
```

Note: `django.db.backends` only logs to console in DEBUG mode.

---

### 2.6 Installed Apps

```python
INSTALLED_APPS = [
    'jazzmin',
    'concurrency',
    'solo',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'django.contrib.flatpages',
    'markdownx',
    'tinymce',
    'helppages',
    'import_export',
    'simple_history',
    'django_object_actions',
    'django_renderpdf',
    'adminsortable2',
    'captcha',
    'django_admin_inline_paginator_plus',
    'axes',
    
    'core',
    'annotations',
    'hankosign',
    'people',
    'finances',
    'employees',
    'assembly',
    'academia',
    'academia_audit',
    'portal',
    
    'organisation',
]
```

**Third-Party Apps:**

- `jazzmin` - Admin interface theme
- `concurrency` - Optimistic locking
- `solo` - Singleton models
- `markdownx` - Markdown editor
- `tinymce` - Rich text editor
- `helppages` - Help system
- `import_export` - CSV/Excel import/export
- `simple_history` - Model history tracking
- `django_object_actions` - Admin action buttons
- `django_renderpdf` - PDF rendering
- `adminsortable2` - Drag-and-drop ordering
- `captcha` - CAPTCHA generation
- `django_admin_inline_paginator_plus` - Paginated inlines
- `axes` - Brute-force login protection

---

### 2.7 Middleware Stack

```python
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.flatpages.middleware.FlatpageFallbackMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'axes.middleware.AxesMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'simple_history.middleware.HistoryRequestMiddleware',
    'core.middleware.ConstraintErrorMiddleware',
    'core.middleware.MaintenanceModeMiddleware',
]
```

**Custom Middleware:**

- `core.middleware.ConstraintErrorMiddleware` - Database constraint error handling
- `core.middleware.MaintenanceModeMiddleware` - Maintenance mode display

---

### 2.8 Authentication

**Backends:**

```python
AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]
```

**Axes Configuration:**

```python
AXES_FAILURE_LIMIT = 5  # Lock after 5 failed attempts
AXES_COOLOFF_TIME = 1  # 1 hour lockout
AXES_LOCKOUT_PARAMETERS = [
    'username',
    'ip_address',
]
```

**Password Validators:**

```python
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]
```

**Login Configuration:**

```python
LOGIN_URL = "/admin/login/"
LOGIN_REDIRECT_URL = "/admin/"
```

---

### 2.9 Templates

```python
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / "templates"],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.template.context_processors.i18n',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.version_info',
            ],
        },
    },
]
```

**Custom Context Processor:**

- `core.context_processors.version_info` - Provides version constants

---

### 2.10 Security Settings

**Production-Only (DEBUG=False):**

```python
# Proxy configuration - CRITICAL
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Cookie Security - CRITICAL
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_AGE = 31449600  # 1 year

# Content Security
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True

# HSTS
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Session Security
SESSION_COOKIE_AGE = 86400  # 24 hours
SESSION_SAVE_EVERY_REQUEST = True

# Admin session timeout
ADMIN_SESSION_COOKIE_AGE = 14400  # 4 hours

# CSRF trusted origins - CRITICAL
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])
if not CSRF_TRUSTED_ORIGINS:
    raise ValueError(
        "CSRF_TRUSTED_ORIGINS must be set in production .env file. "
        "Example: CSRF_TRUSTED_ORIGINS=https://unihanko.example.com"
    )
```

**Development (DEBUG=True):**

```python
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_AGE = 1209600  # 2 weeks
```

**Critical Comment in Code:**

```python
# DO NOT SET SECURE_SSL_REDIRECT = True
# Caddy already handles HTTP→HTTPS redirect, and Django only sees HTTP internally
# Setting this would cause infinite redirects!
```

Deployment is behind Caddy reverse proxy.

---

### 2.11 Database Configuration

```python
DATABASES = {
    'default': {
        'ENGINE': env('DB_ENGINE', default='django.db.backends.sqlite3'),
        'NAME': env('DB_NAME', default=str(BASE_DIR / 'db.sqlite3')),
        'USER': env('DB_USER', default=''),
        'PASSWORD': env('DB_PASSWORD', default=''),
        'HOST': env('DB_HOST', default=''),
        'PORT': env('DB_PORT', default=''),
        'CONN_MAX_AGE': env.int('DB_CONN_MAX_AGE', default=600) if not DEBUG else 0,
        'OPTIONS': {
            'connect_timeout': 10,
        } if not DEBUG else {},
    }
}
```

**Connection Pooling:**

- Production: `CONN_MAX_AGE = 600` (10 minute pool)
- Development: `CONN_MAX_AGE = 0` (no pooling)

**Connect Timeout:**

- Production: 10 seconds
- Development: None (default)

---

### 2.12 Internationalization

```python
LANGUAGE_CODE = 'en-gb'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

LANGUAGES = [
    ("en-gb", "English"),
    ("de-at", "Deutsch"),
]

LOCALE_PATHS = [BASE_DIR / "locale"]
```

**Frame Options:**

```python
X_FRAME_OPTIONS = "SAMEORIGIN"
```

---

### 2.13 Static Files

```python
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / 'staticfiles'
```

---

### 2.14 Media Files

**Development:**

```python
if DEBUG:
    MEDIA_URL = '/media/'
    MEDIA_ROOT = BASE_DIR / 'media'
```

**Production (MinIO/S3):**

```python
else:
    STORAGES = {
        'default': {
            'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    }
    
    AWS_ACCESS_KEY_ID = env('MINIO_ACCESS_KEY')
    AWS_SECRET_ACCESS_KEY = env('MINIO_SECRET_KEY')
    AWS_STORAGE_BUCKET_NAME = env('MINIO_BUCKET_NAME')
    AWS_S3_ENDPOINT_URL = env('MINIO_ENDPOINT_URL')
    AWS_S3_REGION_NAME = 'us-east-1'  # MinIO default, always this
    AWS_S3_SIGNATURE_VERSION = 's3v4'
    AWS_S3_FILE_OVERWRITE = False
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = True
    AWS_QUERYSTRING_EXPIRE = 3600  # 1 hour signed URLs
```

---

### 2.15 Third-Party Library Configuration

**Markdownx:**

```python
MARKDOWNX_MARKDOWN_EXTENSIONS = [
    'markdown.extensions.extra',
    'markdown.extensions.nl2br',
    'markdown.extensions.sane_lists',
]
MARKDOWNX_MARKDOWN_EXTENSION_CONFIGS = {}
MARKDOWNX_MEDIA_PATH = 'markdownx/'
```

**TinyMCE:**

```python
TINYMCE_DEFAULT_CONFIG = {
    'height': 360,
    'width': '100%',
    'menubar': False,
    'plugins': 'lists link',
    'toolbar': 'undo redo | bold italic underline | bullist numlist | removeformat',
    'statusbar': False,
    'branding': False,
    'content_style': 'body { font-family: Arial, sans-serif; font-size: 14px; }',
    'license_key': 'gpl',
}
```

**CAPTCHA:**

```python
CAPTCHA_IMAGE_SIZE = (120, 50)
CAPTCHA_FONT_SIZE = 32
CAPTCHA_LETTER_ROTATION = (-20, 20)
CAPTCHA_BACKGROUND_COLOR = '#0a0a0a'
CAPTCHA_FOREGROUND_COLOR = '#FF6B35'
CAPTCHA_NOISE_FUNCTIONS = ('captcha.helpers.noise_dots',)
CAPTCHA_LENGTH = 4
CAPTCHA_TIMEOUT = 5  # Minutes
```

---

### 2.16 Other Settings

```python
SITE_ID = 1
ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
```

**Jazzmin Import:**

```python
from .settings_jazzmin import JAZZMIN_SETTINGS, JAZZMIN_UI_TWEAKS
```

---

## 3. Jazzmin Admin Theme (settings_jazzmin.py)

### 3.1 Branding

```python
JAZZMIN_SETTINGS = {
    "site_title": "UniHanko Back Office",
    "site_header": "UniHanko Back Office",
    "site_brand": "UniHanko",
    "welcome_sign": f'Welcome to UniHanko Back Office v{UNIHANKO_VERSION} "{UNIHANKO_CODENAME}"',
    "copyright": f'Sven Várszegi & ÖH FH OÖ • UniHanko {UNIHANKO_VERSION} ',
    "site_logo": "img/unihanko-logo.svg",
    "login_logo": "img/unihanko-mark.svg",
    "site_logo_classes": "img-fluid",
    # ...
}
```

---

### 3.2 Navigation

**Top Menu:**

```python
"topmenu_links": [
    # Empty - can add links later
],
```

**User Menu:**

```python
"usermenu_links": [
    {"model": "auth.user"},
],
```

**Search:**

```python
"search_model": ["people.PersonRole", "people.Person",],
```

---

### 3.3 Icons

Font Awesome 6 Solid icons for apps and models:

```python
"icons": {
    # Academia
    "academia": "fa-solid fa-graduation-cap",
    "academia.semester": "fa-solid fa-calendar-days",
    "academia.inboxrequest": "fa-solid fa-inbox",
    "academia.inboxcourse": "fa-solid fa-book-bookmark",
    
    # Academia Audit
    "academia_audit": "fa-solid fa-magnifying-glass-chart",
    "academia_audit.auditsemester": "fa-solid fa-table-list",
    "academia_audit.auditentry": "fa-solid fa-list-check",
    
    # Annotations
    "annotations": "fa-solid fa-comments",
    "annotations.annotation": "fa-solid fa-comment-dots",
    
    # Assembly
    "assembly": "fa-solid fa-landmark-dome",
    "assembly.term": "fa-solid fa-timeline",
    "assembly.composition": "fa-solid fa-diagram-project",
    "assembly.mandate": "fa-solid fa-certificate",
    "assembly.session": "fa-solid fa-gavel",
    "assembly.sessionattendance": "fa-solid fa-clipboard-user",
    "assembly.sessionitem": "fa-solid fa-list-ol",
    "assembly.vote": "fa-solid fa-square-poll-vertical",
    
    # Employees
    "employees": "fa-solid fa-address-book",
    "employees.holidaycalendar": "fa-solid fa-umbrella-beach",
    "employees.employee": "fa-solid fa-id-card",
    "employees.employeeleaveyear": "fa-solid fa-plane-departure",
    "employees.employmentdocument": "fa-solid fa-file-contract",
    "employees.timesheet": "fa-solid fa-clock",
    "employees.timeentry": "fa-solid fa-stopwatch",
    
    # Finances
    "finances": "fa-solid fa-coins",
    "finances.fiscalyear": "fa-solid fa-calendar-check",
    "finances.paymentplan": "fa-solid fa-money-check-dollar",
    
    # HankoSign
    "hankosign": "fa-solid fa-stamp",
    "hankosign.action": "fa-solid fa-bolt",
    "hankosign.policy": "fa-solid fa-file-shield",
    "hankosign.signatory": "fa-solid fa-user-pen",
    "hankosign.signature": "fa-solid fa-signature",
    
    # Help Pages
    "helppages": "fa-solid fa-circle-question",
    "helppages.helppage": "fa-solid fa-book-open",
    
    # Organisation
    "organisation": "fa-solid fa-building",
    "organisation.orginfo": "fa-solid fa-building-columns",
    
    # People
    "people": "fa-solid fa-users",
    "people.person": "fa-solid fa-user",
    "people.role": "fa-solid fa-user-tag",
    "people.roletransitionreason": "fa-solid fa-arrow-right-arrow-left",
    "people.personrole": "fa-solid fa-user-check",
    
    # Django built-ins
    "auth": "fa-solid fa-shield-halved",
    "auth.user": "fa-solid fa-user-lock",
    "auth.group": "fa-solid fa-users-rectangle",
    "sites": "fa-solid fa-network-wired",
    "sites.site": "fa-solid fa-server",
    "flatpages": "fa-solid fa-file-lines",
    "flatpages.flatpage": "fa-solid fa-file-alt",
},
```

---

### 3.4 Sidebar Ordering

```python
"order_with_respect_to": [
    # Academia
    "academia",
    "academia.inboxrequest",
    "academia.semester",
    
    # Academia Audit
    "academia_audit",
    "academia_audit.auditentry",
    "academia_audit.auditsemester",
    
    # Assembly
    "assembly",
    "assembly.session",
    "assembly.sessionitem",
    "assembly.composition",
    "assembly.term",
    
    # Employees
    "employees",
    "employees.timesheet",
    "employees.timeentry",
    "employees.employmentdocument",
    "employees.employee",
    "employees.holidaycalendar",
    
    # Finances
    "finances",
    "finances.paymentplan",
    "finances.fiscalyear",
    
    # People
    "people",
    "people.personrole",
    "people.person",
    "people.roletransitionreason",
    "people.role",
    
    # HankoSign
    "hankosign",
    "hankosign.signatory",
    "hankosign.policy",
    "hankosign.action",
    
    # Helppages
    "helppages",
    "helppages.helppage",
    
    # Organisation
    "organisation",
    "organisation.orginfo",
    
    # Django built-ins
    "flatpages",
    "flatpages.flatpage",
    "sites",
    "sites.site",
    "auth",
    "auth.user",
    "auth.group",
],
```

---

### 3.5 Hidden Models

```python
"hide_models": [
    "academia.historicalsemester",
    "academia.historicalinboxrequest",
    "academia_audit.historicalauditsemester",
    "academia_audit.historicalauditentry",
    "assembly.historicalterm",
    "assembly.historicalcomposition",
    "assembly.historicalmandate",
    "assembly.historicalsession",
    "assembly.historicalsessionitem",
    "employees.historicalholidaycalendar",
    "employees.historicalemployee",
    "employees.historicalemployeeleaveyear",
    "employees.historicalemploymentdocument",
    "employees.historicaltimesheet",
    "employees.historicaltimeentry",
    "finances.historicalfiscalyear",
    "finances.historicalpaymentplan",
    "hankosign.historicalaction",
    "hankosign.historicalpolicy",
    "hankosign.historicalsignatory",
    "hankosign.historicalsignature",
    "helppages.historicalhelppage",
    "organisation.historicalorginfo",
    "people.historicalperson",
    "people.historicalrole",
    "people.historicalpersonrole",
    "people.historicalroletransitionreason",
],
```

---

### 3.6 UI Configuration

```python
"related_modal_active": True,
"changeform_format": "collapsible",
"language_chooser": True,

# Custom assets
"custom_css": "admin/unihanko_neobrutalist_theme.css",
"custom_js": "admin/custom.js",

# UI builder
"show_ui_builder": False,
```

---

### 3.7 UI Tweaks

```python
JAZZMIN_UI_TWEAKS = {
    # Theme
    "theme": "darkly",
    "dark_mode_theme": "darkly",
    
    # Navbar
    "navbar": "navbar-dark",
    "no_navbar_border": True,
    "navbar_fixed": False,
    
    # Brand/Logo
    "brand_small_text": False,
    "brand_colour": False,
    
    # Text sizes
    "navbar_small_text": False,
    "footer_small_text": True,
    "body_small_text": False,
    
    # Layout
    "layout_boxed": False,
    "footer_fixed": True,
    "sidebar_fixed": True,
    "navigation_expanded": False,
    
    # Sidebar
    "accent": "accent-orange",
    "sidebar": "sidebar-dark-orange",
    "sidebar_nav_small_text": True,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": True,
    "sidebar_nav_compact_style": True,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": True,
    
    # Buttons
    "button_classes": {
        "primary": "btn-primary",
        "secondary": "btn-secondary",
        "info": "btn-outline-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success"
    },
    
    # Actions
    "actions_sticky_top": True
}
```

---

## 4. URL Configuration (urls.py)

```python
from django.contrib import admin
from django.urls import path, include
from core import views as core_views
from django.views.generic import TemplateView
from django.conf import settings

admin.site.index_title = "Dashboard"

urlpatterns = [
    path('tinymce/', include('tinymce.urls')),
    path('i18n/', include('django.conf.urls.i18n')),
    path('captcha/', include('captcha.urls')),
    path('', core_views.home, name='home'),
    path('portal/', include('portal.urls')),
    path('admin/', admin.site.urls),
    path('markdownx/', include('markdownx.urls')),
    path('annotations/', include('annotations.urls')),
    path('assembly/', include('assembly.urls')),
]

if settings.DEBUG:
    urlpatterns += [
        path('test/404/', TemplateView.as_view(template_name='404.html')),
        path('test/500/', TemplateView.as_view(template_name='500.html')),
        path('test/403/', TemplateView.as_view(template_name='403.html')),
        path('test/maintenance/', TemplateView.as_view(template_name='maintenance.html')),
    ]
```

**URL Patterns:**

| Path | Included From | Purpose |
|------|---------------|---------|
| `/` | `core.views.home` | Landing page |
| `/portal/` | `portal.urls` | Public portal |
| `/admin/` | `admin.site.urls` | Admin interface |
| `/annotations/` | `annotations.urls` | Annotation AJAX endpoints |
| `/assembly/` | `assembly.urls` | PROTOKOL-KUN editor |
| `/tinymce/` | `tinymce.urls` | TinyMCE assets |
| `/i18n/` | `django.conf.urls.i18n` | Language switching |
| `/captcha/` | `captcha.urls` | CAPTCHA generation |
| `/markdownx/` | `markdownx.urls` | Markdown preview |

**Debug-Only Routes:**

- `/test/404/` - 404 page test
- `/test/500/` - 500 page test
- `/test/403/` - 403 page test
- `/test/maintenance/` - Maintenance page test

---

## 5. WSGI Application (wsgi.py)

```python
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_wsgi_application()
```

Standard WSGI entry point. Used by Gunicorn in production.

---

## 6. ASGI Application (asgi.py)

```python
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_asgi_application()
```

Standard ASGI entry point. Not currently used (no async views or channels).

---

## 7. Bootstrap Fixtures

### 7.1 Directory Structure

```
config/fixtures/
├── access.yaml              # 241 lines
├── assignments.yaml         # 29 lines
├── fiscal_years.yaml        # 14 lines
├── hankosign_actions.yaml   # 476 lines
├── holiday_calendar.yaml    # 23 lines
├── orginfo.yaml             # 19 lines
├── people.yaml              # 15 lines
├── roles.yaml               # 706 lines
├── semesters.yaml           # 33 lines
├── terms.yaml               # 13 lines
└── transition_reasons.yaml  # 127 lines
```

---

### 7.2 OrgInfo Fixture (orginfo.yaml)

```yaml
# Bootstrap configuration for basic organization information

org_name_long_de: "Hochschülerinnen- und Hochschülerschaft der Fachhochschule Oberösterreich"
org_name_short_de: "ÖH FH OÖ"
org_name_long_en: "Students' Union of the University of Applied Sciences Upper Austria"
org_name_short_en: "ÖH FH OÖ"

uni_name_long_de: "Fachhochschule Oberösterreich"
uni_name_short_de: "FH OÖ"
uni_name_long_en: "University of Applied Sciences Upper Austria"
uni_name_short_en: "FH OÖ"

org_address: |
  Garnisonstraße 21
  A-4020 Linz
  Österreich
```

Comment notes bank details, signatories, and legal disclaimers must be configured manually via admin.

---

### 7.3 HankoSign Actions Fixture (hankosign_actions.yaml)

**Format:**

```yaml
actions:
  - verb: VERB
    stage: "STAGE"  # or "" for no stage
    scope: app.Model
    human_label: "Human-readable label"
    is_repeatable: true/false
    require_distinct_signer: true/false
    comment: "Description"
```

**Example Entries:**

```yaml
- verb: LOCK
  stage: ""
  scope: people.Person
  human_label: "Lock Personnel Record"
  is_repeatable: true
  require_distinct_signer: false
  comment: "Prevents further edits to person record (managers can bypass)"

- verb: SUBMIT
  stage: "WIREF"
  scope: finances.PaymentPlan
  human_label: "Submit Payment Plan (WiRef)"
  is_repeatable: false
  require_distinct_signer: false
  comment: "Employee submits payment plan for WiRef approval"

- verb: APPROVE
  stage: "CHAIR"
  scope: finances.PaymentPlan
  human_label: "Approve Payment Plan (Chair)"
  is_repeatable: false
  require_distinct_signer: true
  comment: "Chair approves payment plan (final approval)"
```

Contains 476 lines defining workflow actions for all modules.

---

### 7.4 Roles Fixture (roles.yaml)

**Format:**

```yaml
roles:
  - name: "Full role name"
    short_name: "Abbreviation"
    ects_cap: 8.0
    is_elected: true/false
    kind: "DEPT. HEAD" | "DEPT. CLERK" | "OTHER"
    is_stipend_reimbursed: true/false
    default_monthly_amount: 300.00
    notes: "Description"
```

**Example Entries:**

```yaml
- name: "Vorsitzende:r HV"
  short_name: "Vorsitz"
  ects_cap: 8.0
  is_elected: false
  kind: "DEPT. HEAD"
  is_stipend_reimbursed: true
  default_monthly_amount: 300.00
  notes: "Vorsitzende:r HV ÖH FH OÖ, Wahl idR durch HV-Konstitution"

- name: "Mandatar:in HV"
  short_name: "MandatHV"
  ects_cap: 6.0
  is_elected: true
  kind: "OTHER"
  is_stipend_reimbursed: false
  default_monthly_amount: 0.00
  notes: "Mandatar:in HV ÖH FH OÖ, WAHLAMT gem. HSG 2014"

- name: "Wirtschaftsreferent:in"
  short_name: "WiRef"
  ects_cap: 8.0
  is_elected: false
  kind: "DEPT. HEAD"
  is_stipend_reimbursed: true
  default_monthly_amount: 250.00
  notes: "WiRef, Wahl idR durch HV"
```

Contains 706 lines defining organizational roles.

---

## 8. Important Notes

### 8.1 Production Deployment

**Comment from settings.py:**

```python
# Production/Staging ('Suupu'): Docker mount
```

Production environment nickname is "Suupu".

**Reverse Proxy:**

System runs behind Caddy reverse proxy. DO NOT set `SECURE_SSL_REDIRECT = True` as it would cause infinite redirects.

---

### 8.2 Secret Management

Production requires:
- `SECRET_KEY`
- `HANKOSIGN_SECRET`
- `CSRF_TRUSTED_ORIGINS`
- MinIO credentials (if using S3 storage)

All fail loudly if not set when `DEBUG = False`.

---

### 8.3 Bootstrap Data Location

Development uses `config/fixtures/` in repository.

Production uses `/mnt/bootstrap-data` Docker mount (sensitive data never in repo).

---

### 8.4 Jazzmin Ordering

Sidebar order explicitly controlled via `order_with_respect_to`. Changes to this list affect admin sidebar appearance.

---

**Version:** 1.0.3  
**Last Updated:** 2025-12-08  
**Author:** Sven (vas)