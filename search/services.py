from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List, Optional, Sequence

from django.conf import settings
from django.contrib.auth import get_user_model

User = get_user_model()


def persist_uploaded_file(uploaded_file) -> Path:
    """Persist an UploadedFile to disk and return the temporary path."""

    suffix = Path(getattr(uploaded_file, "name", "")).suffix or ".tmp"
    with NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        for chunk in uploaded_file.chunks():
            handle.write(chunk)
        handle.flush()
        temp_path = Path(handle.name)
    try:
        uploaded_file.seek(0)
    except (AttributeError, OSError):
        pass
    return temp_path


def permitted_category_ids(user: User) -> Optional[List[int]]:
    """Return the category identifiers the user can access.

    Admins can see every category, so `None` indicates no restriction.
    """
    if not user.is_authenticated:
        return []
    if getattr(user, "role", None) == User.Role.ADMIN:
        return None
    return list(user.categories.values_list("id", flat=True))


def build_hybrid_query(
    *,
    allowed_categories: Optional[Sequence[int]],
    requested_category: Optional[int],
    search_text: Optional[str],
    text_embedding: Optional[Sequence[float]],
    image_embedding: Optional[Sequence[float]],
) -> Dict[str, Any]:
    """Compose the OpenSearch query body with a top-level hybrid query."""

    # Aumentiamo leggermente il numero di risultati richiesti a OpenSearch
    # per dare al codice Python più "materiale" su cui lavorare per il raggruppamento.
    max_results = max(1, int(getattr(settings, "MAX_TOTAL_SEARCH_RESULTS", 50))) * 2

    # --- 1. Definizione dei filtri di categoria ---
    filters: List[Dict[str, Any]] = []
    if requested_category is not None:
        filters.append({"term": {"category_id": requested_category}})
    elif allowed_categories:
        filters.append({"terms": {"category_id": list(allowed_categories)}})

    # Il filtro da usare nelle sotto-query. La query knn richiede un oggetto query,
    # quindi avvolgiamo i nostri filtri in una bool query.
    sub_query_filter = {"bool": {"filter": filters}} if filters else None

    # --- 2. Costruzione delle sotto-query per la ricerca ibrida ---
    # Ad ogni sotto-query vengono applicati i filtri.
    search_clauses: List[Dict[str, Any]] = []
    cleaned_text = (search_text or "").strip()

    # Sotto-query 1: Ricerca testuale (`match`)
    if cleaned_text:
        text_query = {
            "match": {
                "text_content": {
                    "query": cleaned_text,
                    "operator": "and",
                    "fuzziness": "AUTO",
                }
            }
        }
        if filters:
            # Per applicare un filtro a una query 'match', dobbiamo avvolgerla in una 'bool'.
            filtered_text_query = {"bool": {"must": [text_query], "filter": filters}}
            search_clauses.append(filtered_text_query)
        else:
            search_clauses.append(text_query)

    # Funzione di supporto per creare le query knn con i filtri
    def _build_knn_query(field: str, vector: Sequence[float]) -> Dict[str, Any]:
        knn_clause = {
            "field": field,
            "query_vector": [float(v) for v in vector],
            "k": max_results,
            "num_candidates": max(max_results * 4, 100),
        }
        # Inseriamo il filtro direttamente nella query knn, se esiste.
        if sub_query_filter:
            knn_clause["filter"] = sub_query_filter
        return {"knn": knn_clause}

    # Sotto-query 2 & 3: Ricerca vettoriale (`knn`)
    if text_embedding is not None:
        search_clauses.append(_build_knn_query("text_embedding", text_embedding))
    if image_embedding is not None:
        search_clauses.append(_build_knn_query("image_embedding", image_embedding))

    # --- 3. Composizione della query finale ---
    if not search_clauses:
        # Se non ci sono termini di ricerca, eseguiamo una semplice ricerca filtrata.
        query_clause = {"bool": {"filter": filters, "must": [{"match_all": {}}]}}
    else:
        # Altrimenti, usiamo 'hybrid' come query di primo livello.
        query_clause = {"hybrid": {"queries": search_clauses}}

    body: Dict[str, Any] = {
        "size": max_results,
        "query": query_clause,
        "sort": [{"_score": {"order": "desc"}}],
        "_source": [
            "title",
            "video_id",
            "chunk_type",
            "start_seconds",
            "upload_timestamp",
        ],
    }

    return body