from django.db.models.signals import post_migrate
from django.contrib.auth import get_user_model
from django.dispatch import receiver
from django.db import connection

User = get_user_model()

@receiver(post_migrate)
def create_sample_users(sender, **kwargs):
    if sender.name == "users":
        # check if the users_user table exists
        if "users_user" not in connection.introspection.table_names():
            return

        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser(
                username="admin",
                email="admin@example.com",
                password="admin123",
                role=User.Role.ADMIN,
            )
        if not User.objects.filter(username="editor").exists():
            User.objects.create_user(
                username="editor",
                email="editor@example.com",
                password="editor123",
                role=User.Role.EDITOR,
            )
        if not User.objects.filter(username="user").exists():
            User.objects.create_user(
                username="user",
                email="user@example.com",
                password="user123",
                role=User.Role.USER,
            )
