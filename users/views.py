from rest_framework import viewsets, permissions
from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema, OpenApiParameter
from .serializers import UserSerializer, CategorySerializer
from videos.models import Category

User = get_user_model()


@extend_schema(
    tags=["Categories"],
    summary="Manage video categories",
    description="API endpoints to create, list, update, and delete categories. "
                "Categories can be assigned to users and used for content classification."
)
class CategoryViewSet(viewsets.ModelViewSet):
    """
    Category API endpoint.

    Provides CRUD operations for video categories.
    Only Admin users are allowed to manage categories.
    """
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAdminUser]


@extend_schema(
    tags=["Users"],
    summary="Manage system users",
    description="API endpoints to create, list, update, and delete users. "
                "Each user has a role (Admin, Editor, User) and may be linked "
                "to one or more categories."
)
class UserViewSet(viewsets.ModelViewSet):
    """
    User API endpoint.

    Provides CRUD operations for system users.
    Each user has a role and can be assigned to categories.
    Only Admin users are allowed to manage users.
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAdminUser]

    @extend_schema(
        summary="List users",
        description="Retrieve a list of all users with their role and assigned categories.",
        responses={200: UserSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Create user",
        description="Create a new user (Admin, Editor, or User) and assign categories.",
        responses={201: UserSerializer},
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(
        summary="Retrieve user",
        description="Get details of a specific user by ID, including role and categories.",
        responses={200: UserSerializer},
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        summary="Update user",
        description="Update an existing user, including role and categories.",
        responses={200: UserSerializer},
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(
        summary="Delete user",
        description="Delete a user by ID. This action is permanent.",
        responses={204: None},
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
