from typing import Any, Dict, List

from django.contrib.auth import get_user_model
from django.db import transaction
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Category, Video, VideoInterval

User = get_user_model()


class CategoryReferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name"]
        read_only_fields = fields


class VideoIntervalSerializer(serializers.ModelSerializer):
    class Meta:
        model = VideoInterval
        fields = ["id", "order", "start_second", "end_second"]
        read_only_fields = ["id"]


class VideoDetailSerializer(serializers.ModelSerializer):
    keywords = serializers.ListField(
        child=serializers.CharField(allow_blank=False),
        required=False,
        allow_empty=True,
    )
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())
    intervals = VideoIntervalSerializer(many=True, required=False)

    class Meta:
        model = Video
        fields = [
            "id",
            "name",
            "description",
            "keywords",
            "category",
            "uploader",
            "source_type",
            "video_file",
            "source_url",
            "status",
            "created_at",
            "updated_at",
            "intervals",
        ]
        read_only_fields = fields


class VideoCreateSerializer(serializers.ModelSerializer):
    keywords = serializers.ListField(
        child=serializers.CharField(allow_blank=False),
        required=False,
        allow_empty=True,
    )
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())
    video_file = serializers.FileField(required=False, allow_null=True, write_only=True)
    intervals = VideoIntervalSerializer(many=True, required=False)

    class Meta:
        model = Video
        fields = [
            "id",
            "name",
            "description",
            "keywords",
            "category",
            "source_type",
            "video_file",
            "source_url",
            "intervals",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "status", "created_at", "updated_at"]
        extra_kwargs = {
            "description": {"required": False, "allow_blank": True},
            "source_url": {"required": False, "allow_blank": True},
        }

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        category = attrs.get("category")
        source_type = attrs.get("source_type")
        video_file = attrs.get("video_file")
        source_url = attrs.get("source_url")
        if source_type is None:
            raise serializers.ValidationError("Specify the video source type.")

        if isinstance(source_url, str) and not source_url.strip():
            source_url = ""
            attrs["source_url"] = ""

        if user is None or not user.is_authenticated:
            raise serializers.ValidationError("Authentication required to upload videos.")

        if user.role == User.Role.ADMIN:
            pass
        elif user.role == User.Role.EDITOR:
            if category and not user.categories.filter(pk=category.pk).exists():
                raise serializers.ValidationError(
                    "Editors can only upload videos for their assigned categories."
                )
        else:
            raise serializers.ValidationError("Only Admins or Editors can upload videos.")

        has_file = bool(video_file)
        has_url = bool(source_url)

        if has_file == has_url:
            raise serializers.ValidationError(
                "Provide exactly one source: either upload a file or supply a source URL."
            )

        if source_type == Video.SourceType.UPLOAD and not has_file:
            raise serializers.ValidationError("Uploaded videos must include a file.")

        if source_type == Video.SourceType.YOUTUBE and not has_url:
            raise serializers.ValidationError("YouTube videos must include a source URL.")

        return attrs

    def create(self, validated_data: Dict[str, Any]) -> Video:
        intervals_data: List[Dict[str, Any]] = validated_data.pop("intervals", [])

        with transaction.atomic():
            video = Video.objects.create(**validated_data)

            if intervals_data:
                VideoInterval.objects.bulk_create(
                    [
                        VideoInterval(video=video, **interval)
                        for interval in intervals_data
                    ]
                )

        return video