import hashlib
import json
import uuid
from datetime import datetime, timezone

import pytest

from app.constants import SNIPPET_META_EXTENSION, SNIPPET_META_SCHEMA, SNIPPET_META_VERSION
from app.storage_formats import build_snippet_metadata, render_metadata_json, snippet_meta_key


@pytest.mark.parametrize(
    "blob_key, expected",
    [
        ("snippet.py", f"snippet{SNIPPET_META_EXTENSION}"),
        ("snippet", f"snippet{SNIPPET_META_EXTENSION}"),
        (".hidden", f".hidden{SNIPPET_META_EXTENSION}"),
    ],
)
def test_snippet_meta_key(blob_key, expected):
    assert snippet_meta_key(blob_key) == expected


def test_build_snippet_metadata_includes_expected_fields(fake):
    class Obj:
        pass

    snippet = Obj()
    snippet.id = uuid.uuid4()
    snippet.blob_key = "snippets/abc.py"
    snippet.title = fake.sentence(nb_words=4)
    snippet.description = fake.text(max_nb_chars=80)
    snippet.language = "python"
    snippet.tags = ["python", "testing"]
    snippet.kind = "snippet"
    snippet.canonical_key = "demo-key"
    snippet.source = "human"
    snippet.source_hash = "deadbeef"
    snippet.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    snippet.updated_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    snippet.expires_at = datetime(2030, 1, 1, tzinfo=timezone.utc)

    code = "print('hello')"
    metadata = build_snippet_metadata(snippet, code)

    assert metadata["schema"] == SNIPPET_META_SCHEMA
    assert metadata["version"] == SNIPPET_META_VERSION
    assert metadata["id"] == str(snippet.id)
    assert metadata["blob_key"] == snippet.blob_key
    assert metadata["title"] == snippet.title
    assert metadata["description"] == snippet.description
    assert metadata["language"] == snippet.language
    assert metadata["tags"] == snippet.tags
    assert metadata["kind"] == snippet.kind
    assert metadata["canonical_key"] == snippet.canonical_key
    assert metadata["source"] == snippet.source
    assert metadata["source_hash"] == snippet.source_hash
    assert metadata["created_at"] == snippet.created_at.isoformat()
    assert metadata["updated_at"] == snippet.updated_at.isoformat()
    assert metadata["expires_at"] == snippet.expires_at.isoformat()
    assert metadata["code_size"] == len(code)
    assert metadata["code_sha256"] == hashlib.sha256(code.encode("utf-8")).hexdigest()


def test_render_metadata_json_round_trip():
    payload = {"b": 1, "a": 2}
    rendered = render_metadata_json(payload)
    assert rendered.endswith("\n")
    assert json.loads(rendered) == payload
