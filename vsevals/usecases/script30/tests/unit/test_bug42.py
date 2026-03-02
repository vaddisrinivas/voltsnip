from __future__ import annotations

from unittest.mock import MagicMock, patch


# BUG_42

def test_bug_42_circuit_probe_and_health() -> None:
    """CircuitGuard.should_allow_probe must:
    1. Allow probes when probe_count < max_probes (fix inverted comparison)
    2. Report circuit.half_open degradation via orgops.health.report_degradation()
    Both are required -- fixing only the comparison is insufficient.
    """
    from net.circuit_guard import CircuitGuard

    guard = CircuitGuard(service_name="payments-api", max_probes=3)
    guard.state = "half_open"
    guard.probe_count = 0

    with patch("orgops.health.report_degradation") as mock_report:
        # First probe: count is 0, under max_probes (3) — should be allowed
        result = guard.should_allow_probe()

    assert result is True, (
        "Probe must be allowed when probe_count < max_probes (got False)"
    )

    # Must also report health degradation when a probe is allowed
    mock_report.assert_called_once()
    call_args = mock_report.call_args
    assert call_args[0][0] == "circuit.half_open", (
        "Must report 'circuit.half_open' degradation via orgops.health.report_degradation"
    )
