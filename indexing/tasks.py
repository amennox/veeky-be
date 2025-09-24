"""Video indexing pipeline tasks."""
from __future__ import annotations

import logging
import os
import re
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.db import transaction

from django_q.tasks import async_task
from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

from videos.models import Video

from .ollama_client import OllamaClient
from .opensearch_client import get_client, index_documents
from .utils import (
    Keyframe,
    MissingDependencyError,
    VideoSegment,
    build_keyframe_directory,
    chunk_text,
    fetch_prompt,
    require_dependency,
    safe_rmtree,
    safe_unlink,
    timestamp_to_filename,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("indexing.tasks")

DEFAULT_INDEX_NAME = os.getenv("OPENSEARCH_INDEX", "videos")
DEFAULT_KEYFRAME_INTERVAL = float(os.getenv("VIDEO_INDEX_KEYFRAME_INTERVAL", "4.0"))
DEFAULT_SSIM_THRESHOLD = float(os.getenv("VIDEO_INDEX_SSIM_THRESHOLD", "0.90"))
DEFAULT_MIN_SEGMENT = float(os.getenv("VIDEO_INDEX_MIN_SEGMENT", "8.0"))
DEFAULT_MAX_SEGMENT = float(os.getenv("VIDEO_INDEX_MAX_SEGMENT", "75.0"))
DEFAULT_SILENCE_NOISE = os.getenv("VIDEO_INDEX_SILENCE_NOISE", "-35dB")
DEFAULT_SILENCE_DURATION = float(os.getenv("VIDEO_INDEX_SILENCE_DURATION", "1.5"))
DEFAULT_WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")

_WHISPER_MODEL: Optional[Any] = None

__all__ = ("enqueue_video", "process_video")


def _processing_root() -> Path:
    tmp_upload = Path(getattr(settings, "TMP_UPLOAD_DIR", Path(settings.BASE_DIR) / "tmp" / "uploads"))
    return tmp_upload.parent / "processing"


def _relative_media_path(path: Path) -> str:
    media_root = Path(getattr(settings, "MEDIA_ROOT", ""))
    try:
        relative = path.relative_to(media_root)
    except ValueError:
        return str(path).replace("\\", "/")
    return str(relative).replace("\\", "/")


def _get_whisper_model():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        whisper_module = require_dependency(
            "whisper",
            "Install openai-whisper to enable automatic transcription.",
        )
        _WHISPER_MODEL = whisper_module.load_model(DEFAULT_WHISPER_MODEL)
    return _WHISPER_MODEL


def _acquire_video(video: Video, cleanup_files: List[Path], span: Span) -> Path:
    if video.source_type == Video.SourceType.UPLOAD:
        if not video.video_file:
            raise FileNotFoundError("Uploaded video has no associated file.")
        path = Path(video.video_file.path)
        if not path.exists():
            raise FileNotFoundError(path)
        span.add_event("video_file_resolved", {"path": str(path)})
        return path

    if not video.source_url:
        raise ValueError("YouTube videos require a source URL.")

    yt_dlp_module = require_dependency(
        "yt_dlp",
        "Install yt-dlp to download videos from YouTube.",
    )
    download_root = Path(getattr(settings, "TMP_DOWNLOAD_DIR", Path(settings.BASE_DIR) / "tmp" / "downloads"))
    download_root.mkdir(parents=True, exist_ok=True)
    filename_template = download_root / f"video_{video.id}_%(id)s.%(ext)s"

    ydl_options = {
        "outtmpl": str(filename_template),
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp_module.YoutubeDL(ydl_options) as ydl:
        info = ydl.extract_info(video.source_url, download=True)
        downloaded_path = Path(ydl.prepare_filename(info))

    cleanup_files.append(downloaded_path)
    description = info.get("description")
    if description and not video.description:
        video.description = description
        video.save(update_fields=["description", "updated_at"])
        span.add_event("video_description_updated")

    span.add_event("video_downloaded", {"path": str(downloaded_path)})
    return downloaded_path


def _probe_duration(video_path: Path) -> float:
    try:
        ffmpeg_module = require_dependency(
            "ffmpeg",
            "Install ffmpeg-python to probe video metadata.",
        )
    except MissingDependencyError:
        return 0.0

    try:
        data = ffmpeg_module.probe(str(video_path))
    except Exception as exc:  # pragma: no cover - best effort diagnostics
        logger.debug("ffmpeg probe failed for %s: %s", video_path, exc)
        return 0.0

    try:
        return float(data.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _extract_keyframes(
    video: Video,
    video_path: Path,
    keyframe_dir: Path,
    span: Span,
) -> tuple[List[Keyframe], float]:
    cv2 = require_dependency(
        "cv2",
        "Install opencv-python to extract keyframes.",
    )
    skimage_metrics = require_dependency(
        "skimage.metrics",
        "Install scikit-image to compare video frames.",
    )
    structural_similarity = getattr(skimage_metrics, "structural_similarity", None)
    if structural_similarity is None:
        raise MissingDependencyError("skimage.metrics.structural_similarity")

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open video stream: {video_path}")

    interval = max(0.5, DEFAULT_KEYFRAME_INTERVAL)
    threshold = min(max(DEFAULT_SSIM_THRESHOLD, 0.0), 1.0)

    keyframes: List[Keyframe] = []
    previous_gray = None
    next_capture = 0.0
    duration = 0.0

    while True:
        success, frame = capture.read()
        if not success:
            break

        timestamp_ms = capture.get(cv2.CAP_PROP_POS_MSEC)
        timestamp = max(0.0, timestamp_ms / 1000.0)
        duration = max(duration, timestamp)

        if keyframes and timestamp < next_capture:
            continue

        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if previous_gray is not None:
            score = structural_similarity(previous_gray, gray_frame)
            if score >= threshold:
                continue

        file_name = timestamp_to_filename(timestamp)
        file_path = keyframe_dir / file_name
        cv2.imwrite(str(file_path), frame)
        keyframes.append(Keyframe(timestamp=timestamp, path=file_path))
        previous_gray = gray_frame
        next_capture = timestamp + interval

    capture.release()

    if not keyframes:
        capture = cv2.VideoCapture(str(video_path))
        success, frame = capture.read()
        if success:
            fallback = keyframe_dir / timestamp_to_filename(0.0)
            cv2.imwrite(str(fallback), frame)
            keyframes.append(Keyframe(timestamp=0.0, path=fallback))
        capture.release()

    if duration <= 0.0:
        duration = _probe_duration(video_path)

    span.add_event("keyframes_extracted", {"count": len(keyframes), "duration": duration})
    return keyframes, duration


def _detect_silence_boundaries(video_path: Path) -> List[float]:
    try:
        ffmpeg_module = require_dependency(
            "ffmpeg",
            "Install ffmpeg-python to analyse audio.",
        )
    except MissingDependencyError:
        return []

    try:
        process = (
            ffmpeg_module
            .input(str(video_path))
            .output(
                "pipe:",
                format="null",
                af=f"silencedetect=noise={DEFAULT_SILENCE_NOISE}:d={DEFAULT_SILENCE_DURATION}",
            )
        )
        _, stderr = process.run(capture_stdout=True, capture_stderr=True)
    except FileNotFoundError:
        logger.warning("ffmpeg binary not found while detecting silence.")
        return []
    except Exception as exc:  # pragma: no cover - diagnostic
        logger.debug("Silence detection failed: %s", exc)
        return []

    boundaries: List[float] = []
    text = stderr.decode("utf-8", errors="ignore")
    pattern = re.compile(r"silence_(?:start|end):\s*(?P<value>[0-9.]+)")
    for match in pattern.finditer(text):
        value = match.group("value")
        try:
            boundaries.append(float(value))
        except ValueError:
            continue

    return boundaries


def _determine_segments(
    video: Video,
    duration: float,
    keyframes: List[Keyframe],
    video_path: Path,
    span: Span,
) -> List[VideoSegment]:
    manual_intervals = list(video.intervals.all())
    if manual_intervals:
        segments = [
            VideoSegment(
                start=float(interval.start_second),
                end=float(interval.end_second),
            )
            for interval in manual_intervals
        ]
        span.add_event("segments_loaded_from_db", {"count": len(segments)})
        return segments

    boundaries = {0.0}
    if duration:
        boundaries.add(duration)
    boundaries.update(max(0.0, keyframe.timestamp) for keyframe in keyframes)

    silence_boundaries = _detect_silence_boundaries(video_path)
    boundaries.update(silence_boundaries)

    sorted_bounds = sorted(boundaries)
    segments: List[VideoSegment] = []
    if not sorted_bounds:
        return segments

    start = sorted_bounds[0]
    for boundary in sorted_bounds[1:]:
        end = min(boundary, duration) if duration else boundary
        if end <= start:
            continue

        while DEFAULT_MAX_SEGMENT and end - start > DEFAULT_MAX_SEGMENT:
            # Split overly long segments to respect the configured maximum duration.
            split_end = start + DEFAULT_MAX_SEGMENT
            segments.append(VideoSegment(start=start, end=split_end))
            start = split_end

        if end - start >= DEFAULT_MIN_SEGMENT or boundary == sorted_bounds[-1]:
            segments.append(VideoSegment(start=start, end=end))
            start = end

    if not segments and duration:
        segments.append(VideoSegment(start=0.0, end=duration))

    span.add_event("segments_generated", {"count": len(segments)})
    return segments


def _extract_audio_clip(
    ffmpeg_module: Any,
    video_path: Path,
    segment: VideoSegment,
    destination: Path,
) -> None:
    stream = (
        ffmpeg_module
        .input(str(video_path), ss=max(segment.start, 0.0), t=max(segment.duration, 0.5))
        .output(str(destination), format="wav", ac=1, ar="16000")
        .overwrite_output()
    )
    stream.run(capture_stdout=True, capture_stderr=True)


def _transcribe_audio(audio_path: Path) -> str:
    model = _get_whisper_model()
    result = model.transcribe(str(audio_path))
    text = result.get("text", "")
    return text.strip()


def _process_segments(
    video: Video,
    segments: List[VideoSegment],
    video_path: Path,
    ollama: OllamaClient,
    span: Span,
) -> List[Dict[str, Any]]:
    if not segments:
        return []

    ffmpeg_module = require_dependency(
        "ffmpeg",
        "Install ffmpeg-python to extract audio segments.",
    )
    actions: List[Dict[str, Any]] = []
    audio_root = _processing_root() / f"video_{video.id}"
    audio_root.mkdir(parents=True, exist_ok=True)

    category_name = video.category.name if video.category_id else "general"
    cleanup_prompt = fetch_prompt("transcript_cleanup", category_name)

    try:
        for index, segment in enumerate(segments):
            audio_path = audio_root / f"segment_{int(segment.start * 1000)}_{int(segment.end * 1000)}.wav"
            try:
                _extract_audio_clip(ffmpeg_module, video_path, segment, audio_path)
            except Exception as exc:
                logger.warning("Failed to extract audio for segment %s: %s", index, exc)
                continue

            try:
                segment.raw_transcription = _transcribe_audio(audio_path)
            except Exception as exc:
                logger.warning("Whisper transcription failed for segment %s: %s", index, exc)
                continue
            finally:
                safe_unlink(audio_path)

            if not segment.raw_transcription:
                continue

            try:
                refined = ollama.refine_text(segment.raw_transcription, cleanup_prompt)
            except Exception as exc:
                logger.warning("Text refinement failed for segment %s: %s", index, exc)
                refined = segment.raw_transcription

            segment.corrected_transcription = refined or segment.raw_transcription
            chunks = chunk_text(segment.corrected_transcription)
            if not chunks:
                continue

            # Each refined chunk becomes an independently searchable document.
            for chunk_index, chunk in enumerate(chunks):
                try:
                    embedding = list(ollama.embed_text(chunk))
                except Exception as exc:
                    logger.warning("Text embedding failed for segment %s chunk %s: %s", index, chunk_index, exc)
                    continue

                doc_id = f"{video.id}-segment-{index}-{chunk_index}"
                actions.append(
                    {
                        "_op_type": "index",
                        "_index": DEFAULT_INDEX_NAME,
                        "_id": doc_id,
                        "_routing": str(video.id),
                        "video_id": video.id,
                        "chunk_type": "text_segment",
                        "start_seconds": float(segment.start),
                        "end_seconds": float(segment.end),
                        "text_content": chunk,
                        "text_embedding": embedding,
                        "keyframe_path": "",
                        "image_embedding": None,
                        "relation_type": {"name": "content_chunk", "parent": str(video.id)},
                    }
                )
    finally:
        safe_rmtree(audio_root)

    span.add_event("segments_processed", {"chunk_documents": len(actions)})
    return actions


def _build_keyframe_documents(
    video: Video,
    keyframes: List[Keyframe],
    ollama: OllamaClient,
    span: Span,
) -> List[Dict[str, Any]]:
    if not keyframes:
        return []

    category_name = video.category.name if video.category_id else "general"
    description_prompt = fetch_prompt("keyframe_description", category_name)
    docs: List[Dict[str, Any]] = []

    for index, keyframe in enumerate(keyframes):
        try:
            keyframe.description = ollama.describe_image(keyframe.path, description_prompt)
        except Exception as exc:
            logger.warning("Failed to describe keyframe %s: %s", keyframe.path, exc)
            keyframe.description = ""

        try:
            keyframe.embedding = list(ollama.embed_image(keyframe.path))
        except Exception as exc:
            logger.warning("Image embedding failed for %s: %s", keyframe.path, exc)
            keyframe.embedding = []

        text_embedding: List[float] = []
        if keyframe.description:
            try:
                text_embedding = list(ollama.embed_text(keyframe.description))
            except Exception as exc:
                logger.warning("Text embedding for keyframe description failed: %s", exc)

        # Combine visual embedding with a textual description for richer search.
        doc_id = f"{video.id}-keyframe-{int(keyframe.timestamp * 1000)}"
        docs.append(
            {
                "_op_type": "index",
                "_index": DEFAULT_INDEX_NAME,
                "_id": doc_id,
                "_routing": str(video.id),
                "video_id": video.id,
                "chunk_type": "keyframe",
                "start_seconds": float(keyframe.timestamp),
                "end_seconds": float(keyframe.timestamp),
                "text_content": keyframe.description or "",
                "text_embedding": text_embedding,
                "keyframe_path": _relative_media_path(keyframe.path),
                "image_embedding": keyframe.embedding,
                "relation_type": {"name": "content_chunk", "parent": str(video.id)},
            }
        )

    span.add_event("keyframe_documents_ready", {"count": len(docs)})
    return docs


def _build_parent_document(video: Video, duration: float) -> Dict[str, Any]:
    if video.source_type == Video.SourceType.UPLOAD and video.video_file:
        try:
            source_url = video.video_file.url
        except ValueError:
            source_url = video.video_file.name
    else:
        source_url = video.source_url or ""

    category_name = video.category.name if video.category_id else ""

    return {
        "_op_type": "index",
        "_index": DEFAULT_INDEX_NAME,
        "_id": str(video.id),
        "_routing": str(video.id),
        "video_id": video.id,
        "title": video.name,
        "description": video.description,
        "source_url": source_url,
        "category_id": video.category_id,
        "category_name": category_name,
        "upload_timestamp": video.created_at.isoformat(),
        "duration_seconds": duration,
        "relation_type": "video",
    }


def _execute_pipeline(video: Video, span: Span) -> None:
    cleanup_files: List[Path] = []
    keyframe_dir = build_keyframe_directory(video.id, video.category.name if video.category_id else "general")

    try:
        video_path = _acquire_video(video, cleanup_files, span)
        ollama_client = OllamaClient()

        keyframes, duration = _extract_keyframes(video, video_path, keyframe_dir, span)
        segments = _determine_segments(video, duration, keyframes, video_path, span)

        keyframe_docs = _build_keyframe_documents(video, keyframes, ollama_client, span)
        text_docs = _process_segments(video, segments, video_path, ollama_client, span)
        parent_doc = _build_parent_document(video, duration)

        actions: List[Dict[str, Any]] = [parent_doc]
        actions.extend(keyframe_docs)
        actions.extend(text_docs)

        if actions:
            client = get_client()
            refresh_mode = "wait_for" if settings.DEBUG else None
            index_documents(client, actions, refresh=refresh_mode)
            span.add_event(
                "opensearch_indexed",
                {"parent": parent_doc["_id"], "children": len(actions) - 1},
            )
    finally:
        for path in cleanup_files:
            safe_unlink(path)


def enqueue_video(video_id: int) -> None:
    """Submit the video for asynchronous processing."""
    with tracer.start_as_current_span("indexing.enqueue_video") as span:
        span.set_attribute("video.id", video_id)
        async_task(process_video, video_id)


def process_video(video_id: int) -> None:
    """Full video indexing pipeline task."""
    with tracer.start_as_current_span("indexing.process_video") as span:
        span.set_attribute("video.id", video_id)
        try:
            video = Video.objects.select_related("category").get(pk=video_id)
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
            _execute_pipeline(video, span)
        except MissingDependencyError as exc:
            logger.error("Missing dependency while processing video %s: %s", video_id, exc)
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
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Processing failed for video %s", video_id)
            span.record_exception(exc)
            span.set_attribute(
                "error.stacktrace",
                "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            )
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            with transaction.atomic():
                video.refresh_from_db()
                video.status = Video.Status.FAILED
                video.save(update_fields=["status", "updated_at"])
            span.add_event(
                "status_updated",
                {"from": Video.Status.PROCESSING, "to": Video.Status.FAILED},
            )
        else:
            with transaction.atomic():
                video.refresh_from_db()
                video.status = Video.Status.COMPLETED
                video.save(update_fields=["status", "updated_at"])
            span.add_event(
                "status_updated",
                {"from": Video.Status.PROCESSING, "to": Video.Status.COMPLETED},
            )
            span.set_status(Status(StatusCode.OK))
