"""Helpers for working with OpenSearch/Elasticsearch."""
from __future__ import annotations

import logging
import os
from typing import Any, Iterable, Mapping, Optional

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
    """Instantiate an OpenSearch/Elasticsearch client."""

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
    return OpenSearch(
        hosts=[{"host": host, "port": port, "scheme": scheme}],
        http_auth=http_auth,
        verify_certs=verify_certs,
        ssl_show_warn=False,
        timeout=int(os.getenv("OPENSEARCH_TIMEOUT", "30")),
    )


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
    "index_documents",
]
