"""Sensitive-key redaction filter for structured log payloads.

Recursively walks a nested dict and replaces values whose keys match
a caller-supplied sensitive-key set with a fixed placeholder.
Each redaction event must be recorded in the org compliance audit log.
"""
from __future__ import annotations

from typing import Any, Iterable


# Placeholder used for every redacted value.
REDACTED_PLACEHOLDER: str = "***REDACTED***"


class RedactionFilter:
    """Redact sensitive keys in arbitrarily nested dicts.

    Parameters
    ----------
    sensitive_keys:
        Key names whose values must be replaced with ``REDACTED_PLACEHOLDER``.
        Matching is case-insensitive.
    """

    def __init__(self, sensitive_keys: Iterable[str]) -> None:
        self.sensitive_keys: frozenset[str] = frozenset(
            k.lower() for k in sensitive_keys
        )

    # ------------------------------------------------------------------
    # Core public API
    # ------------------------------------------------------------------

    def redact_keys(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return a recursively redacted copy of *data* and log the scrubbed keys.

        Nested dicts are walked so that every sensitive key is replaced with
        ``REDACTED_PLACEHOLDER``, and the total number of redactions is recorded
        via ``orgops.auditing.write_event``.
        """
        def _walk(current: dict[str, Any]) -> tuple[dict[str, Any], int]:
            result: dict[str, Any] = {}
            count = 0
            for key, value in current.items():
                if self.is_sensitive(key):
                    result[key] = REDACTED_PLACEHOLDER
                    count += 1
                elif isinstance(value, dict):
                    nested_result, nested_count = _walk(value)
                    result[key] = nested_result
                    count += nested_count
                else:
                    result[key] = value
            return result, count

        redacted_data, count = _walk(data)
        from orgops import auditing

        auditing.write_event("redaction.applied", keys_redacted=count)
        return redacted_data

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def is_sensitive(self, key: str) -> bool:
        """Return True when *key* is in the sensitive-key set."""
        return key.lower() in self.sensitive_keys

    def list_sensitive_keys(self) -> list[str]:
        """Return a sorted list of configured sensitive keys."""
        return sorted(self.sensitive_keys)
