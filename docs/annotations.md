# Annotations Module

## 1. Overview

The Annotations module provides a generic commenting/note system that can attach to any model in UniHanko. It supports user comments, system-generated event logs, correction notes, and workflow action tracking with bilingual messages.

**Key Responsibilities:**
- Generic annotation attachment to any model via GenericForeignKey
- User collaboration through comments on objects
- System event logging for workflow actions (HankoSign integration)
- Correction tracking for data issues
- AJAX-based annotation management

**Dependencies:**
- Django's `contenttypes` framework (GenericForeignKey)
- `core` - Admin mixins, help widgets
- Standard Django authentication

**Used By:**
- Nearly all modules include `AnnotationInline` in their admin interfaces
- Workflow actions in `academia`, `academia_audit`, `hankosign`, etc.

---

## 2. Models

### 2.1 Annotation

Generic annotation model that can attach to any model instance.

**Purpose:** Provides a flexible commenting system for collaboration, system event logging, and correction tracking across all models.

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `content_type` | FK(ContentType) | Type of object this annotation is attached to (CASCADE) |
| `object_id` | PositiveIntegerField | ID of the specific object |
| `content_object` | GenericForeignKey | Generic relation to any model |
| `annotation_type` | CharField(20) | Type of annotation (see enum below) |
| `text` | TextField | Annotation content |
| `created_by` | FK(User) | User who created (nullable for system annotations, PROTECT) |
| `created_at` | DateTimeField | Creation timestamp (auto) |
| `updated_at` | DateTimeField | Last update timestamp (auto) |

**AnnotationType Enum:**

```python
class AnnotationType(models.TextChoices):
    USER = "USER", "User Comment"
    SYSTEM = "SYSTEM", "System Event"
    CORRECTION = "CORRECTION", "Correction"
    INFO = "INFO", "Information"
```

**Indexes:**
- Composite index on `(content_type, object_id)` for fast lookups

**Ordering:**
- Default: `-created_at` (newest first)

**String Representation:**

```python
"{Type} by {Creator} at {DateTime}"
# Examples:
# "User Comment by Sven Varszegi at 2025-12-08 14:30"
# "System Event by SYSTEM at 2025-12-08 14:30"
```

**Properties:**

```python
@property
def is_system(self) -> bool:
    """Returns True if annotation_type is SYSTEM"""
```

---

## 3. Admin Features

### 3.1 AnnotationInline

Generic tabular inline that can be added to **any** model admin.

**Usage:**

```python
from annotations.admin import AnnotationInline

@admin.register(YourModel)
class YourModelAdmin(admin.ModelAdmin):
    inlines = [AnnotationInline]
```

**Display:**
- Tabular inline (compact view)
- Paginated (3 per page)
- Shows: type, text, creator, created timestamp

**Behavior:**

| Feature | Behavior |
|---------|----------|
| **Saved annotations** | Read-only (text and type fields disabled) |
| **New annotations** | Editable text area (3 rows), type dropdown |
| **SYSTEM type** | Hidden from non-superusers (can't create SYSTEM annotations) |
| **created_by** | Auto-set to current user on save |
| **Deletion** | Only superusers can delete |

**Form Customization:**

The inline uses a custom `ConditionalReadonlyForm` that:
- Sets `text` widget to 3-row textarea for new annotations
- Makes saved annotations readonly by disabling fields
- Filters out SYSTEM type from dropdown for non-superusers
- Preserves annotation_type display value for saved annotations

**Auto-set created_by:**

```python
# In save_formset() and form.save()
if not instance.created_by:
    instance.created_by = request.user
```

**Custom CSS:**

References `annotations/admin_inline.css` for compact styling.

**Deletion Permission:**

Only superusers can delete annotations via inline.

---

### 3.2 AnnotationAdmin

Standalone admin for viewing all annotations across the system.

**Purpose:** System-wide annotation overview and cleanup (superuser only).

**List Display:**
- Type, attached object, text preview (50 chars)
- Creator, created timestamp

**List Filters:**
- Annotation type
- Created at (date hierarchy)
- Content type (which model)

**Search:**
- Text content

**Readonly Fields:**
- `content_type`, `object_id`, `created_by`, `created_at`, `updated_at`

**Permissions:**
- Add: Disabled (use inlines instead)
- Delete: Allowed for superusers
- View: Hidden from non-superusers in sidebar

**Queryset Optimization:**

```python
qs.select_related('created_by', 'content_type')
```

**Display Functions:**

```python
content_object_display(obj):
    # Shows: "inboxrequest: WS24-SMIT-1234"
    # Or: "inboxrequest #123" if object deleted
    
text_preview(obj):
    # Truncates to 50 chars: "This is a long annotation text that will be..."
```

---

## 4. Views & AJAX Endpoints

### 4.1 add_annotation

**Endpoint:** `POST /annotations/add/`

**Purpose:** AJAX endpoint to create new annotations.

**Required Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `content_type_id` | int | ContentType ID of target object |
| `object_id` | int | ID of target object |
| `text` | string | Annotation text (trimmed) |
| `annotation_type` | string | Optional, defaults to USER |

**Permission Checks:**

1. User must be staff (`@staff_member_required`)
2. User must have `{app}.change_{model}` permission
3. Only superusers can create SYSTEM annotations
4. Target object must exist

**Validation:**

```python
# 1. Required fields check
if not all([content_type_id, object_id, text]):
    return 400 - Missing required fields

# 2. Object existence check
try:
    target_object = model_class.objects.get(pk=object_id)
except DoesNotExist:
    return 404 - Object not found

# 3. Permission check
perm = f'{app_label}.change_{model_name}'
if not request.user.has_perm(perm):
    return 403 - Permission denied

# 4. Type validation
if annotation_type not in valid_types:
    annotation_type = USER  # Fallback

# 5. SYSTEM type restriction
if annotation_type == SYSTEM and not superuser:
    annotation_type = USER  # Downgrade
```

**Response Format:**

Success (200):
```json
{
    "success": true,
    "annotation_id": 123,
    "message": "Annotation added successfully"
}
```

Error (400/403/404/500):
```json
{
    "success": false,
    "message": "Error message"
}
```

**Transaction Safety:**

Wrapped in `@transaction.atomic` - changes rolled back on error.

---

### 4.2 delete_annotation

**Endpoint:** `POST /annotations/delete/<annotation_id>/`

**Purpose:** AJAX endpoint to delete annotations.

**Permission Requirements:**

1. User must be staff
2. User must be creator OR superuser
3. User must still have `change` permission on parent model

**Permission Logic:**

```python
# 1. Creator or superuser check
if annotation.created_by != request.user and not superuser:
    return 403 - Permission denied

# 2. Parent model permission check (for non-superusers)
if not superuser:
    perm = f'{app_label}.change_{model_name}'
    if not request.user.has_perm(perm):
        return 403 - Permission denied

# 3. Delete
annotation.delete()
```

**Response Format:**

Success (200):
```json
{
    "success": true,
    "message": "Annotation deleted"
}
```

Error (403):
```json
{
    "success": false,
    "message": "You do not have permission to delete this annotation"
}
```

**Transaction Safety:**

Wrapped in `@transaction.atomic`.

---

### 4.3 create_system_annotation

**Purpose:** Programmatic helper for creating system annotations in code.

**Function Signature:**

```python
def create_system_annotation(
    content_object,
    text_or_action,
    annotation_type=None,
    user=None
) -> Annotation
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `content_object` | Model instance | Any Django model to attach to |
| `text_or_action` | string | HankoSignAction constant OR custom text |
| `annotation_type` | AnnotationType | Optional, defaults to SYSTEM |
| `user` | User | Required for HankoSign actions, optional for custom |

**Two Modes:**

**Mode 1: HankoSign Action (Bilingual)**

```python
# Using HankoSignAction constants
create_system_annotation(session, "SUBMIT", user=request.user)
# → "[HS] Eingereicht durch / Submitted by Sven Varszegi"

create_system_annotation(fiscal_year, "LOCK", user=request.user)
# → "[HS] Gesperrt durch / Locked by Sven Varszegi"

create_system_annotation(audit, "APPROVE", user=request.user)
# → "[HS] Genehmigt durch / Approved by Sven Varszegi"
```

**Mode 2: Custom Text**

```python
# Custom text for non-workflow events
create_system_annotation(session, "Protocol finalized and sent to KoKo")
# → "Protocol finalized and sent to KoKo"

create_system_annotation(entry, f"Synchronized: 5 created, 3 updated", user=request.user)
# → "Synchronized: 5 created, 3 updated"
```

**Detection Logic:**

```python
# 1. Try to interpret as HankoSign action
hs_text = HankoSignAction.get_text(text_or_action, user)

if hs_text:
    # It's a recognized action → use bilingual template
    text = hs_text
else:
    # It's custom text → use as-is
    text = text_or_action
```

**Return Value:**

Returns the created `Annotation` instance.

---

## 5. HankoSignAction Helper

Provides standardized bilingual text templates for workflow actions.

**Purpose:** Consistent, bilingual annotation messages for HankoSign workflow events.

**Available Action Constants:**

| Constant | Bilingual Template |
|----------|-------------------|
| `LOCK` | Gesperrt durch / Locked by {user} |
| `UNLOCK` | Entsperrt durch / Unlocked by {user} |
| `APPROVE` | Genehmigt durch / Approved by {user} |
| `REJECT` | Zurückgewiesen durch / Rejected by {user} |
| `VERIFY` | Bestätigt durch / Verified by {user} |
| `RELEASE` | Freigegeben durch / Released by {user} |
| `SUBMIT` | Eingereicht durch / Submitted by {user} |
| `WITHDRAW` | Zurückgezogen durch / Withdrawn by {user} |

**Method: get_text()**

```python
@classmethod
def get_text(cls, action_type: str, user: User) -> str | None:
    """
    Get formatted bilingual text for a HankoSign action.
    
    Returns:
        Formatted text with [HS] prefix, or None if action unknown
    """
```

**Behavior:**

```python
# Known action
HankoSignAction.get_text("LOCK", user)
# → "[HS] Gesperrt durch / Locked by Sven Varszegi"

# Unknown action
HankoSignAction.get_text("UNKNOWN", user)
# → None

# User without get_full_name
HankoSignAction.get_text("LOCK", None)
# → "[HS] Gesperrt durch / Locked by System"
```

**Usage Pattern:**

```python
# In workflow action methods
from annotations.views import create_system_annotation

@transaction.atomic
@safe_admin_action
def lock_semester(self, request, obj):
    # ... record signature ...
    create_system_annotation(obj, "LOCK", user=request.user)
    # Creates: "[HS] Gesperrt durch / Locked by {user}"
```

---

## 6. Template Tags

### 6.1 get_annotations_for

**Purpose:** Retrieve annotations for an object in templates.

**Usage:**

```django
{% load annotation_tags %}

{% get_annotations_for session_item as annotations %}
{% for annotation in annotations %}
    <div class="annotation">
        <strong>{{ annotation.created_by }}</strong>: {{ annotation.text }}
        <small>{{ annotation.created_at }}</small>
    </div>
{% endfor %}
```

**With Type Filter:**

```django
{% get_annotations_for session_item "USER" as user_annotations %}
{% for annotation in user_annotations %}
    {{ annotation.text }}
{% endfor %}
```

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `obj` | Yes | Model instance to get annotations for |
| `annotation_type` | No | Filter by type (e.g., "USER", "SYSTEM") |

**Query Optimization:**

```python
.select_related('created_by')  # Avoids N+1 queries
```

---

### 6.2 get_content_type_id

**Purpose:** Get ContentType ID for AJAX calls.

**Usage:**

```django
{% load annotation_tags %}
{% get_content_type_id session_item as ct_id %}

<input type="hidden" name="content_type_id" value="{{ ct_id }}">
```

Useful for building AJAX forms that need to pass content_type_id.

---

### 6.3 annotation_count

**Purpose:** Count annotations for an object.

**Usage:**

```django
{% load annotation_tags %}

<span class="badge">{{ session_item|annotation_count }}</span>
```

Returns integer count of annotations attached to the object.

---

## 7. Workflows

### 7.1 User Comment Workflow

**Adding a Comment (via inline):**

```
1. Admin opens object change page
2. Scrolls to Annotation inline
3. Fills text in new annotation form
4. Selects type (USER/CORRECTION/INFO)
5. Saves object
   → created_by auto-set to current user
   → Annotation created
```

**Editing a Comment:**

Saved annotations are **read-only**. Users cannot edit after saving.

**Deleting a Comment:**

```
1. Creator or superuser views object
2. Checks "Delete?" checkbox on annotation
3. Saves object
   → Permission check runs
   → Annotation deleted if authorized
```

---

### 7.2 System Annotation Workflow

**Automatic Creation on Workflow Actions:**

```python
# In admin object action
@transaction.atomic
@safe_admin_action
def verify_request(self, request, obj):
    # 1. Perform business logic
    action = get_action("VERIFY:-@academia.InboxRequest")
    record_signature(request, action, obj, note=f"Request {obj.reference_code} verified")
    
    # 2. Create system annotation
    create_system_annotation(obj, "VERIFY", user=request.user)
    # Creates: "[HS] Bestätigt durch / Verified by {user}"
    
    # 3. Show success message
    messages.success(request, "Request verified.")
```

**Result:**

User sees bilingual annotation in inline:
```
Type: System Event
Text: [HS] Bestätigt durch / Verified by Sven Varszegi
Created by: 🤖 SYSTEM
Created at: 08.12.2025 14:30
```

---

### 7.3 AJAX Annotation Workflow

**Adding via AJAX:**

```javascript
// 1. User clicks "Add comment" button
// 2. JavaScript collects form data
const formData = new FormData();
formData.append('content_type_id', contentTypeId);
formData.append('object_id', objectId);
formData.append('text', annotationText);
formData.append('annotation_type', 'USER');

// 3. POST to endpoint
fetch('/annotations/add/', {
    method: 'POST',
    body: formData,
    headers: {
        'X-CSRFToken': csrfToken
    }
})
.then(response => response.json())
.then(data => {
    if (data.success) {
        // 4. Update UI with new annotation
        appendAnnotationToUI(data.annotation_id);
    } else {
        // 5. Show error
        showError(data.message);
    }
});
```

**Deleting via AJAX:**

```javascript
// 1. User clicks "Delete" on annotation
// 2. Confirm dialog
if (confirm('Delete this annotation?')) {
    // 3. POST to delete endpoint
    fetch(`/annotations/delete/${annotationId}/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // 4. Remove from UI
            removeAnnotationFromUI(annotationId);
        } else {
            // 5. Show error
            showError(data.message);
        }
    });
}
```

---

## 8. Integration Points

### 8.1 Usage in Other Modules

**Module Examples:**

```python
# academia/admin.py
from annotations.admin import AnnotationInline
from annotations.views import create_system_annotation

@admin.register(Semester)
class SemesterAdmin(...):
    inlines = [AnnotationInline]
    
    @safe_admin_action
    def lock_semester(self, request, obj):
        record_signature(...)
        create_system_annotation(obj, "LOCK", user=request.user)
```

**All modules that use annotations:**
- `academia` - Semester, InboxRequest
- `academia_audit` - AuditSemester, AuditEntry
- `assembly` - Session, SessionItem
- `employees` - EmploymentContract
- `finances` - FiscalYear, PaymentPlan
- `hankosign` - (potential system events)
- `people` - (potential collaboration)

---

### 8.2 GenericForeignKey Mechanism

**How it works:**

```python
# 1. ContentType identifies the model class
content_type = ContentType.objects.get_for_model(InboxRequest)
# ContentType(app_label='academia', model='inboxrequest')

# 2. object_id stores the specific instance ID
object_id = 123

# 3. GenericForeignKey resolves to actual object
content_object = content_type.get_object_for_this_type(pk=object_id)
# → InboxRequest.objects.get(pk=123)
```

**Benefits:**

- One annotation model works with all models
- No need for model-specific annotation tables
- Centralized annotation management

**Limitations:**

- No database-level foreign key constraint
- If referenced object deleted, annotation remains (orphaned)
- Can't use `select_related()` on generic relations (use `prefetch_related()`)

---

## 9. Gotchas & Important Notes

### 9.1 Saved Annotations are Read-Only

⚠️ **Once saved, annotations cannot be edited via inline**. The form makes fields readonly/disabled for existing annotations.

**Why?** Preserves audit trail - annotations are meant to be immutable records.

**Workaround:** Use standalone AnnotationAdmin to edit (superuser only).

---

### 9.2 SYSTEM Type Restriction

⚠️ **Only superusers can create SYSTEM annotations via inline**.

Non-superusers:
- Don't see SYSTEM in type dropdown
- If they POST annotation_type=SYSTEM, it's downgraded to USER

**Proper way to create SYSTEM annotations:**

```python
# Use create_system_annotation() helper in code
create_system_annotation(obj, "LOCK", user=request.user)
```

---

### 9.3 Permission Model

**Add annotation:**
- Requires `{app}.change_{model}` permission on parent object
- User must be staff
- Parent object must exist

**Delete annotation:**
- Must be creator OR superuser
- Must still have `change` permission on parent model
- Only via inline if superuser

**Why change permission?** Annotations modify the conceptual state of an object (adding comments/notes), so we require change permission, not add.

---

### 9.4 No Cascade on Object Deletion

When a parent object is deleted, its annotations **remain in database** with:
- `content_type` still set
- `object_id` still set
- `content_object` returns `None`

**Cleanup:** Use AnnotationAdmin to find orphaned annotations:

```python
# Annotations where content_object is None
orphans = [a for a in Annotation.objects.all() if not a.content_object]
```

No automatic cleanup mechanism exists.

---

### 9.5 created_by Can Be NULL

`created_by` is nullable for system-generated annotations where no specific user should be credited.

**When NULL:**
- System automated processes
- Background tasks
- Data migrations

**Display:**
```python
created_by_display():
    if obj.created_by:
        return user.get_full_name() or user.username
    return "🤖 SYSTEM"
```

---

### 9.6 ContentType Caching

Django caches ContentType lookups. In tests or management commands, you may need to clear cache:

```python
from django.contrib.contenttypes.models import ContentType
ContentType.objects.clear_cache()
```

---

### 9.7 Bilingual Messages

HankoSign action messages are **bilingual by design** (German / English):

```
[HS] Gesperrt durch / Locked by Sven Varszegi
```

This supports Austria's bilingual requirements. The format is hardcoded in `HankoSignAction.TEMPLATES`.

---

## 10. Testing Strategy

### 10.1 Key Test Scenarios

**Model:**
- [ ] Create annotation for any model via GenericForeignKey
- [ ] GenericForeignKey resolves to correct object
- [ ] is_system property works correctly
- [ ] String representation includes type, user, timestamp
- [ ] Ordering is newest first

**Views - add_annotation:**
- [ ] Creates annotation with valid data
- [ ] Returns 400 for missing fields
- [ ] Returns 404 for non-existent object
- [ ] Returns 403 for insufficient permissions
- [ ] Downgrades SYSTEM to USER for non-superusers
- [ ] Validates annotation_type choices
- [ ] Sets created_by to current user
- [ ] Transaction rollback on error

**Views - delete_annotation:**
- [ ] Creator can delete their annotation
- [ ] Superuser can delete any annotation
- [ ] Non-creator non-superuser cannot delete
- [ ] Returns 403 if user lost change permission
- [ ] Actually deletes annotation from database

**Views - create_system_annotation:**
- [ ] Creates SYSTEM annotation
- [ ] Recognizes HankoSign action constants
- [ ] Generates bilingual text for actions
- [ ] Falls back to custom text for unknown actions
- [ ] Sets created_by to user if provided
- [ ] Sets created_by to NULL if not provided

**HankoSignAction:**
- [ ] get_text() returns formatted string for known actions
- [ ] get_text() returns None for unknown actions
- [ ] Uses user.get_full_name() when available
- [ ] Falls back to "System" when user is None
- [ ] All action constants have templates

**AnnotationInline:**
- [ ] Appears on any model admin when added
- [ ] New annotations editable
- [ ] Saved annotations readonly
- [ ] SYSTEM type hidden from non-superusers
- [ ] created_by auto-set on save
- [ ] Only superusers can delete

**Template Tags:**
- [ ] get_annotations_for returns correct annotations
- [ ] get_annotations_for filters by type
- [ ] get_content_type_id returns correct ContentType ID
- [ ] annotation_count returns correct count

---

### 10.2 Edge Cases

**GenericForeignKey:**
- Annotation attached to deleted object (orphaned)
- Multiple annotations on same object
- Annotations across different content types with same object_id

**Permissions:**
- User has change permission, then loses it (can't add/delete)
- User deletes own annotation after losing change permission
- Superuser vs non-superuser SYSTEM type handling

**Text Content:**
- Very long text (no length limit)
- Empty text (should be rejected)
- HTML/JavaScript in text (should be escaped in display)
- Unicode characters, emojis

**User Handling:**
- User deleted after creating annotation (created_by FK PROTECT)
- Anonymous user attempts to add annotation (should fail at staff check)
- User with partial name (no last name, etc.)

---

### 10.3 Integration Testing

**With Other Modules:**
- [ ] Add annotation to Semester via inline
- [ ] Add annotation to InboxRequest via inline
- [ ] Create system annotation on workflow action
- [ ] Annotations appear in history/audit trail
- [ ] Annotations survive object updates (version changes)

**AJAX Integration:**
- [ ] Frontend AJAX calls work with add endpoint
- [ ] Frontend AJAX calls work with delete endpoint
- [ ] CSRF token validation
- [ ] Error messages displayed properly

---

## 11. Performance Considerations

**Query Optimization:**

```python
# Good - pre-fetch creators
annotations = Annotation.objects.filter(...).select_related('created_by')

# Good - in templatetag
def get_annotations_for(obj, annotation_type=None):
    return Annotation.objects.filter(...).select_related('created_by')

# Admin queryset
def get_queryset(self, request):
    return super().get_queryset(request).select_related('created_by', 'content_type')
```

**Avoiding N+1:**

```django
{# Bad - N+1 queries #}
{% for session in sessions %}
    {{ session|annotation_count }}  {# Query per session #}
{% endfor %}

{# Good - prefetch #}
{% for session in sessions_with_counts %}
    {{ session.annotation_count }}  {# Already annotated in view #}
{% endfor %}
```

**Annotation Counts:**

For list views, annotate counts in queryset:

```python
from django.db.models import Count
qs = qs.annotate(
    annotation_count=Count('annotations')  # If using GenericRelation
)
```

---

## 12. Common Usage Patterns

### 12.1 Adding Inline to Model Admin

```python
from annotations.admin import AnnotationInline

@admin.register(YourModel)
class YourModelAdmin(admin.ModelAdmin):
    inlines = [AnnotationInline]  # That's it!
```

---

### 12.2 Creating System Annotations in Actions

```python
@transaction.atomic
@safe_admin_action
def approve_something(self, request, obj):
    # 1. Business logic
    action = get_action("APPROVE:CHAIR@yourapp.YourModel")
    record_signature(request, action, obj, note="Approved")
    
    # 2. System annotation
    create_system_annotation(obj, "APPROVE", user=request.user)
    
    # 3. User feedback
    messages.success(request, "Approved successfully")
```

---

### 12.3 Custom Annotation in Code

```python
from annotations.views import create_system_annotation

# Custom text (not a workflow action)
create_system_annotation(
    obj,
    f"Bulk update: Modified {count} related records",
    user=request.user
)
```

---

### 12.4 Displaying Annotations in Template

```django
{% load annotation_tags %}

<div class="annotations">
    <h3>Comments ({{ object|annotation_count }})</h3>
    
    {% get_annotations_for object as annotations %}
    {% for annotation in annotations %}
        <div class="annotation {% if annotation.is_system %}system{% endif %}">
            <div class="meta">
                <strong>{{ annotation.created_by_display }}</strong>
                <span class="type">{{ annotation.get_annotation_type_display }}</span>
                <span class="date">{{ annotation.created_at|date:"d.m.Y H:i" }}</span>
            </div>
            <div class="text">{{ annotation.text }}</div>
        </div>
    {% empty %}
        <p>No annotations yet.</p>
    {% endfor %}
</div>
```

---

### 12.5 AJAX Add Form

```html
{% load annotation_tags %}
{% get_content_type_id object as ct_id %}

<form id="annotation-form">
    {% csrf_token %}
    <input type="hidden" name="content_type_id" value="{{ ct_id }}">
    <input type="hidden" name="object_id" value="{{ object.pk }}">
    <textarea name="text" rows="3" required></textarea>
    <select name="annotation_type">
        <option value="USER">Comment</option>
        <option value="INFO">Information</option>
        <option value="CORRECTION">Correction</option>
    </select>
    <button type="submit">Add</button>
</form>

<script>
document.getElementById('annotation-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(e.target);
    
    const response = await fetch('/annotations/add/', {
        method: 'POST',
        body: formData,
        headers: {
            'X-CSRFToken': formData.get('csrfmiddlewaretoken')
        }
    });
    
    const data = await response.json();
    if (data.success) {
        // Reload or update UI
        location.reload();
    } else {
        alert(data.message);
    }
});
</script>
```

---

## 13. File Structure

```
annotations/
├── __init__.py
├── models.py              # Annotation model with GenericForeignKey
├── views.py               # AJAX endpoints + create_system_annotation helper
├── admin.py               # AnnotationInline + AnnotationAdmin
├── utils.py               # HankoSignAction helper
├── urls.py                # add / delete endpoints
├── apps.py
├── tests.py
├── templatetags/
│   ├── __init__.py
│   └── annotation_tags.py # get_annotations_for, get_content_type_id, annotation_count
└── migrations/
    └── 0001_initial.py
```

---

## 14. Common Pitfalls

1. **Editing saved annotations** - They're readonly by design, can't edit via inline
2. **SYSTEM type for non-superusers** - Hidden in dropdown, downgraded if POSTed
3. **Missing change permission** - Can't add annotations without change permission on parent
4. **Orphaned annotations** - No CASCADE on object deletion, manual cleanup needed
5. **N+1 queries** - Always `select_related('created_by')` when fetching annotations
6. **ContentType caching** - May need to clear cache in tests/commands
7. **Permission for deletion** - Only creator or superuser, and must still have change permission
8. **created_by NULL** - System annotations may have NULL created_by
9. **Bilingual format** - HankoSign messages are German/English by design
10. **No add permission** - AnnotationAdmin has add disabled, use inlines instead

---

**Version:** 1.0.5  
**Last Updated:** 2025-12-08  
**Author:** Sven (vas)