from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = "Category"
        verbose_name_plural = "Categories"

    def __str__(self) -> str:
        return self.name


def video_upload_path(instance: "Video", filename: str) -> str:
    """Return the storage path for uploaded videos."""
    return f"videos/{instance.uploader_id}/{filename}"

def validate_video_file(file):
    if file.size > 1024 * 1024 * 500:  # 500 MB
        raise ValidationError(
            _('Video file size cannot exceed 500 MB')
        )
    
    allowed_types = ['video/mp4', 'video/mpeg', 'video/quicktime']
    if file.content_type not in allowed_types:
        raise ValidationError(
            _('Unsupported file format. Please use MP4, MPEG or MOV')
        )

video_file = models.FileField(
    upload_to=video_upload_path,
    validators=[validate_video_file],
    blank=True, 
    null=True,
    help_text=_("Upload MP4, MPEG or MOV video files up to 500 MB")
)


class Video(models.Model):
    class SourceType(models.TextChoices):
        UPLOAD = "UPLOAD", "Upload"
        YOUTUBE = "YOUTUBE", "YouTube"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    keywords = models.JSONField(default=list, blank=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="videos",
    )
    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_videos",
    )
    source_type = models.CharField(max_length=10, choices=SourceType.choices)
    video_file = models.FileField(upload_to=video_upload_path, blank=True, null=True)
    source_url = models.URLField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_status_display()})"

    def clean(self) -> None:
        super().clean()
        has_file = bool(self.video_file)
        has_url = bool(self.source_url)

        if has_file == has_url:
            raise ValidationError("Provide either a video file or a source URL, not both.")

        if self.source_type == self.SourceType.UPLOAD and not has_file:
            raise ValidationError("Uploaded videos must include a file.")

        if self.source_type == self.SourceType.YOUTUBE and not has_url:
            raise ValidationError("YouTube videos must include a source URL.")

    def save(self, *args, **kwargs):  # type: ignore[override]
        self.full_clean()
        return super().save(*args, **kwargs)


class VideoInterval(models.Model):
    video = models.ForeignKey(
        Video,
        on_delete=models.CASCADE,
        related_name="intervals",
    )
    order = models.PositiveIntegerField(default=0)
    start_second = models.PositiveIntegerField()
    end_second = models.PositiveIntegerField()

    class Meta:
        ordering = ["order", "start_second"]

    def __str__(self) -> str:
        return f"{self.video_id}: {self.start_second}-{self.end_second}"

    def clean(self) -> None:
        super().clean()
        if self.end_second <= self.start_second:
            raise ValidationError("Interval end must be greater than the start.")

    def save(self, *args, **kwargs):  # type: ignore[override]
        self.full_clean()
        return super().save(*args, **kwargs)
