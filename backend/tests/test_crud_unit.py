from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock

import pytest

from app import crud
from app.constants import (
    ACTIVE_STATUS,
    SURVIVED_STATUS,
    SURVIVAL_UPVOTES,
    SURVIVAL_VIEWS,
    SURVIVAL_REFERENCES,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "upvotes, views, refs, should_survive",
    [
        (SURVIVAL_UPVOTES, 0, 0, True),
        (0, SURVIVAL_VIEWS, 0, True),
        (0, 0, SURVIVAL_REFERENCES, True),
        (SURVIVAL_UPVOTES - 1, SURVIVAL_VIEWS - 1, SURVIVAL_REFERENCES - 1, False),
    ],
)
async def test_check_survival_promotes_when_threshold_met(
    upvotes, views, refs, should_survive
):
    db = MagicMock()
    snippet = SimpleNamespace(
        status=ACTIVE_STATUS,
        upvote_count=upvotes,
        view_count=views,
        reference_count=refs,
        expires_at=datetime.now(timezone.utc),
    )

    await crud.check_survival(db, snippet)

    if should_survive:
        assert snippet.status == SURVIVED_STATUS
        assert snippet.expires_at > datetime.now(timezone.utc) + timedelta(days=365 * 5)
        db.add.assert_called_once_with(snippet)
    else:
        assert snippet.status == ACTIVE_STATUS
        db.add.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("title", ["", None])
async def test_search_snippets_by_title_short_circuit(title):
    db = MagicMock()
    db.execute = AsyncMock()

    results = await crud.search_snippets_by_title(db, title)

    assert results == []
    db.execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("tags", [[], None])
async def test_search_snippets_by_tags_short_circuit(tags):
    db = MagicMock()
    db.execute = AsyncMock()

    results = await crud.search_snippets_by_tags(db, tags)

    assert results == []
    db.execute.assert_not_called()
