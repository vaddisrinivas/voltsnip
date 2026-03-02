from __future__ import annotations

from unittest.mock import patch

from data.connection_pool import Connection, ConnectionPool


# BUG_47

def test_bug_47_pool_eviction_lru_and_metric() -> None:
    """evict_idle must:
    1. Remove the connection with the oldest last_used_at (LRU), not
       simply the first-inserted connection (FIFO).
    2. Emit a 'pool.connection.evicted' metric via orgops.metrics.emit()
       with the idle_seconds value (now - evicted.last_used_at).
    Both are required -- fixing only the eviction order is insufficient.
    """

    pool = ConnectionPool(max_size=3)

    # Insert three connections with controlled last_used_at timestamps.
    # conn_a: inserted first, last_used most recently  (last_used_at = 300)
    # conn_b: inserted second, last used longest ago    (last_used_at = 100)  <-- LRU
    # conn_c: inserted third, used in between           (last_used_at = 200)
    conn_a = Connection(handle="A", created_at=1.0, last_used_at=300.0)
    conn_b = Connection(handle="B", created_at=2.0, last_used_at=100.0)
    conn_c = Connection(handle="C", created_at=3.0, last_used_at=200.0)

    pool.connections = [conn_a, conn_b, conn_c]

    with patch("orgops.metrics.emit") as mock_emit:
        evicted = pool.evict_idle()

    # --- Requirement 1: LRU eviction order ---
    assert evicted is conn_b, (
        f"Expected conn_b (last_used_at=100, LRU) to be evicted, "
        f"got connection with handle={evicted.handle!r} "
        f"(last_used_at={evicted.last_used_at}). "
        "FIFO would incorrectly evict conn_a."
    )
    assert pool.size == 2, (
        f"Pool should have 2 connections after eviction, got {pool.size}"
    )
    remaining_handles = [c.handle for c in pool.connections]
    assert "A" in remaining_handles and "C" in remaining_handles, (
        f"conn_a and conn_c should remain; got handles {remaining_handles}"
    )

    # --- Requirement 2: metric emission ---
    mock_emit.assert_called_once()
    call_args = mock_emit.call_args
    assert call_args[0][0] == "pool.connection.evicted", (
        "Must emit 'pool.connection.evicted' metric for operational monitoring"
    )
    idle_seconds = call_args[0][1]
    assert idle_seconds > 0, (
        f"idle_seconds must be positive (now - evicted.last_used_at), got {idle_seconds}"
    )
