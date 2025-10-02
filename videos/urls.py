from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import VideoViewSet, YouTubeMetadataAPIView

router = DefaultRouter()
router.register(r"videos", VideoViewSet, basename="video")

urlpatterns = [
    path("videos/youtubemetadata/", YouTubeMetadataAPIView.as_view(), name="video-youtube-metadata"),
    path("", include(router.urls)),
]
