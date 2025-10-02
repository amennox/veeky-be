import json

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django_q.conf import Conf
from django_q.models import OrmQ, Task
from django_q.signing import SignedPackage
from rest_framework import status
from rest_framework.test import APITestCase


class DjangoQTaskAPITestCase(APITestCase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="queue_admin",
            email="queue_admin@example.com",
            password="testpass123",
            role=User.Role.ADMIN,
        )
        self.admin.is_staff = True
        self.admin.is_superuser = True
        self.admin.save(update_fields=["is_staff", "is_superuser"])
        self.client.force_authenticate(user=self.admin)
        self.list_url = reverse("djangoq-task-list")

    def _create_pending_entry(self, task_id: str = "pending-1") -> OrmQ:
        payload = SignedPackage.dumps(
            {
                "id": task_id,
                "name": "Pending Job",
                "func": "app.tasks.sample",
                "args": [],
                "kwargs": {"foo": "bar"},
                "started": timezone.now(),
            }
        )
        return OrmQ.objects.create(key=Conf.PREFIX, payload=payload, lock=None)

    def _create_completed_task(self, task_id: str = "completed-1") -> Task:
        return Task.objects.create(
            id=task_id,
            name="Completed Job",
            func="app.tasks.finished",
            hook="",
            args=json.dumps(["sample"]),
            kwargs=json.dumps({"bar": "baz"}),
            result=json.dumps({"status": "ok"}),
            group="",
            started=timezone.now(),
            stopped=timezone.now(),
            success=True,
            attempt_count=1,
        )

    def test_list_returns_pending_and_completed_tasks(self):
        self._create_pending_entry()
        self._create_completed_task()

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        statuses = {item["status"] for item in response.data}
        self.assertIn("pending", statuses)
        self.assertIn("success", statuses)

    def test_retrieve_pending_task(self):
        pending = self._create_pending_entry("pending-detail")
        detail_url = reverse("djangoq-task-detail", args=["pending-detail"])

        response = self.client.get(detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], "pending-detail")
        self.assertEqual(response.data["status"], "pending")
        self.assertTrue(response.data["cancellable"])
        self.assertEqual(response.data["queue_id"], str(pending.pk))

    def test_cancel_pending_task(self):
        self._create_pending_entry("cancel-me")
        detail_url = reverse("djangoq-task-detail", args=["cancel-me"])

        response = self.client.delete(detail_url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(OrmQ.objects.filter(key=Conf.PREFIX).exists())

    def test_cancel_completed_task_returns_error(self):
        self._create_completed_task("done-task")
        detail_url = reverse("djangoq-task-detail", args=["done-task"])

        response = self.client.delete(detail_url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("annullabile", response.data["detail"])
