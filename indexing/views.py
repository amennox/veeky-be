"""API endpoints exposing Django-Q task information."""

from __future__ import annotations

import ast
import json
import logging
from datetime import datetime, timezone as dt_timezone
from typing import Dict, List, Optional

from django_q.conf import Conf
from django_q.models import OrmQ, Task
from django_q.signing import SignedPackage
from rest_framework import permissions, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from drf_spectacular.utils import OpenApiParameter, extend_schema

from .serializers import DjangoQTaskSerializer


logger = logging.getLogger(__name__)


def _to_naive_default(dt: Optional[datetime]) -> datetime:
    if dt is not None:
        return dt
    return datetime.min.replace(tzinfo=dt_timezone.utc)


def _safe_parse(value, default):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        parsed = json.loads(value)
        if isinstance(parsed, tuple):
            return list(parsed)
        return parsed
    except (TypeError, ValueError):
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, (set, tuple)):
                return list(parsed)
            return parsed
        except (ValueError, SyntaxError):
            return value


class DjangoQTaskViewSet(viewsets.ViewSet):
    """Expose queued and completed Django-Q tasks with cancellation support."""

    permission_classes = [permissions.IsAdminUser]

    @extend_schema(
        tags=["Queue"],
        summary="List tasks",
        description=(
            "Restituisce i task gestiti da Django-Q, includendo sia quelli in coda "
            "sia quelli completati. È possibile filtrare per stato con "
            "?status=pending,success,failed."
        ),
        parameters=[
            OpenApiParameter(
                name="status",
                description=(
                    "Filtra i task per stato (pending, running, success, failed). "
                    "Accetta valori separati da virgola."
                ),
                required=False,
                type=str,
            )
        ],
        responses={200: DjangoQTaskSerializer(many=True)},
    )
    def list(self, request):
        statuses = self._parse_status_filter(request.query_params.get("status"))
        pending_map = self._build_pending_map()
        records: List[Dict] = []

        for pending in pending_map.values():
            if statuses and pending["status"] not in statuses:
                continue
            records.append(pending)

        for task in Task.objects.order_by("-started"):
            record = self._serialize_completed_task(task)
            if statuses and record["status"] not in statuses:
                continue
            records.append(record)

        records.sort(key=lambda item: _to_naive_default(item.get("started")), reverse=True)
        serializer = DjangoQTaskSerializer(instance=records, many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=["Queue"],
        summary="Retrieve task",
        description="Dettagli di un singolo task di Django-Q.",
        responses={200: DjangoQTaskSerializer},
    )
    def retrieve(self, request, pk: Optional[str] = None):  # type: ignore[override]
        if pk is None:
            raise NotFound("Task identifier is required")

        try:
            task = Task.objects.get(pk=pk)
        except Task.DoesNotExist:
            pending_map = self._build_pending_map()
            pending = pending_map.get(pk)
            if pending is None:
                raise NotFound(f"Task {pk} non trovato")
            serializer = DjangoQTaskSerializer(instance=pending)
            return Response(serializer.data)

        record = self._serialize_completed_task(task)
        serializer = DjangoQTaskSerializer(instance=record)
        return Response(serializer.data)

    @extend_schema(
        tags=["Queue"],
        summary="Cancel pending task",
        description=(
            "Rimuove un task ancora in coda. I task già in esecuzione o completati "
            "non possono essere annullati."
        ),
        responses={204: None},
    )
    def destroy(self, request, pk: Optional[str] = None):  # type: ignore[override]
        if pk is None:
            raise NotFound("Task identifier is required")

        pending_entries = self._build_pending_entries()
        entry = pending_entries.get(pk)
        if entry is None:
            if Task.objects.filter(pk=pk).exists():
                return Response(
                    {"detail": "Il task non è più annullabile."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            raise NotFound(f"Task {pk} non trovato")

        entry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _parse_status_filter(raw: Optional[str]) -> Optional[set[str]]:
        if not raw:
            return None
        statuses = {item.strip().lower() for item in raw.split(",") if item.strip()}
        return statuses or None

    def _build_pending_entries(self) -> Dict[str, OrmQ]:
        entries: Dict[str, OrmQ] = {}
        queryset = OrmQ.objects.filter(key=Conf.PREFIX)
        for entry in queryset:
            try:
                payload = SignedPackage.loads(entry.payload)
            except Exception:
                logger.warning("Impossibile decodificare il payload di OrmQ %s", entry.pk)
                continue
            task_id = str(payload.get("id") or entry.pk)
            entries[task_id] = entry
        return entries

    def _build_pending_map(self) -> Dict[str, Dict]:
        pending_records: Dict[str, Dict] = {}
        queryset = OrmQ.objects.filter(key=Conf.PREFIX)
        for entry in queryset:
            try:
                payload = SignedPackage.loads(entry.payload)
            except Exception:
                logger.warning("Impossibile decodificare il payload di OrmQ %s", entry.pk)
                continue
            task_id = str(payload.get("id") or entry.pk)
            record = {
                "id": task_id,
                "name": payload.get("name") or "",
                "func": payload.get("func") or "",
                "status": "pending",
                "started": payload.get("started"),
                "stopped": None,
                "duration": None,
                "success": None,
                "attempt_count": 0,
                "hook": payload.get("hook"),
                "group": payload.get("group"),
                "args": _safe_parse(payload.get("args"), []),
                "kwargs": _safe_parse(payload.get("kwargs"), {}),
                "result": None,
                "queue_id": str(entry.pk),
                "cancellable": True,
            }
            pending_records[task_id] = record
        return pending_records

    def _serialize_completed_task(self, task: Task) -> Dict:
        status_value = self._resolve_status(task)
        started = task.started
        stopped = task.stopped
        duration = None
        if started and stopped:
            duration = (stopped - started).total_seconds()

        record = {
            "id": str(task.pk),
            "name": task.name or "",
            "func": task.func or "",
            "status": status_value,
            "started": started,
            "stopped": stopped,
            "duration": duration,
            "success": task.success,
            "attempt_count": task.attempt_count,
            "hook": task.hook,
            "group": task.group,
            "args": _safe_parse(task.args, []),
            "kwargs": _safe_parse(task.kwargs, {}),
            "result": _safe_parse(task.result, None),
            "queue_id": None,
            "cancellable": False,
        }
        return record

    @staticmethod
    def _resolve_status(task: Task) -> str:
        if task.success is True:
            return "success"
        if task.success is False:
            return "failed"
        if task.stopped is None:
            return "running"
        return "unknown"
