"""Serializers for exposing Django-Q task information via the API."""

from rest_framework import serializers


class DjangoQTaskSerializer(serializers.Serializer):
    """Shape used to expose queued and completed Django-Q tasks."""

    id = serializers.CharField()
    name = serializers.CharField(allow_blank=True, required=False)
    func = serializers.CharField(allow_blank=True, required=False)
    status = serializers.CharField()
    started = serializers.DateTimeField(allow_null=True, required=False)
    stopped = serializers.DateTimeField(allow_null=True, required=False)
    duration = serializers.FloatField(allow_null=True, required=False)
    success = serializers.BooleanField(allow_null=True, required=False)
    attempt_count = serializers.IntegerField(allow_null=True, required=False)
    hook = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    group = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    args = serializers.JSONField(required=False)
    kwargs = serializers.JSONField(required=False)
    result = serializers.JSONField(allow_null=True, required=False)
    queue_id = serializers.CharField(allow_null=True, required=False)
    cancellable = serializers.BooleanField(default=False)

