import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from indexing import tasks as indexing_tasks
from videos.models import Category, Video
from core.telemetry import JsonFileSpanExporter

User = get_user_model()


class VideoCreateAPITestCase(APITestCase):
    def setUp(self):
        super().setUp()
        self.temp_media = tempfile.mkdtemp()
        media_override = override_settings(MEDIA_ROOT=self.temp_media)
        media_override.enable()
        self.addCleanup(media_override.disable)
        self.addCleanup(lambda: shutil.rmtree(self.temp_media, ignore_errors=True))

        self.user = User.objects.create_user(
            username="test_admin",
            email="test_admin@example.com",
            password="testpass123",
            role=User.Role.ADMIN,
        )
        self.category = Category.objects.create(name="Tutorials")
        self.client.force_authenticate(user=self.user)
        self.url = reverse("video-list")

    @patch("indexing.tasks.async_task")
    def test_admin_can_upload_video_file(self, mock_async_task):
        upload = SimpleUploadedFile(
            "demo_ut.mp4",
            b"\x00\x00\x00\x18ftypmp42testvideo",
            content_type="video/mp4",
        )

        response = self.client.post(
            self.url,
            data={
                "name": "Demo video ut",
                "category": self.category.id,
                "source_type": Video.SourceType.UPLOAD,
                "video_file": upload,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Video.objects.count(), 1)
        video = Video.objects.get()
        self.assertEqual(video.uploader, self.user)
        self.assertEqual(video.source_type, Video.SourceType.UPLOAD)
        self.assertTrue(video.video_file.name)

        stored_path = Path(settings.MEDIA_ROOT, video.video_file.name)
        self.assertTrue(stored_path.exists(), msg=f"Stored file not found: {stored_path}")

        mock_async_task.assert_called_once_with(indexing_tasks.process_video, video.id)
        self.assertEqual(response.data["id"], video.id)
        self.assertIn("/media/videos/", response.data["video_file"])


    @patch("indexing.tasks.async_task")
    def test_upload_records_telemetry_span(self, mock_async_task):
        exporter = JsonFileSpanExporter()
        telemetry_path = exporter.path
        initial_content = ""
        if telemetry_path.exists():
            initial_content = telemetry_path.read_text(encoding="utf-8")

        self.addCleanup(lambda: telemetry_path.write_text(initial_content, encoding="utf-8"))

        upload = SimpleUploadedFile(
            "demo.mp4",
            b"\x00\x00\x00\x18ftypmp42testvideo",
            content_type="video/mp4",
        )

        response = self.client.post(
            self.url,
            data={
                "name": "Telemetry video",
                "category": self.category.id,
                "source_type": Video.SourceType.UPLOAD,
                "video_file": upload,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        updated_content = telemetry_path.read_text(encoding="utf-8")
        initial_lines = initial_content.splitlines()
        updated_lines = updated_content.splitlines()
        self.assertGreater(len(updated_lines), len(initial_lines))

        new_entries = [json.loads(line) for line in updated_lines[len(initial_lines):] if line.strip()]
        self.assertTrue(new_entries, "No telemetry spans captured for video upload")

        create_span = next((entry for entry in reversed(new_entries) if entry.get("name") == "videos.create"), None)
        self.assertIsNotNone(create_span, "videos.create span missing from telemetry log")
        self.assertEqual(create_span["attributes"].get("http.status_code"), 201)
        self.assertEqual(create_span["attributes"].get("video.id"), response.data["id"])




