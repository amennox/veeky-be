from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult, SpanExporter

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_OUTPUT = _BASE_DIR / "logs" / "telemetry.jsonl"
_lock = threading.Lock()
_initialized = False


def _ensure_serializable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_ensure_serializable(v) for v in value]
    return str(value)


def _format_timestamp(nanos: int) -> str:
    return datetime.fromtimestamp(nanos / 1_000_000_000, tz=timezone.utc).isoformat()


class JsonFileSpanExporter(SpanExporter):
    """Persist spans as JSON lines in a local file."""

    def __init__(self, output_path: Path | None = None) -> None:
        self._path = (output_path or _DEFAULT_OUTPUT).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        payload = []
        for span in spans:
            span_entry = {
                "name": span.name,
                "trace_id": format(span.context.trace_id, "032x"),
                "span_id": format(span.context.span_id, "016x"),
                "parent_span_id": (
                    format(span.parent.span_id, "016x") if span.parent else None
                ),
                "start_time": _format_timestamp(span.start_time),
                "end_time": _format_timestamp(span.end_time),
                "status": span.status.status_code.name,
                "status_message": span.status.description,
                "attributes": _serialize_mapping(span.attributes),
                "resource": _serialize_mapping(span.resource.attributes),
                "events": [
                    {
                        "name": event.name,
                        "timestamp": _format_timestamp(event.timestamp),
                        "attributes": _serialize_mapping(event.attributes),
                    }
                    for event in span.events
                ],
            }
            payload.append(json.dumps(span_entry, ensure_ascii=False))

        with _lock:
            with self._path.open("a", encoding="utf-8") as file_handle:
                for line in payload:
                    file_handle.write(line + "\n")

        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:  # type: ignore[override]
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:  # type: ignore[override]
        return True

    @property
    def path(self) -> Path:
        return self._path


def _serialize_mapping(values: Mapping[str, Any] | Mapping[Any, Any] | None) -> dict[str, Any]:
    if not values:
        return {}
    return {str(key): _ensure_serializable(val) for key, val in values.items()}


def initialize_tracer(service_name: str = "veeky-backend") -> None:
    global _initialized
    if _initialized:
        return

    with _lock:
        if _initialized:
            return

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        exporter = JsonFileSpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        try:
            trace.set_tracer_provider(provider)
        except RuntimeError as err:
            logger.info("Tracer provider already configured: %s", err)
        else:
            logger.info("OpenTelemetry initialized. Writing spans to %s", exporter.path)
        _initialized = True


def get_tracer(name: str):
    return trace.get_tracer(name)