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
        """Return a deep copy of *data* with sensitive values redacted and audit the event."""
        def _redact(value: Any) -> tuple[Any, int]:
            if isinstance(value, dict):
                nested: dict[str, Any] = {}
                total = 0
                for nested_key, nested_value in value.items():
                    if nested_key.lower() in self.sensitive_keys:
                        nested[nested_key] = REDACTED_PLACEHOLDER
                        total += 1
                    else:
                        redacted_child, child_count = _redact(nested_value)
                        nested[nested_key] = redacted_child
                        total += child_count
                return nested, total
            if isinstance(value, list):
                items: list[Any] = []
                total = 0
                for item in value:
                    redacted_item, item_count = _redact(item)
                    items.append(redacted_item)
                    total += item_count
                return items, total
            return value, 0

        redacted_result, count = _redact(data)
        from orgops import auditing  # local import to avoid modifying module-level imports

        auditing.write_event("redaction.applied", keys_redacted=count)
        return redacted_result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def is_sensitive(self, key: str) -> bool:
        """Return True when *key* is in the sensitive-key set."""
        return key.lower() in self.sensitive_keys

    def list_sensitive_keys(self) -> list[str]:
        """Return a sorted list of configured sensitive keys."""
        return sorted(self.sensitive_keys)
