from django.contrib.auth import get_user_model
from rest_framework import permissions

User = get_user_model()


class IsAdminOrEditor(permissions.BasePermission):
    """Allow Admins full access and Editors to create videos."""

    message = "Only Admins or Editors can perform this action."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if request.method == "POST":
            return user.role in {User.Role.ADMIN, User.Role.EDITOR}

        if request.method in permissions.SAFE_METHODS:
            return user.role in {User.Role.ADMIN, User.Role.EDITOR}

        return user.role == User.Role.ADMIN

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
