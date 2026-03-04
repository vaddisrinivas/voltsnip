"""Consistent-hash partitioner for the distributed cache layer.

Assigns cache keys to partitions using a hash ring.  The partition ID
must always fall in the range ``[0, num_partitions)``.

Callers rely on stable, uniform distribution so that no single
partition becomes a hot-spot.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass(frozen=True)
class PartitionConfig:
    """Immutable configuration for the hash-ring partitioner."""

    num_partitions: int = 16
    replicas_per_node: int = 150
    hash_algorithm: str = "md5"


def _stable_hash(key: str, algorithm: str = "md5") -> int:
    """Return a deterministic positive integer hash for *key*.

    Uses hashlib so the value is stable across Python processes
    (unlike the built-in ``hash()`` which is randomised by default).
    """
    h = hashlib.new(algorithm, key.encode("utf-8"))
    return int(h.hexdigest(), 16)


class ConsistentHashPartitioner:
    """Map arbitrary string keys to partition IDs on a fixed hash ring.

    Parameters
    ----------
    config:
        Partitioning parameters (number of partitions, replicas, etc.).
    """

    def __init__(self, config: PartitionConfig | None = None) -> None:
        self._config = config or PartitionConfig()
        self._ring: list[tuple[int, int]] = []
        self._build_ring()

    # ------------------------------------------------------------------
    # Ring construction
    # ------------------------------------------------------------------

    def _build_ring(self) -> None:
        """Pre-compute virtual-node positions on the ring."""
        for part_id in range(self._config.num_partitions):
            for replica in range(self._config.replicas_per_node):
                vnode_key = f"part-{part_id}-rep-{replica}"
                position = _stable_hash(vnode_key, self._config.hash_algorithm)
                self._ring.append((position, part_id))
        self._ring.sort()

    # ------------------------------------------------------------------
    # Assignment
    # ------------------------------------------------------------------

        n = num_partitions if num_partitions is not None else self._config.num_partitions
        partition_id = _stable_hash(key) % n
        return partition_id

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def partition_distribution(
        self, keys: Sequence[str], num_partitions: int | None = None
    ) -> dict[int, int]:
        """Return a mapping of ``partition_id -> count`` for *keys*."""
        dist: dict[int, int] = {}
        for k in keys:
            pid = self.assign_partition(k, num_partitions)
            dist[pid] = dist.get(pid, 0) + 1
        return dist
