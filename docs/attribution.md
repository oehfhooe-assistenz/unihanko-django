# Third-Party Licenses and Attribution

UniHanko uses the following open-source libraries and components. We are grateful to their 
authors and contributors.

---

## Django Web Framework

- **License:** BSD-3-Clause
- **Source:** https://github.com/django/django
- **Copyright:** Django Software Foundation and contributors

```
Copyright (c) Django Software Foundation and individual contributors.
All rights reserved.

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

    1. Redistributions of source code must retain the above copyright notice,
       this list of conditions and the following disclaimer.

    2. Redistributions in binary form must reproduce the above copyright
       notice, this list of conditions and the following disclaimer in the
       documentation and/or other materials provided with the distribution.

    3. Neither the name of Django nor the names of its contributors may be used
       to endorse or promote products derived from this software without
       specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

Full license: https://github.com/django/django/blob/main/LICENSE

---

## Django Jazzmin Admin Theme

- **License:** MIT
- **Source:** https://github.com/farridav/django-jazzmin
- **Copyright:** farridav and contributors
- **Usage:** Modern admin interface theme with Bootstrap 5

```
MIT License

Copyright (c) 2019 farridav

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## TinyMCE Rich Text Editor

- **License:** LGPL-2.1 (or Commercial)
- **Source:** https://github.com/tinymce/tinymce
- **Django Wrapper:** https://github.com/jazzband/django-tinymce (MIT)
- **Copyright:** Tiny Technologies Inc.
- **Usage:** Rich text editor for protocol and document editing

TinyMCE is licensed under the GNU Lesser General Public License v2.1. This allows its use 
in proprietary applications as long as the library itself is not modified. If you modify 
TinyMCE's source code, those modifications must be shared under LGPL-2.1.

The django-tinymce wrapper package is separately licensed under MIT.

Full license: https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html

**Note:** UniHanko uses TinyMCE as-is without modifications. If you deploy this system 
commercially or at scale, consider purchasing a commercial TinyMCE license from 
Tiny Technologies Inc.

---

## Alpine.js

- **License:** MIT
- **Source:** https://github.com/alpinejs/alpine
- **Copyright:** Caleb Porzio and contributors
- **Usage:** Reactive JavaScript framework for PROTOKOL-KUN protocol editor

```
MIT License

Copyright (c) Caleb Porzio and contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## PostgreSQL

- **License:** PostgreSQL License (similar to BSD/MIT)
- **Source:** https://www.postgresql.org/
- **Copyright:** PostgreSQL Global Development Group
- **Usage:** Primary database system

```
PostgreSQL is released under the PostgreSQL License, a liberal Open Source license, 
similar to the BSD or MIT licenses.

PostgreSQL Database Management System
(formerly known as Postgres, then as Postgres95)

Portions Copyright (c) 1996-2024, PostgreSQL Global Development Group
Portions Copyright (c) 1994, The Regents of the University of California

Permission to use, copy, modify, and distribute this software and its documentation 
for any purpose, without fee, and without a written agreement is hereby granted, 
provided that the above copyright notice and this paragraph and the following two 
paragraphs appear in all copies.
```

Full license: https://www.postgresql.org/about/licence/

---

## MinIO Object Storage

- **License:** AGPL-3.0
- **Source:** https://github.com/minio/minio
- **Copyright:** MinIO, Inc.
- **Usage:** File and document storage backend (used as external service)

MinIO is licensed under the GNU Affero General Public License v3.0. UniHanko uses MinIO 
as a separate storage service via its S3-compatible API and does not modify or embed 
MinIO's source code.

Full license: https://github.com/minio/minio/blob/master/LICENSE

**Note:** If you modify MinIO itself, those modifications must be shared under AGPL-3.0. 
Using MinIO as a storage backend via its API does not require your application to be 
AGPL-licensed.

---

## Python Packages

UniHanko uses numerous Python packages from PyPI. Key dependencies include:

### Core Framework

- **Django** (BSD-3-Clause) - Web framework
- **django-environ** (MIT) - Environment variable management
- **asgiref** (BSD) - ASGI reference implementation

### Admin Interface & UI

- **django-jazzmin** (MIT) - Modern admin theme with Bootstrap 5
- **django-admin-sortable2** (MIT) - Drag-and-drop sorting in admin
- **django-admin-inline-paginator-plus** (MIT) - Pagination for inline models
- **django-object-actions** (MIT) - Custom admin object actions
- **django-colorfield** (MIT) - Color picker field
- **django-static-fontawesome** (MIT/CC BY 4.0) - Font Awesome icons
- **django-static-jquery3** (MIT) - jQuery integration

### Document & File Processing

- **weasyprint** (BSD-3-Clause) - HTML to PDF conversion
- **pikepdf** (MPL-2.0) - PDF manipulation and validation
- **Pillow** (HPND License) - Image processing
- **xlsxwriter** (BSD) - Excel file generation
- **python-barcode** (MIT) - Barcode generation
- **qrcode** (BSD) - QR code generation
- **lxml** (BSD) - XML/HTML processing

### Content & Editing

- **django-tinymce** (MIT) - TinyMCE integration
- **django-markdownx** (BSD) - Markdown editor with live preview
- **Markdown** (BSD) - Markdown parsing

### Storage & AWS

- **boto3** (Apache-2.0) - AWS SDK for S3/MinIO
- **botocore** (Apache-2.0) - AWS SDK core
- **django-storages** (BSD-3-Clause) - Django storage backends
- **s3transfer** (Apache-2.0) - S3 transfer utilities

### Database & History

- **django-simple-history** (BSD-3-Clause) - Model history tracking
- **django-concurrency** (MIT) - Optimistic locking
- **django-solo** (MIT) - Singleton model pattern

### Security & Rate Limiting

- **django-axes** (MIT) - Failed login attempt tracking
- **django-ratelimit** (Apache-2.0) - Rate limiting decorator
- **django-simple-captcha** (MIT) - CAPTCHA integration

### Import/Export & Data

- **django-import-export** (BSD) - CSV/Excel import/export
- **tablib** (MIT) - Tabular data library
- **PyYAML** (MIT) - YAML parser
- **defusedxml** (PSF) - Secure XML parsing

### PDF & Rendering

- **django-renderpdf** (MIT) - PDF rendering utilities
- **weasyprint** (BSD-3-Clause) - CSS-based PDF generation
- **fonttools** (MIT) - Font manipulation
- **pyphen** (GPL-2.0/LGPL-2.1/MPL-1.1) - Hyphenation
- **cssselect2** (BSD-3-Clause) - CSS selector engine
- **tinycss2** (BSD-3-Clause) - CSS parser
- **html5lib** (MIT) - HTML5 parser

### Utilities

- **python-slugify** (MIT) - URL slug generation
- **text-unidecode** (GPL-2.0+) - Unicode transliteration
- **python-dateutil** (Apache-2.0/BSD) - Date parsing
- **babel** (BSD) - Internationalization
- **colorama** (BSD) - Colored terminal output
- **wrapt** (BSD) - Python wrapper utilities
- **Deprecated** (MIT) - Deprecation decorator

### Compression & Encoding

- **Brotli** (MIT) - Brotli compression
- **zopfli** (Apache-2.0) - Zopfli compression
- **webencodings** (BSD) - Character encoding

---

## Fonts

### Noto Sans JP

- **License:** SIL Open Font License 1.1
- **Source:** https://fonts.google.com/noto/specimen/Noto+Sans+JP
- **Copyright:** Google Inc.
- **Usage:** Primary UI font for Neo-Japanese neobrutalist design aesthetic

```
This Font Software is licensed under the SIL Open Font License, Version 1.1.
This license is copied below, and is also available with a FAQ at:
http://scripts.sil.org/OFL
```

---

## Icons and Assets

### FontAwesome Icons

- **License:** CC BY 4.0 (icons), SIL OFL 1.1 (fonts), MIT (code)
- **Source:** https://fontawesome.com/
- **Copyright:** Fonticons, Inc.
- **Usage:** UI icons throughout the application

UniHanko uses Font Awesome Free icons under the Creative Commons Attribution 4.0 
International license, delivered via django-static-fontawesome.

---

## Notable License Considerations

### GPL-Licensed Components

UniHanko includes some GPL-licensed components:

1. **text-unidecode** (GPL-2.0+) - Used as a library for Unicode transliteration
2. **pyphen** (GPL-2.0/LGPL-2.1/MPL-1.1) - Hyphenation library for PDF generation

These are used as libraries and do not affect UniHanko's overall licensing. However, 
if you modify these packages, those modifications must be shared under their respective 
licenses.

### LGPL Components

1. **TinyMCE** (LGPL-2.1) - Used as-is without modifications
2. **pyphen** (also available under LGPL-2.1) - Used as library

LGPL allows use in proprietary applications as long as the library is not modified.

### MPL Components

1. **pikepdf** (MPL-2.0) - Mozilla Public License allows use in proprietary software
2. **pyphen** (also available under MPL-1.1) - Triple-licensed

---

## Attribution Summary

UniHanko is built on the shoulders of giants. We gratefully acknowledge:

- The Django Software Foundation for Django
- farridav and contributors for Django Jazzmin
- The PostgreSQL Global Development Group for PostgreSQL
- Tiny Technologies Inc. for TinyMCE
- Caleb Porzio for Alpine.js
- MinIO, Inc. for MinIO object storage
- The authors and maintainers of WeasyPrint, Pillow, and pikepdf for document processing
- All Python package maintainers and contributors
- The broader open-source community

---

## License Compliance

UniHanko complies with all license requirements of its dependencies:

1. **Permissive licenses (MIT, BSD, Apache, PSF):** Used as-is, attribution provided
2. **LGPL (TinyMCE):** Used as library, not modified
3. **GPL (text-unidecode, pyphen):** Used as libraries for data processing
4. **MPL (pikepdf):** Used as library, modifications would be shared
5. **AGPL (MinIO):** Used as separate service via API, not embedded

---

## Complete Dependency List

For a complete list of all dependencies with exact versions, see `requirements.txt` in 
the project root. Each package's full license can be found in their respective PyPI 
repositories or GitHub sources.

---

## Reporting License Issues

If you believe UniHanko violates any license terms or if you have licensing questions, 
please contact: office@oeh.fh-ooe.at

Last updated: December 2024