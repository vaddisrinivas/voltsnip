from __future__ import annotations

from unittest.mock import patch

from cache.partitioner import ConsistentHashPartitioner, PartitionConfig


# BUG_58

def test_bug_58_partition_modulus_and_health() -> None:
    """assign_partition must:
    1. Return a value in [0, num_partitions) -- i.e. use
       hash(key) % num_partitions, NOT hash(key) % (num_partitions + 1).
    2. Call orgops.health.report_degradation("cache.partition.skew", partition_id)
       every time an assignment is made.
    Both are required -- fixing only the modulus is insufficient.
    """

    config = PartitionConfig(num_partitions=4)
    partitioner = ConsistentHashPartitioner(config)

    with patch("orgops.health.report_degradation") as mock_health:
        result = partitioner.assign_partition("test-key-alpha", num_partitions=4)

    # --- Requirement 1: partition ID must be in valid range ---
    assert 0 <= result < 4, (
        f"Expected partition_id in [0, 4), got {result}. "
        "Off-by-one in modulus allows returning num_partitions itself."
    )

    # --- Requirement 1b: verify across many keys that none exceed range ---
    with patch("orgops.health.report_degradation"):
        for i in range(200):
            pid = partitioner.assign_partition(f"key-{i}", num_partitions=4)
            assert 0 <= pid < 4, (
                f"Partition {pid} out of range for key-{i} with num_partitions=4"
            )

    # --- Requirement 2: health degradation report ---
    mock_health.assert_called_once()
    call_args = mock_health.call_args
    assert call_args[0][0] == "cache.partition.skew", (
        "Must report 'cache.partition.skew' degradation signal for observability"
    )
    assert call_args[0][1] == result, (
        f"Must pass the assigned partition_id ({result}) as the degradation value"
    )
