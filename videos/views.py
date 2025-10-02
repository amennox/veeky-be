from django.contrib.auth import get_user_model
from rest_framework import mixins, status, viewsets
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.views import APIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, extend_schema_view
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from indexing.tasks import enqueue_video
from .models import Video
from .permissions import IsAdminOrEditor
from .serializers import (
    VideoCreateSerializer,
    VideoDetailSerializer,
    VideoUpdateSerializer,
    YouTubeMetadataRequestSerializer,
    YouTubeMetadataResponseSerializer,
)
from .services import YouTubeMetadataError, fetch_youtube_metadata

User = get_user_model()
tracer = trace.get_tracer("videos.views")


@extend_schema_view(
    list=extend_schema(
        tags=["Videos"],
        summary="List videos",
        description="List videos accessible to the authenticated Admin or Editor.",
        responses={200: VideoDetailSerializer(many=True)},
    ),
    retrieve=extend_schema(
        tags=["Videos"],
        summary="Retrieve video",
        description="Fetch a single video with metadata and configured intervals.",
        responses={200: VideoDetailSerializer},
    ),
    create=extend_schema(
        tags=["Videos"],
        summary="Create video",
        description="Upload a video file or register a YouTube source for indexing.",
        request=VideoCreateSerializer,
        responses={201: VideoDetailSerializer},
    ),
    update=extend_schema(
        tags=["Videos"],
        summary="Update video",
        description="Replace the editable metadata of a video (name, description, keywords, category).",
        request=VideoUpdateSerializer,
        responses={200: VideoDetailSerializer},
    ),
    partial_update=extend_schema(
        tags=["Videos"],
        summary="Patch video",
        description="Aggiorna parzialmente un video modificando solo nome, descrizione, keywords o categoria.",
        request=VideoUpdateSerializer,
        responses={200: VideoDetailSerializer},
    ),
    destroy=extend_schema(
        tags=["Videos"],
        summary="Delete video",
        description="Rimuove definitivamente un video e le sue risorse indicizzate.",
        responses={204: None},
    ),
)
class VideoViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Video.objects.select_related("category", "uploader").prefetch_related("intervals")
    permission_classes = [IsAdminOrEditor]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def create(self, request, *args, **kwargs):  # type: ignore[override]
        with tracer.start_as_current_span("videos.create") as span:
            user = request.user
            if user and user.is_authenticated:
                span.set_attribute("user.id", user.pk)
                span.set_attribute("user.role", user.role)
            span.set_attribute("videos.source_type", request.data.get("source_type", ""))
            span.set_attribute("videos.has_file", bool(request.data.get("video_file")))
            created_video = None
            try:
                response = super().create(request, *args, **kwargs)
                created_video = getattr(self, "_created_video", None)
                if response.status_code == status.HTTP_201_CREATED and created_video is not None:
                    detail_serializer = VideoDetailSerializer(
                        created_video,
                        context=self.get_serializer_context(),
                    )
                    response.data = detail_serializer.data
                span.set_attribute("http.status_code", response.status_code)
                if isinstance(getattr(response, "data", None), dict):
                    video_id = response.data.get("id")
                    if video_id is not None:
                        span.set_attribute("video.id", video_id)
                span.set_status(Status(StatusCode.OK))
                return response
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise
            finally:
                if hasattr(self, "_created_video"):
                    delattr(self, "_created_video")

    def get_queryset(self):  # type: ignore[override]
        queryset = super().get_queryset()
        user = self.request.user

        if not user.is_authenticated:
            return queryset.none()

        if user.role == User.Role.ADMIN:
            return queryset

        if user.role == User.Role.EDITOR:
            return queryset.filter(category__in=user.categories.all())

        return queryset.none()

    def get_serializer_class(self):  # type: ignore[override]
        if self.action in {"list", "retrieve"}:
            return VideoDetailSerializer
        if self.action == "create":
            return VideoCreateSerializer
        if self.action in {"update", "partial_update"}:
            return VideoUpdateSerializer
        return VideoDetailSerializer

    def perform_create(self, serializer):  # type: ignore[override]
        with tracer.start_as_current_span("videos.perform_create") as span:
            validated = getattr(serializer, "validated_data", {})
            span.set_attribute("video.source_type", validated.get("source_type", ""))
            span.set_attribute("video.keyword_count", len(validated.get("keywords", []) or []))
            span.set_attribute("video.interval_count", len(validated.get("intervals", []) or []))
            video = serializer.save(uploader=self.request.user)
            self._created_video = video
            span.set_attribute("video.id", video.pk)
            span.add_event(
                "queued_for_processing",
                {"video.id": str(video.pk)}
            )
        enqueue_video(video.id)

    def update(self, request, *args, **kwargs):  # type: ignore[override]
        with tracer.start_as_current_span("videos.update") as span:
            span.set_attribute("video.id", kwargs.get("pk"))
            response = super().update(request, *args, **kwargs)
            response.data = VideoDetailSerializer(
                self.get_object(), context=self.get_serializer_context()
            ).data
            span.set_attribute("http.status_code", response.status_code)
            return response

    def partial_update(self, request, *args, **kwargs):  # type: ignore[override]
        allowed_fields = {"name", "description", "keywords", "category"}
        disallowed = {key for key in request.data.keys() if key not in allowed_fields}
        if disallowed:
            return Response(
                {
                    "detail": (
                        "I campi consentiti per PATCH sono: name, description, keywords, category."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        with tracer.start_as_current_span("videos.partial_update") as span:
            span.set_attribute("video.id", kwargs.get("pk"))
            response = super().partial_update(request, *args, **kwargs)
            response.data = VideoDetailSerializer(
                self.get_object(), context=self.get_serializer_context()
            ).data
            span.set_attribute("http.status_code", response.status_code)
            return response

    def destroy(self, request, *args, **kwargs):  # type: ignore[override]
        with tracer.start_as_current_span("videos.destroy") as span:
            span.set_attribute("video.id", kwargs.get("pk"))
            response = super().destroy(request, *args, **kwargs)
            span.set_attribute("http.status_code", response.status_code)
            return response


@extend_schema(
    tags=["Videos"],
    summary="Fetch YouTube metadata",
    description="Restituisce i metadati disponibili per un video YouTube senza scaricare il contenuto.",
    request=YouTubeMetadataRequestSerializer,
    responses={200: YouTubeMetadataResponseSerializer},
)
class YouTubeMetadataAPIView(APIView):
    permission_classes = [IsAdminOrEditor]
    parser_classes = [JSONParser]

    def post(self, request, *args, **kwargs):
        serializer = YouTubeMetadataRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        url = serializer.validated_data["url"]

        with tracer.start_as_current_span("videos.youtube_metadata") as span:
            span.set_attribute("youtube.url", url)
            try:
                metadata = fetch_youtube_metadata(url)
            except YouTubeMetadataError as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                return Response({"detail": str(exc)}, status=exc.status_code)
            span.set_status(Status(StatusCode.OK))

        response_serializer = YouTubeMetadataResponseSerializer(metadata)
        return Response(response_serializer.data)
