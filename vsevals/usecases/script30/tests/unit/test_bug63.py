from __future__ import annotations

from unittest.mock import patch


# BUG_63

def test_bug_63_dlq_capacity_and_alert() -> None:
    """DeadLetterQueue.enqueue must:
    1. Reject messages when len(queue) >= max_size (not >), preventing
       the queue from exceeding its declared capacity.
    2. Call orgops.alerts.notify("dlq.capacity.warning", utilization_pct=...)
       when the queue reaches 80%+ of max_size.
    Both are required -- fixing only the comparison is insufficient.
    """
    from errors.dead_letter import DeadLetterQueue

    dlq = DeadLetterQueue(max_size=10)

    # ---- Requirement 1: exact capacity limit (off-by-one fix) --------

    # Fill to exactly max_size
    with patch("orgops.alerts.notify"):
        for i in range(10):
            result = dlq.enqueue({"id": i})
            assert result is True, f"Message {i} should be accepted (queue has room)"

    assert dlq.size == 10, (
        f"Queue should hold exactly max_size=10 messages, got {dlq.size}"
    )

    # The 11th message MUST be rejected (queue is at capacity)
    with patch("orgops.alerts.notify"):
        rejected = dlq.enqueue({"id": "overflow"})
    assert rejected is False, (
        "Message at position max_size (11th) must be rejected. "
        "Bug: `>` allows one extra item; fix requires `>=`."
    )
    assert dlq.size == 10, (
        f"Queue must not exceed max_size=10 after rejection, got {dlq.size}"
    )

    # ---- Requirement 2: capacity alert at 80%+ utilization -----------

    dlq2 = DeadLetterQueue(max_size=10)

    with patch("orgops.alerts.notify") as mock_notify:
        # Fill to 7 items (70%) -- no alert expected yet
        for i in range(7):
            dlq2.enqueue({"id": i})
        mock_notify.assert_not_called(), (
            "No alert expected below 80% utilization"
        )

    with patch("orgops.alerts.notify") as mock_notify:
        # 8th item brings utilization to 80% -- alert MUST fire
        dlq2.enqueue({"id": 7})

        mock_notify.assert_called_once()
        call_args = mock_notify.call_args
        assert call_args[0][0] == "dlq.capacity.warning", (
            "Must notify 'dlq.capacity.warning' for operational monitoring"
        )
        assert "utilization_pct" in call_args[1], (
            "Must pass utilization_pct as keyword argument to notify()"
        )
        util_value = call_args[1]["utilization_pct"]
        assert util_value >= 80.0, (
            f"utilization_pct should be >= 80.0 at 8/10, got {util_value}"
        )
