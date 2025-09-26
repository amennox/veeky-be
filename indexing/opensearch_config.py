"""OpenSearch index configuration."""
from __future__ import annotations

from typing import Any, Dict

# Central place to define all OpenSearch indices and their mappings/settings.
OPENSEARCH_INDICES: Dict[str, Dict[str, Any]] = {
    "videos": {
        "settings": {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 1,
                "knn": True,
                "knn.algo_param.ef_search": 100,
            }
        },
        "mappings": {
            "properties": {
                "video_id": {"type": "integer"},
                "title": {
                    "type": "text",
                    "fields": {
                        "keyword": {
                            "type": "keyword",
                            "ignore_above": 256,
                        }
                    },
                },
                "description": {"type": "text"},
                "source_url": {"type": "keyword"},
                "category_id": {"type": "integer"},
                "category_name": {"type": "keyword"},
                "upload_timestamp": {"type": "date"},
                "processing_status": {"type": "keyword"},
                "video_relation": {
                    "type": "join",
                    "relations": {"video": "content_chunk"},
                },
                "chunk_type": {"type": "keyword"},
                "start_seconds": {"type": "float"},
                "end_seconds": {"type": "float"},
                "text_content": {"type": "text"},
                "text_embedding": {
                    "type": "knn_vector",
                    "dimension": 1024,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "nmslib",
                        "parameters": {
                            "ef_construction": 128,
                            "m": 24,
                        },
                    },
                },
                "keyframe_path": {"type": "keyword"},
                "image_embedding": {
                    "type": "knn_vector",
                    "dimension": 512,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "nmslib",
                        "parameters": {
                            "ef_construction": 128,
                            "m": 24,
                        },
                    },
                },
            }
        },
    }
}

__all__ = ["OPENSEARCH_INDICES"]
