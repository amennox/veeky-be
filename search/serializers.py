from __future__ import annotations

from rest_framework import serializers


class HybridSearchRequestSerializer(serializers.Serializer):
    search_text = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
    )
    search_image = serializers.ImageField(required=False)
    video_category_id = serializers.IntegerField(required=False)
    analyze_image = serializers.BooleanField(
        required=False,
        default=False,
    )

    def validate(self, attrs: dict) -> dict:
        text = attrs.get("search_text", "") or ""
        image = attrs.get("search_image")
        if not text.strip() and image is None:
            raise serializers.ValidationError(
                "Provide at least one of search_text or search_image."
            )
        return attrs


class HybridSearchResultSerializer(serializers.Serializer):
    title = serializers.CharField()
    video_id = serializers.IntegerField()
    chunk_type = serializers.CharField()
    start_seconds = serializers.FloatField(required=False, allow_null=True)
    upload_timestamp = serializers.CharField(required=False, allow_blank=True)
    relevance = serializers.FloatField()
