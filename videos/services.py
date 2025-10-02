"""Utility helpers for working with external video services."""

from __future__ import annotations

import json
from typing import Any, Dict

from rest_framework import status

from indexing.utils import MissingDependencyError, require_dependency


class YouTubeMetadataError(Exception):
    """Raised when fetching YouTube metadata fails."""

    def __init__(self, message: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
        super().__init__(message)
        self.status_code = status_code


def fetch_youtube_metadata(url: str) -> Dict[str, Any]:
    """Return metadata for a YouTube video without downloading it."""

    try:
        yt_dlp = require_dependency(
            "yt_dlp",
            "Installa il pacchetto 'yt-dlp' per recuperare i metadati YouTube.",
        )
    except MissingDependencyError as exc:
        raise YouTubeMetadataError(str(exc)) from exc

    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "force_generic_extractor": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:  # type: ignore[attr-defined]
        raise YouTubeMetadataError(str(exc), status.HTTP_400_BAD_REQUEST) from exc
    except Exception as exc:
        raise YouTubeMetadataError(f"Errore durante l'estrazione dei metadati: {exc}") from exc

    metadata = {
        "original_url": url,
        "webpage_url": info_dict.get("webpage_url"),
        "title": info_dict.get("title"),
        "description": info_dict.get("description"),
        "author": info_dict.get("uploader"),
        "channel_id": info_dict.get("channel_id"),
        "channel_url": info_dict.get("uploader_url"),
        "duration_seconds": info_dict.get("duration"),
        "duration_formatted": info_dict.get("duration_string"),
        "keywords": info_dict.get("tags"),
        "thumbnail_url": info_dict.get("thumbnail"),
        "thumbnails": info_dict.get("thumbnails"),
        "view_count": info_dict.get("view_count"),
        "like_count": info_dict.get("like_count"),
        "comment_count": info_dict.get("comment_count"),
        "categories": info_dict.get("categories"),
        "language": info_dict.get("language"),
        "age_limit": info_dict.get("age_limit"),
        "upload_date": info_dict.get("upload_date"),
        "release_timestamp": info_dict.get("release_timestamp"),
        "live_status": info_dict.get("live_status"),
        "is_live": info_dict.get("is_live"),
        "availability": info_dict.get("availability"),
    }

    # Normalise the full payload for clients needing every available attribute.
    metadata["raw"] = json.loads(json.dumps(info_dict, default=str))

    return metadata


__all__ = [
    "YouTubeMetadataError",
    "fetch_youtube_metadata",
]

