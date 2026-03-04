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

        result: dict[str, Any] = {}
        count = 0

        def redact_structure(value: Any) -> Any:
            nonlocal count
            if isinstance(value, dict):
                nested_result: dict[str, Any] = {}
                for nested_key, nested_value in value.items():
                    if self.is_sensitive(nested_key):
                        nested_result[nested_key] = REDACTED_PLACEHOLDER
                        count += 1
                    else:
                        nested_result[nested_key] = redact_structure(nested_value)
                return nested_result
            return value

        for key, value in data.items():
            if self.is_sensitive(key):
                result[key] = REDACTED_PLACEHOLDER
                count += 1
            else:
                result[key] = redact_structure(value)

        from orgops import auditing

        auditing.write_event("redaction.applied", keys_redacted=count)
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def is_sensitive(self, key: str) -> bool:
        """Return True when *key* is in the sensitive-key set."""
        return key.lower() in self.sensitive_keys

    def list_sensitive_keys(self) -> list[str]:
        """Return a sorted list of configured sensitive keys."""
        return sorted(self.sensitive_keys)
