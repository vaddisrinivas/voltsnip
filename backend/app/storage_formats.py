import hashlib
import json
import os
from typing import Any, Mapping

from app.constants import (
    ENCODING_UTF8,
    SNIPPET_META_SCHEMA,
    SNIPPET_META_VERSION,
    SNIPPET_META_EXTENSION,
)


def snippet_meta_key(blob_key: str) -> str:
    base, _ = os.path.splitext(blob_key)
    if not base:
        return f"{blob_key}{SNIPPET_META_EXTENSION}"
    return f"{base}{SNIPPET_META_EXTENSION}"


def _isoformat_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def build_snippet_metadata(snippet: Any, code: str) -> dict:
    code_hash = hashlib.sha256(code.encode(ENCODING_UTF8)).hexdigest()
    return {
        "schema": SNIPPET_META_SCHEMA,
        "version": SNIPPET_META_VERSION,
        "id": str(getattr(snippet, "id", None)) if getattr(snippet, "id", None) is not None else None,
        "blob_key": getattr(snippet, "blob_key", None),
        "title": getattr(snippet, "title", None),
        "description": getattr(snippet, "description", None),
        "language": getattr(snippet, "language", None),
        "tags": getattr(snippet, "tags", None),
        "kind": getattr(snippet, "kind", None),
        "canonical_key": getattr(snippet, "canonical_key", None),
        "source": getattr(snippet, "source", None),
        "source_hash": getattr(snippet, "source_hash", None),
        "created_at": _isoformat_or_none(getattr(snippet, "created_at", None)),
        "updated_at": _isoformat_or_none(getattr(snippet, "updated_at", None)),
        "expires_at": _isoformat_or_none(getattr(snippet, "expires_at", None)),
        "code_sha256": code_hash,
        "code_size": len(code),
    }


def render_metadata_json(metadata: Mapping[str, Any]) -> str:
    return json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
