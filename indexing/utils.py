"""Utility helpers for the indexing pipeline."""
from __future__ import annotations

import importlib
import math
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Sequence

from django.apps import apps
from django.conf import settings
from django.db import OperationalError, ProgrammingError


class MissingDependencyError(RuntimeError):
    """Raised when an optional runtime dependency is not available."""

    def __init__(self, package: str, hint: Optional[str] = None) -> None:
        message = f"Required dependency '{package}' is not installed."
        if hint:
            message = f"{message} {hint}"
        super().__init__(message)
        self.package = package
        self.hint = hint


@dataclass(slots=True)
class VideoSegment:
    """Represents an analysed time range for the video."""

    start: float
    end: float
    raw_transcription: Optional[str] = None
    corrected_transcription: Optional[str] = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(slots=True)
class Keyframe:
    """Represents a keyframe extracted from the video."""

    timestamp: float
    path: Path
    description: Optional[str] = None
    embedding: Optional[Sequence[float]] = None


@contextmanager
def temporary_directory(prefix: str = "veeky-index-") -> Iterator[Path]:
    """Context manager yielding a temporary directory path."""

    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def ensure_directory(path: Path | str) -> Path:
    """Create the directory if it does not exist and return the Path."""

    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_unlink(path: Path) -> None:
    """Remove a file if it exists."""

    try:
        path.unlink(missing_ok=True)  # type: ignore[arg-type]
    except TypeError:  # Python < 3.8 compatibility for missing_ok
        if path.exists():
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def safe_rmtree(path: Path) -> None:
    """Remove a directory tree if it exists."""

    shutil.rmtree(path, ignore_errors=True)


def chunk_text(text: str, max_chars: int = 900) -> List[str]:
    """Split text into roughly sentence sized chunks."""

    text = text.strip()
    if not text:
        return []

    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: List[str] = []
    buffer = []
    current_length = 0
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        sentence_len = len(sentence)
        if current_length + sentence_len + 1 > max_chars and buffer:
            chunks.append(" ".join(buffer))
            buffer = [sentence]
            current_length = sentence_len
        else:
            buffer.append(sentence)
            current_length += sentence_len + 1
    if buffer:
        chunks.append(" ".join(buffer))
    return chunks


def timestamp_to_filename(timestamp: float) -> str:
    """Convert a timestamp in seconds into a sortable filename."""

    ms = int(math.floor(timestamp * 1000))
    return f"frame_{ms:08d}.jpg"


def require_dependency(module_name: str, hint: Optional[str] = None):
    """Import a dependency or raise a MissingDependencyError."""

    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise MissingDependencyError(module_name, hint) from exc


PromptResolver = Callable[[str, str], str]


def default_prompt_resolver(purpose: str, category_name: str) -> str:
    """Return a fallback prompt when no dynamic prompt is available."""

    if purpose == "keyframe_description":
        return (
            "You are an assistant that explains what is happening in a video frame. "
            "Provide a concise, vivid description tailored to the category '"
            f"{category_name}'."
        )
    if purpose == "transcript_cleanup":
        return (
            "Clean up the transcription for clarity while preserving meaning. "
            "Fix punctuation, casing, and remove filler words where obvious."
        )
    if purpose == "segment_summary":
        return (
            "Summarise the segment in 1-2 sentences highlighting key ideas relevant "
            f"to {category_name}."
        )
    return ""


def fetch_prompt(purpose: str, category_name: str, fallback_resolver: PromptResolver = default_prompt_resolver) -> str:
    """Attempt to fetch a prompt from the 'configs' app, falling back to defaults."""

    try:
        PromptModel = apps.get_model("configs", "Prompt")  # type: ignore[assignment]
    except LookupError:
        return fallback_resolver(purpose, category_name)

    if PromptModel is None:
        return fallback_resolver(purpose, category_name)

    try:
        prompt_obj = (
            PromptModel.objects.filter(purpose=purpose, is_active=True)
            .order_by("-updated_at")
            .first()
        )
    except (ProgrammingError, OperationalError):
        return fallback_resolver(purpose, category_name)

    if prompt_obj and getattr(prompt_obj, "template", None):
        template = str(prompt_obj.template)
        if "{category}" in template:
            return template.format(category=category_name)
        return template

    return fallback_resolver(purpose, category_name)


def build_keyframe_directory(video_id: int, category_name: str) -> Path:
    """Return the directory path for storing keyframes."""

    base_dir = Path(getattr(settings, "MEDIA_ROOT", Path.cwd()))
    path = base_dir / "keyframes" / slugify(category_name) / str(video_id)
    return ensure_directory(path)


def slugify(value: str) -> str:
    """Simplified slugify implementation suitable for directory names."""

    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-")
    value = value.lower()
    return value or "uncategorised"


__all__ = [
    "Keyframe",
    "MissingDependencyError",
    "VideoSegment",
    "build_keyframe_directory",
    "chunk_text",
    "ensure_directory",
    "fetch_prompt",
    "require_dependency",
    "safe_rmtree",
    "safe_unlink",
    "slugify",
    "temporary_directory",
    "timestamp_to_filename",
]
