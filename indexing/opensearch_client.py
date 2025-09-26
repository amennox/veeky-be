"""Helpers for working with OpenSearch/Elasticsearch."""
from __future__ import annotations

import logging
import os
from copy import deepcopy
from typing import Any, Iterable, Mapping, Optional

from .opensearch_config import OPENSEARCH_INDICES
from .utils import MissingDependencyError

logger = logging.getLogger(__name__)

try:  # Prefer OpenSearch if available
    from opensearchpy import OpenSearch  # type: ignore
    from opensearchpy.helpers import bulk as os_bulk  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    OpenSearch = None  # type: ignore
    os_bulk = None  # type: ignore

if OpenSearch is None:
    try:
        from elasticsearch import Elasticsearch as OpenSearch  # type: ignore
        from elasticsearch.helpers import bulk as os_bulk  # type: ignore
    except ImportError:  # pragma: no cover - optional dependency
        OpenSearch = None  # type: ignore
        os_bulk = None  # type: ignore


def get_client() -> Any:
    """Instantiate an OpenSearch/Elasticsearch client and ensure indices exist."""

    if OpenSearch is None:
        raise MissingDependencyError(
            "opensearch-py",
            "Install opensearch-py or elasticsearch to enable indexing.",
        )

    host = os.getenv("OPENSEARCH_HOST", "localhost")
    port = int(os.getenv("OPENSEARCH_PORT", "9200"))
    scheme = os.getenv("OPENSEARCH_SCHEME", "http")
    username = os.getenv("OPENSEARCH_USER")
    password = os.getenv("OPENSEARCH_PASSWORD")

    http_auth = None
    if username and password:
        http_auth = (username, password)

    verify_certs = os.getenv("OPENSEARCH_VERIFY_CERTS", "true").lower() in {"1", "true", "yes"}

    logger.debug("Initialising OpenSearch client %s:%s", host, port)
    client = OpenSearch(
        hosts=[{"host": host, "port": port, "scheme": scheme}],
        http_auth=http_auth,
        verify_certs=verify_certs,
        ssl_show_warn=False,
        timeout=int(os.getenv("OPENSEARCH_TIMEOUT", "30")),
    )

    ensure_indices(client)
    return client


def ensure_indices(client: Any) -> None:
    """Ensure all configured indices exist in OpenSearch."""

    indices_client = getattr(client, "indices", None)
    if indices_client is None:
        raise RuntimeError("OpenSearch client does not expose an indices API")

    indices_to_ensure = {name: deepcopy(definition) for name, definition in OPENSEARCH_INDICES.items()}

    # Honour the primary index override used by the indexing pipeline.
    default_index_name = os.getenv("OPENSEARCH_INDEX")
    if default_index_name and default_index_name not in indices_to_ensure:
        base_definition = OPENSEARCH_INDICES.get("videos")
        if base_definition is not None:
            indices_to_ensure[default_index_name] = deepcopy(base_definition)

    for index_name, definition in indices_to_ensure.items():
        try:
            exists = indices_client.exists(index=index_name)
        except Exception as exc:  # pragma: no cover - relies on OpenSearch client
            logger.exception("Failed to check existence of index %s", index_name)
            raise RuntimeError(f"Failed to check index {index_name}") from exc

        if exists:
            logger.debug("OpenSearch index '%s' already exists", index_name)
            continue

        logger.info("Creating OpenSearch index '%s'", index_name)
        try:
            indices_client.create(index=index_name, body=definition)
        except Exception as exc:  # pragma: no cover - relies on OpenSearch client
            logger.exception("Failed to create index %s", index_name)
            raise RuntimeError(f"Failed to create index {index_name}") from exc


def index_documents(
    client: Any,
    actions: Iterable[Mapping[str, Any]],
    refresh: Optional[str] = None,
) -> None:
    """Submit bulk indexing actions."""

    if os_bulk is None:
        raise MissingDependencyError(
            "opensearch-py",
            "Install opensearch-py or elasticsearch helpers for bulk indexing.",
        )

    success, errors = os_bulk(client, actions, refresh=refresh)
    if errors:
        logger.error("OpenSearch bulk indexing reported errors: %s", errors)
        raise RuntimeError("OpenSearch bulk indexing failed")
    logger.info("Indexed %s documents", success)


__all__ = [
    "get_client",
    "ensure_indices",
    "index_documents",
]
