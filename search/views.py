from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from django.conf import settings
from django.utils.timezone import localtime
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

try:  # opensearch is optional during tests
    from opensearchpy.exceptions import OpenSearchException
except Exception:  # pragma: no cover - optional dependency guard
    OpenSearchException = Exception  # type: ignore[misc,assignment]

from indexing.ollama_client import OllamaClient
from indexing.opensearch_client import get_client
from indexing.tasks import DEFAULT_INDEX_NAME
from indexing.utils import MissingDependencyError, fetch_prompt
from videos.models import Video

from .serializers import (
    HybridSearchRequestSerializer,
    HybridSearchResultSerializer,
)
from .services import build_hybrid_query, persist_uploaded_file, permitted_category_ids

tracer = trace.get_tracer("search.views")


class SearchAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(
        tags=["Search"],
        summary="Hybrid search across video content",
        description="Performs a hybrid text and image search over indexed video content.",
        request=HybridSearchRequestSerializer,
        responses={
            200: HybridSearchResultSerializer(many=True),
            400: OpenApiResponse(description="Invalid input."),
            403: OpenApiResponse(description="Forbidden."),
            502: OpenApiResponse(description="OpenSearch query failed."),
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = HybridSearchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with tracer.start_as_current_span("search.hybrid_search") as span:
            user = request.user
            if user and user.is_authenticated:
                span.set_attribute("user.id", str(user.pk))
                span.set_attribute("user.role", getattr(user, "role", "unknown"))

            allowed_categories = permitted_category_ids(user)
            if allowed_categories is None:
                span.set_attribute("search.allowed_categories", "all")
            else:
                span.set_attribute("search.allowed_categories", len(allowed_categories))

            requested_category = data.get("video_category_id")
            if requested_category is not None:
                span.set_attribute("search.requested_category", requested_category)
                if (
                    allowed_categories is not None
                    and allowed_categories
                    and requested_category not in allowed_categories
                ):
                    span.set_status(
                        Status(
                            StatusCode.ERROR,
                            "requested_category_not_permitted",
                        )
                    )
                    return Response(
                        {"detail": _("You are not allowed to search this category.")},
                        status=status.HTTP_403_FORBIDDEN,
                    )

            search_text = data.get("search_text", "") or ""
            search_image = data.get("search_image")
            analyze_image = data.get("analyze_image", False)

            span.set_attribute("search.has_text", bool(search_text.strip()))
            span.set_attribute("search.has_image", search_image is not None)
            span.set_attribute("search.analyze_image", bool(analyze_image))

            if allowed_categories == []:
                span.add_event("no_categories_allowed")
                span.set_status(Status(StatusCode.OK))
                return Response([], status=status.HTTP_200_OK)

            ollama_required = bool(search_text.strip()) or search_image is not None
            ollama_client: Optional[OllamaClient] = None
            if ollama_required:
                try:
                    ollama_client = OllamaClient()
                except MissingDependencyError as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    return Response(
                        {"detail": str(exc)},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, "ollama_initialization_failed"))
                    return Response(
                        {"detail": "Failed to initialise embedding service."},
                        status=status.HTTP_502_BAD_GATEWAY,
                    )

            image_temp_path: Optional[Path] = None
            image_embedding: Optional[Sequence[float]] = None
            try:
                if search_image is not None and ollama_client is not None:
                    image_temp_path = persist_uploaded_file(search_image)
                    span.add_event(
                        "search.image_persisted", {"path": str(image_temp_path)}
                    )

                    if analyze_image:
                        try:
                            prompt = fetch_prompt("keyframe_description", "general")
                            description = ollama_client.describe_image(
                                image_temp_path, prompt
                            )
                            span.add_event(
                                "search.image_described",
                                {"description_length": len(description)},
                            )
                            if description:
                                if search_text.strip():
                                    search_text = f"{search_text.strip()} {description}"
                                else:
                                    search_text = description
                        except Exception as exc:
                            span.record_exception(exc)
                            span.add_event("search.image_description_failed")

                    try:
                        image_embedding = list(
                            ollama_client.embed_image(image_temp_path)
                        )
                        span.add_event(
                            "search.image_embedded",
                            {"embedding_dims": len(image_embedding)},
                        )
                    except Exception as exc:
                        image_embedding = None
                        span.record_exception(exc)
                        span.add_event("search.image_embedding_failed")
            finally:
                if image_temp_path:
                    try:
                        image_temp_path.unlink(missing_ok=True)  # type: ignore[arg-type]
                    except TypeError:
                        if image_temp_path.exists():
                            try:
                                image_temp_path.unlink()
                            except FileNotFoundError:
                                pass

            text_embedding: Optional[Sequence[float]] = None
            final_search_text = search_text.strip()
            if final_search_text and ollama_client is not None:
                try:
                    text_embedding = list(ollama_client.embed_text(final_search_text))
                    span.add_event(
                        "search.text_embedded",
                        {"embedding_dims": len(text_embedding)},
                    )
                except Exception as exc:
                    text_embedding = None
                    span.record_exception(exc)
                    span.add_event("search.text_embedding_failed")

            try:
                query_body = build_hybrid_query(
                    allowed_categories=allowed_categories,
                    requested_category=requested_category,
                    search_text=final_search_text,
                    text_embedding=text_embedding,
                    image_embedding=image_embedding,
                )
            except Exception as exc:  # pragma: no cover - defensive
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, "query_build_failed"))
                return Response(
                    {"detail": "Failed to build search query."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            try:
                client = get_client()
            except MissingDependencyError as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                return Response(
                    {"detail": str(exc)},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            except RuntimeError as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, "opensearch_unavailable"))
                return Response(
                    {"detail": str(exc)},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            if not isinstance(query_body, dict):
                error_message = f"query_body must be dict, got {type(query_body).__name__}"
                span.add_event("search.invalid_query_body", {"message": error_message})
                span.set_status(Status(StatusCode.ERROR, "invalid_query_body"))
                detail: Dict[str, Any] = {"detail": error_message}
                if settings.DEBUG:
                    detail["query"] = query_body
                return Response(detail, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            try:
                search_response = client.search(
                    index=DEFAULT_INDEX_NAME,
                    body=query_body,
                )
                span.add_event("search.executed")
            except OpenSearchException as exc:
                error_message = str(exc)
                span.record_exception(exc)
                span.add_event("search.opensearch_error", {"message": error_message})
                span.set_status(Status(StatusCode.ERROR, "opensearch_query_failed"))
                detail: Dict[str, Any] = {"detail": error_message}
                if settings.DEBUG:
                    detail["query"] = self._serialise_query(query_body)
                return Response(detail, status=status.HTTP_502_BAD_GATEWAY)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, "opensearch_query_failed"))
                span.add_event("search.unexpected_error", {"message": str(exc)})
                detail: Dict[str, Any] = {"detail": str(exc)}
                if settings.DEBUG:
                    detail["query"] = self._serialise_query(query_body)
                return Response(
                    detail,
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            results = self._build_response(search_response)
            span.add_event("search.results_ready", {"count": len(results)})
            span.set_status(Status(StatusCode.OK))
            return Response(results, status=status.HTTP_200_OK)

    def _serialise_query(self, payload: Dict[str, Any]) -> str:
        try:
            return json.dumps(payload, indent=2, ensure_ascii=False)
        except TypeError:
            return repr(payload)

    def _build_response(self, search_response: Dict[str, Any]) -> List[Dict[str, Any]]:
        hits = search_response.get("hits", {}).get("hits", [])
        if not hits:
            return []

        video_ids = set()
        documents: List[Tuple[str, float, Dict[str, Any]]] = []

        for hit in hits:
            doc_id = hit.get("_id")
            doc_score = float(hit.get("_score", 0.0))
            source = hit.get("_source") or {}
            if source:
                documents.append((doc_id, doc_score, source))
                if source.get("video_id") is not None:
                    video_ids.add(int(source["video_id"]))

            inner_hits = (
                hit.get("inner_hits", {})
                .get("top_segments", {})
                .get("hits", {})
                .get("hits", [])
            )
            for inner in inner_hits:
                inner_id = inner.get("_id")
                inner_score = float(inner.get("_score", 0.0))
                inner_source = inner.get("_source") or {}
                if inner_source:
                    documents.append((inner_id, inner_score, inner_source))
                    if inner_source.get("video_id") is not None:
                        video_ids.add(int(inner_source["video_id"]))

        video_meta = self._fetch_video_metadata(video_ids)

        seen_ids = set()
        results: List[Dict[str, Any]] = []
        per_video_counts: Dict[int, int] = {}
        max_segments = max(1, int(getattr(settings, "MAX_SEGMENTS_PER_VIDEO", 10)))

        for doc_id, score, source in sorted(
            documents, key=lambda item: item[1], reverse=True
        ):
            if doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)

            video_id = source.get("video_id")
            if video_id is None:
                continue

            per_video_counts.setdefault(video_id, 0)
            if per_video_counts[video_id] >= max_segments:
                continue
            per_video_counts[video_id] += 1

            meta = video_meta.get(int(video_id), {})

            title = source.get("title") or meta.get("title", "")
            upload_timestamp = source.get("upload_timestamp") or meta.get(
                "upload_timestamp"
            )

            result = {
                "title": title,
                "video_id": video_id,
                "chunk_type": source.get("chunk_type") or "video",
                "start_seconds": source.get("start_seconds"),
                "upload_timestamp": upload_timestamp,
                "relevance": score,
            }
            results.append(result)

        max_total = max(1, int(getattr(settings, "MAX_TOTAL_SEARCH_RESULTS", 50)))
        return results[:max_total]

    def _fetch_video_metadata(self, video_ids: Iterable[int]) -> Dict[int, Dict[str, Any]]:
        metadata: Dict[int, Dict[str, Any]] = {}
        queryset = (
            Video.objects.filter(id__in=list(video_ids))
            .values_list("id", "name", "created_at")
        )
        for video_id, title, created_at in queryset:
            timestamp = localtime(created_at).isoformat()
            metadata[int(video_id)] = {"title": title, "upload_timestamp": timestamp}
        return metadata
