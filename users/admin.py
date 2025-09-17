from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model

User = get_user_model()

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active", "groups")
    search_fields = ("username", "email")
    filter_horizontal = ("groups", "user_permissions", "categories")  # M2M
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Access control", {"fields": ("role", "categories")}),
    )
