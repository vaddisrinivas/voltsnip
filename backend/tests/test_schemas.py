import pytest
from pydantic import ValidationError

from app.schemas import SnippetCreate


@pytest.mark.parametrize(
    "tags, expected",
    [
        ([" Python ", "PYTHON", "test"], ["python", "test"]),
        (["  ", "Go", "go", "GOLANG "], ["go", "golang"]),
        ([], []),
    ],
)
def test_validate_tags_normalizes(tags, expected):
    snippet = SnippetCreate(code="print('ok')", tags=tags)
    assert snippet.tags == expected


@pytest.mark.parametrize("canonical_key, expected", [(" Demo-Key ", "demo-key"), (None, None)])
def test_validate_canonical_key_normalizes(canonical_key, expected):
    snippet = SnippetCreate(code="print('ok')", canonical_key=canonical_key)
    assert snippet.canonical_key == expected


@pytest.mark.parametrize("canonical_key", ["", "  ", "has space"])
def test_validate_canonical_key_rejects_invalid(canonical_key):
    with pytest.raises(ValidationError):
        SnippetCreate(code="print('ok')", canonical_key=canonical_key)


@pytest.mark.parametrize("tags", [["x" * 51], ["a"] * 21])
def test_validate_tags_rejects_invalid(tags):
    with pytest.raises(ValidationError):
        SnippetCreate(code="print('ok')", tags=tags)


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        SnippetCreate(code="print('ok')", unexpected="nope")
