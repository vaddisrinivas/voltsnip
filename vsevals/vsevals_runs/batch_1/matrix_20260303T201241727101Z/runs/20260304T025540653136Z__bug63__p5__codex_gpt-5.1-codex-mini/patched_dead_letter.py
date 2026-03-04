"""Dead-letter queue for messages that cannot be processed.

Provides a bounded queue that collects failed messages for later
inspection / replay.  When the queue nears capacity an operational
alert must be sent so on-call engineers can investigate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class DeadLetterQueue:
    """Bounded dead-letter queue with capacity alerting.

    Parameters
    ----------
    max_size:
        Maximum number of messages the queue may hold.  Once full,
        ``enqueue`` must reject new messages and return ``False``.
    """

    max_size: int = 1000
    queue: List[Dict[str, Any]] = field(default_factory=list)

    # ---- public API ------------------------------------------------

    def enqueue(self, message: Dict[str, Any]) -> bool:
        if len(self.queue) >= self.max_size:
            return False

        self.queue.append(message)
        if self.utilization_pct >= 80.0:
            from orgops.alerts import notify
            notify("dlq.capacity.warning")
        return True

    def peek(self) -> Dict[str, Any] | None:
        """Return the oldest message without removing it."""
        if not self.queue:
            return None
        return self.queue[0]

    def dequeue(self) -> Dict[str, Any] | None:
        """Remove and return the oldest message, or ``None`` if empty."""
        if not self.queue:
            return None
        return self.queue.pop(0)

    @property
    def size(self) -> int:
        """Current number of messages in the queue."""
        return len(self.queue)

    @property
    def utilization_pct(self) -> float:
        """Current utilization as a percentage of max_size."""
        if self.max_size <= 0:
            return 100.0
        return (len(self.queue) / self.max_size) * 100.0
