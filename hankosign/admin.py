from django.contrib import admin

# Register your models here.

from django.utils.translation import gettext_lazy as _

from .models import Action, Policy, Signatory, Signature


class SignatureInline(admin.TabularInline):
    model = Signature
    extra = 0
    can_delete = False
    readonly_fields = ("at", "verb", "stage", "content_type", "object_id", "signature_id", "note")
    fields = ("at", "verb", "stage", "content_type", "object_id", "signature_id", "note")
    ordering = ("-at",)

    def has_add_permission(self, request, obj):
        return False


@admin.register(Action)
class ActionAdmin(admin.ModelAdmin):
    list_display = ("human_label", "verb", "stage", "scope", "action_code", "updated_at")
    list_filter = ("verb", "stage", "scope")
    search_fields = ("human_label",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (_("Definition"), {"fields": ("verb", "stage", "scope", "human_label", "comment")}),
        (_("System"), {"fields": ("created_at", "updated_at")}),
    )


@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
    list_display = ("role", "action", "require_distinct_signer", "is_repeatable", "updated_at")
    list_filter = ("is_repeatable", "require_distinct_signer", "action__verb", "action__stage", "action__scope")
    search_fields = ("role__name", "action__human_label")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("role", "action")
    fieldsets = (
        (_("Grant"), {"fields": ("role", "action", "is_repeatable", "require_distinct_signer")}),
        (_("Notes"), {"fields": ("notes",)}),
        (_("System"), {"fields": ("created_at", "updated_at")}),
    )


@admin.register(Signatory)
class SignatoryAdmin(admin.ModelAdmin):
    list_display = ("display_name", "user_display", "person_role", "is_active", "is_verified", "updated_at")
    list_filter = ("is_active", "is_verified", "person_role__role")
    search_fields = ("person_role__person__last_name", "person_role__person__first_name", "person_role__person__user__username")
    readonly_fields = ("created_at", "updated_at", "base_key", "user_display")
    autocomplete_fields = ("person_role",)
    inlines = [SignatureInline]
    fieldsets = (
        (_("Identity"), {"fields": ("person_role", "user_display", "name_override")}),
        (_("Status"), {"fields": ("is_active", "is_verified", "pdf_specimen")}),
        (_("System"), {"fields": ("base_key", "created_at", "updated_at")}),
    )

    @admin.display(description=_("User"))
    def user_display(self, obj):
        u = obj.user
        return getattr(u, "username", "—")


@admin.register(Signature)
class SignatureAdmin(admin.ModelAdmin):
    # Keep visible but lean; we can hide it from the sidebar if you prefer.
    list_display = ("at", "signatory", "verb", "stage", "content_type", "object_id", "signature_id")
    list_filter = ("verb", "stage", "content_type")
    search_fields = ("signature_id", "object_id", "signatory__name_override", "signatory__person_role__person__last_name")
    readonly_fields = ("signatory", "content_type", "object_id", "action", "verb", "stage", "scope_ct", "at", "note", "payload", "signature_id")
    fieldsets = (
        (_("Target"), {"fields": ("content_type", "object_id")}),
        (_("Action"), {"fields": ("action", "verb", "stage", "scope_ct")}),
        (_("Signer"), {"fields": ("signatory",)}),
        (_("Result"), {"fields": ("signature_id", "at", "note", "payload")}),
    )

    def get_model_perms(self, request):
        # If you want it invisible from the sidebar, uncomment:
        # return {}
        return super().get_model_perms(request)
