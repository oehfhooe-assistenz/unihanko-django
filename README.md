# UniHanko

**Version:** 1.0.0 "Sakura"  
**Django-based Administrative System for Austrian Students' Unions**

---

## Overview

UniHanko is a comprehensive administrative management system designed for the Austrian Students' Union (ÖH FH OÖ) at the University of Applied Sciences Upper Austria. It provides integrated tools for personnel management, financial administration, legislative assembly protocols, ECTS reimbursement processing, and digital signature workflows.

**Key Features:**
- **Digital Signature Workflows** - HankoSign system with HMAC-SHA256 attestation
- **Personnel Management** - Role assignments, certificates, time tracking
- **Financial Administration** - Payment plans with proration, fiscal year management
- **Assembly Protocols** - PROTOKOL-KUN editor with TinyMCE and Alpine.js
- **ECTS Processing** - Reimbursement requests with audit trails
- **Public Portal** - Self-service filing for ECTS and payment plans
- **Document Generation** - WeasyPrint-powered PDF generation with attestation seals
- **Bilingual Support** - German/English UI with django-i18n

**Tech Stack:**
- Django 5.2.5 + PostgreSQL
- WeasyPrint for PDF generation
- MinIO (S3-compatible) for file storage
- Django Jazzmin for modern admin interface
- TinyMCE + Alpine.js for rich editing
- Neo-Japanese neobrutalist design aesthetic

---

## Documentation

All technical documentation is available in the [`docs/`](./docs/) directory:

### System Architecture

- **[CONFIG.md](./docs/config.md)** - Django project configuration, settings structure, environment variables
- **[CORE.md](./docs/core.md)** - Core utilities, middleware, PDF generation, privacy helpers
- **[TEMPLATES.md](./docs/templates.md)** - Template system overview (76 templates across admin/PDF/portal contexts)

### Core Modules

- **[HANKOSIGN.md](./docs/hankosign.md)** - Digital signature workflow system with HMAC attestation
- **[PEOPLE.md](./docs/people.md)** - Personnel management (Person, Role, PersonRole, certificates)
- **[FINANCES.md](./docs/finances.md)** - Fiscal years, payment plans, proration calculations
- **[EMPLOYEES.md](./docs/employees.md)** - Employment contracts, timesheets, PTO tracking
- **[ASSEMBLY.md](./docs/assembly.md)** - Legislative assembly management, PROTOKOL-KUN editor
- **[ACADEMIA.md](./docs/academia.md)** - ECTS reimbursement filing system
- **[ACADEMIA_AUDIT.md](./docs/academia_audit.md)** - ECTS final calculations and audit reports
- **[ORGANISATION.md](./docs/organisation.md)** - Singleton master data (banking, signatories)
- **[HELPPAGES.md](./docs/helppages.md)** - Bilingual help system for admin pages
- **[ANNOTATIONS.md](./docs/annotations.md)** - Generic commenting system across models
- **[PORTAL.md](./docs/portal.md)** - Public self-service portal (no authentication required)

### Reference

- **[LICENSE.md](./docs/license.md)** - Proprietary license with ÖH FH OÖ perpetual license
- **[ATTRIBUTION.md](./docs/attribution.md)** - Third-party open-source licenses and acknowledgments

---

## Project Structure

```
unihanko-django/
├── academia/              # ECTS reimbursement filing
├── academia_audit/        # ECTS audit calculations
├── annotations/           # Generic commenting system
├── assembly/              # Legislative assembly protocols
├── config/                # Django project configuration
├── core/                  # Core utilities and middleware
├── employees/             # Employment contracts and timesheets
├── finances/              # Fiscal years and payment plans
├── hankosign/             # Digital signature workflows
├── helppages/             # Bilingual help system
├── locale/                # Translation files (DE/EN)
├── media/                 # User-uploaded files (MinIO)
├── organisation/          # Master organisation data
├── people/                # Personnel and role management
├── portal/                # Public self-service portal
├── static/                # Static assets (CSS, JS, images)
├── templates/             # Django templates (76 files)
├── docs/                  # Technical documentation
├── manage.py              # Django management script
├── requirements.txt       # Python dependencies
└── README.md              # This file
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- MinIO (or S3-compatible storage)
- Redis (for caching and rate limiting)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/oehfhooe-assistenz/unihanko-django.git
   cd unihanko-django
   ```

2. **Create virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your database, MinIO, and secret key settings
   ```

5. **Run migrations:**
   ```bash
   python manage.py migrate
   ```

6. **Create superuser:**
   ```bash
   python manage.py createsuperuser
   ```

7. **Bootstrap initial data:**
   ```bash
   python manage.py bootstrap_actions      # HankoSign actions
   python manage.py bootstrap_acls         # HankoSign policies
   python manage.py bootstrap_roles        # Default roles
   python manage.py bootstrap_org          # Organisation singleton
   ```

8. **Run development server:**
   ```bash
   python manage.py runserver
   ```

9. **Access the application:**
   - Admin: http://localhost:8000/admin/
   - Portal: http://localhost:8000/portal/

### First-Time Setup

After initial installation:

1. Configure **Organisation** singleton (Admin → Organisation)
2. Create **Fiscal Years** (Admin → Finances → Fiscal Years)
3. Create **Semesters** (Admin → Academia → Semesters)
4. Add **People** and assign **Roles** (Admin → People)
5. Create **Signatories** for HankoSign workflows (Admin → HankoSign)
6. Configure **Help Pages** for admin pages (Admin → Help Pages)

See [CONFIG.md](./docs/config.md) for detailed configuration options.

---

## Development

### Running Tests

```bash
# Run all tests
python manage.py test

# Run specific app tests
python manage.py test people
python manage.py test finances.tests.test_proration

# Run with coverage
coverage run --source='.' manage.py test
coverage report
```

### Code Style

- **Black** for Python formatting
- **Flake8** for linting
- **MyPy** for type checking (partial coverage)

### Translation Workflow

1. **Extract messages:**
   ```bash
   python manage.py makemessages -l de
   python manage.py makemessages -l en
   ```

2. **Translate in `.po` files:**
   - Edit `locale/de/LC_MESSAGES/django.po`
   - Edit `locale/en/LC_MESSAGES/django.po`

3. **Compile messages:**
   ```bash
   python manage.py compilemessages
   ```

### Database Migrations

```bash
# Create migrations
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Show migration status
python manage.py showmigrations
```

---

## Deployment

**Note:** Deployment documentation is currently in progress and will be provided separately.

For production deployment, consider:
- A separate `deployment/` directory with Docker Compose configuration
- `README_DEPLOYMENT.md` or `DEPLOYMENT.md` with deployment-specific instructions
- Environment-specific settings for staging and production

Recommended deployment stack:
- **Web Server:** Caddy
- **Database:** PostgreSQL
- **Storage:** MinIO cluster or AWS S3
- **Process Manager:** Docker
- **SSL/TLS:** Let's Encrypt via Certbot

---

## Module Overview

### HankoSign - Digital Signature System

A cryptographic signature workflow system using HMAC-SHA256 attestation. Provides:
- **Actions:** SUBMIT, APPROVE, VERIFY, RELEASE, REJECT, LOCK, UNLOCK
- **Stages:** WIREF (Financial Officer), CHAIR (Chairperson), ASS (Assembly)
- **Status Machine:** Reduces signatures to workflow state (DRAFT → PENDING → ACTIVE → FINISHED)
- **Attestation Seals:** Cryptographically signed PDF seals with audit trails

See [HANKOSIGN.md](./docs/hankosign.md) for complete documentation.

### People - Personnel Management

Core personnel and role management system:
- **Person:** Individual records with UUID, matric_no, personal access codes
- **Role:** Position definitions with ECTS caps and stipend amounts
- **PersonRole:** Time-bound assignments with effective dates and transition reasons
- **Certificates:** Automated generation (appointment, confirmation, resignation)

See [PEOPLE.md](./docs/people.md) for complete documentation.

### Finances - Payment Administration

Fiscal year and payment plan management:
- **FiscalYear:** July 1 - June 30 periods with lock protection
- **PaymentPlan:** Monthly stipend payments with 30-day proration
- **Status Workflow:** DRAFT → PENDING → ACTIVE → FINISHED (via HankoSign)
- **Banking Details:** IBAN/BIC validation, reference generation

See [FINANCES.md](./docs/finances.md) for complete documentation.

### Assembly - Protocol Management

Legislative assembly session management:
- **Term:** Legislative periods with composition tracking
- **Session:** Assembly meetings with agenda items
- **PROTOKOL-KUN:** Custom protocol editor with TinyMCE + Alpine.js
- **Decisions:** Vote recording with decision types and results

See [ASSEMBLY.md](./docs/assembly.md) for complete documentation.

### Academia - ECTS Processing

ECTS reimbursement request handling:
- **InboxRequest:** Public filing with reference codes (SSSS-LLLL-####)
- **Validation:** Role ECTS cap enforcement with aliquotation
- **Audit:** Semester-wide reports with aggregated statistics
- **Portal:** Self-service filing and status tracking

See [ACADEMIA.md](./docs/academia.md) and [ACADEMIA_AUDIT.md](./docs/academia_audit.md).

### Employees - Contract Management

Employment contract and time tracking:
- **WorkContract:** Employment periods with salary and PTO entitlements
- **Timesheet:** Monthly time tracking with sick leave and PTO
- **LeaveRequest:** Vacation requests with approval workflow
- **SickNote:** Doctor's note tracking

See [EMPLOYEES.md](./docs/employees.md) for complete documentation.

### Portal - Public Self-Service

Unauthenticated public access portal:
- **ECTS Filing:** Semester access codes → file requests → upload signed forms
- **Payment Plans:** Personal access codes → banking details → upload signed forms
- **Security:** CAPTCHA, rate limiting, PDF validation
- **Anti-Ping-Pong:** All steps visible on single page (accordion design)

See [PORTAL.md](./docs/portal.md) for complete documentation.

---

## Design Philosophy

### Neo-Japanese Neobrutalist Aesthetic

UniHanko features a distinctive visual design:
- **Chunky Borders:** 4-5px solid black borders throughout
- **Brutal Shadows:** `6px 6px 0 #000` offset shadows
- **High Contrast:** ÖH orange (#f2a535) on black/white
- **Typography:** Noto Sans JP for headers, system fonts for body
- **Animated Elements:** Cherry blossoms on landing, soup bowls on 404
- **Text Shadows:** Multi-layer shadows for emphasis

See [TEMPLATES.md](./docs/templates.md) for complete design system documentation.

### Code Principles

- **Explicit is better than implicit:** Clear model relationships, no magic
- **Atomic operations:** Database transactions for critical paths
- **Separation of concerns:** Pure functions for business logic
- **Fail-safe defaults:** Conservative permissions, opt-in features
- **Audit trails:** HistoricalRecords on all models, HankoSign signatures
- **Bilingual by default:** DE/EN support throughout

---

## Security Features

- **Optimistic Locking:** django-concurrency prevents concurrent modification conflicts
- **CSRF Protection:** Django's built-in CSRF middleware
- **Rate Limiting:** django-ratelimit on public endpoints
- **Failed Login Tracking:** django-axes with IP blocking
- **CAPTCHA:** django-simple-captcha on public forms
- **PDF Validation:** pikepdf security checks (no embedded files/JavaScript)
- **IBAN Validation:** Mod-97 checksum verification
- **HMAC Signatures:** SHA-256 attestation for workflow actions
- **IP Logging:** Audit trail for public submissions

---

## Performance Considerations

- **Prefetch & Select Related:** Optimized querysets throughout
- **Database Indexes:** Strategic indexing on foreign keys and date fields
- **Caching:** Redis for session and rate limit storage
- **Static Files:** Collected and served via CDN-ready structure
- **PDF Generation:** Cached WeasyPrint font loading
- **Pagination:** Admin inlines paginated (10 items default)

---

## Browser Support

- **Modern Browsers:** Chrome, Firefox, Safari, Edge (last 2 versions)
- **No IE11:** Modern JavaScript features required
- **Mobile Responsive:** Admin and portal optimized for tablets/phones

---

## Contributing

UniHanko is proprietary software with a perpetual license granted to ÖH FH OÖ. 

For bug reports, feature requests, or questions:
- **Email:** office@oeh.fh-ooe.at
- **Internal Issues:** Contact system administrator

---

## License

Copyright © 2025-2026 Sven Várszegi. All rights reserved.

UniHanko is proprietary software. See [LICENSE.md](./docs/license.md) for license terms.

Third-party open-source components are used under their respective licenses. See [ATTRIBUTION.md](./docs/attribution.md) for complete attribution.

---

## Acknowledgments

UniHanko is built with:
- Django Web Framework (BSD-3-Clause)
- Django Jazzmin (MIT)
- WeasyPrint (BSD-3-Clause)
- TinyMCE (LGPL-2.1)
- Alpine.js (MIT)
- PostgreSQL (PostgreSQL License)
- MinIO (AGPL-3.0, used as external service)

See [ATTRIBUTION.md](./docs/attribution.md) for complete list and license texts.

Special thanks to the open-source community and all contributors.

---

**Last Updated:** December 2025
**Version:** 1.0.0 "Sakura"