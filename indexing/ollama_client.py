"""Client helpers for interacting with Ollama's HTTP API."""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .utils import MissingDependencyError, require_dependency

logger = logging.getLogger(__name__)

try:
    requests = require_dependency("requests", "Install requests to call the Ollama API.")
except MissingDependencyError as exc:  # pragma: no cover - handled lazily
    requests = None
    logger.debug("requests module not available: %s", exc)


class OllamaClient:
    """Thin wrapper around the Ollama REST interface."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        text_model: Optional[str] = None,
        embedding_model: Optional[str] = None,
        vision_model: Optional[str] = None,
        timeout: int = 120,
    ) -> None:
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.text_model = text_model or os.getenv("OLLAMA_TEXT_MODEL", "gemma3:4b")
        self.embedding_model = embedding_model or os.getenv("OLLAMA_EMBED_MODEL", "snowflake-arctic-embed2")
        self.vision_model = vision_model or os.getenv("OLLAMA_VISION_MODEL", self.text_model)
        self.timeout = timeout
        if requests is None:
            raise MissingDependencyError("requests", "Install requests to use the Ollama client.")

    # --- Internal helpers -------------------------------------------------
    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = self.base_url.rstrip("/") + path
        logger.debug("POST %s payload keys=%s", url, list(payload))
        response = requests.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        logger.debug("Response keys=%s", list(data)[:5])
        return data

    # --- Text utilities ---------------------------------------------------
    def refine_text(self, text: str, prompt: str) -> str:
        """Send a text prompt for refinement (grammar correction, summaries, etc.)."""

        payload = {
            "model": self.text_model,
            "prompt": f"{prompt}\n\n{text.strip()}\n",
            "stream": False,
        }
        result = self._post("/api/generate", payload)
        return str(result.get("response", "")).strip()

    def embed_text(self, text: str) -> Sequence[float]:
        """Generate an embedding for the provided text."""

        payload = {
            "model": self.embedding_model,
            "prompt": text,
        }
        result = self._post("/api/embeddings", payload)
        embedding = result.get("embedding")
        if not isinstance(embedding, Sequence):
            raise RuntimeError("Unexpected embedding response from Ollama")
        return embedding

    # --- Vision utilities -------------------------------------------------
    def describe_image(self, image_path: Path, prompt: str) -> str:
        """Generate a textual description of an image."""

        data = _encode_image(image_path)
        payload = {
            "model": self.vision_model,
            "prompt": prompt,
            "images": [data],
            "stream": False,
        }
        result = self._post("/api/generate", payload)
        return str(result.get("response", "")).strip()

    def embed_image(self, image_path: Path) -> Sequence[float]:
        """Generate an embedding for an image."""

        data = _encode_image(image_path)
        payload = {
            "model": self.embedding_model,
            "prompt": "",
            "images": [data],
        }
        result = self._post("/api/embeddings", payload)
        embedding = result.get("embedding")
        if not isinstance(embedding, Sequence):
            raise RuntimeError("Unexpected embedding response for image")
        return embedding


def _encode_image(path: Path) -> str:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    return base64.b64encode(path.read_bytes()).decode("utf-8")


__all__ = ["OllamaClient"]
