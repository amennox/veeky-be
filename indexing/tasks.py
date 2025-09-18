import logging

from django.db import transaction
from django_q.tasks import async_task
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from videos.models import Video

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("indexing.tasks")


def enqueue_video(video_id: int) -> None:
    """Submit the video for asynchronous processing."""
    with tracer.start_as_current_span("indexing.enqueue_video") as span:
        span.set_attribute("video.id", video_id)
        async_task(process_video, video_id)

def process_video(video_id: int) -> None:
    """Placeholder task that updates video status.

    The actual processing pipeline will extract intervals, transcribe audio,
    enrich metadata, and index the content. This stub ensures the queue and
    status flow are operational while the pipeline is being implemented.
    """
    with tracer.start_as_current_span("indexing.process_video") as span:
        span.set_attribute("video.id", video_id)
        try:
            video = Video.objects.get(pk=video_id)
        except Video.DoesNotExist as exc:
            logger.warning("Video %s not found when processing", video_id)
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, "video_not_found"))
            return

        if video.status == Video.Status.PROCESSING:
            span.add_event("already_processing", {"video.status": video.status})
            logger.info("Video %s is already being processed", video_id)
            span.set_status(Status(StatusCode.OK))
            return

        with transaction.atomic():
            previous_status = video.status
            video.status = Video.Status.PROCESSING
            video.save(update_fields=["status", "updated_at"])
        span.add_event(
            "status_updated",
            {"from": previous_status, "to": Video.Status.PROCESSING},
        )

        try:
            logger.info("Processing video %s (stub)", video_id)
            # TODO: implement the real processing workflow.
            with transaction.atomic():
                video.refresh_from_db()
                video.status = Video.Status.COMPLETED
                video.save(update_fields=["status", "updated_at"])
            span.add_event(
                "status_updated",
                {"from": Video.Status.PROCESSING, "to": Video.Status.COMPLETED},
            )
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Processing failed for video %s", video_id)
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            with transaction.atomic():
                video.refresh_from_db()
                video.status = Video.Status.FAILED
                video.save(update_fields=["status", "updated_at"])
            span.add_event(
                "status_updated",
                {"from": Video.Status.PROCESSING, "to": Video.Status.FAILED},
            )

