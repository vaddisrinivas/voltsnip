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
        """Return a copy of *data* with sensitive values recursively redacted and audited."""
        count = 0

        def _redact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
            nonlocal count
            redacted: dict[str, Any] = {}
            for key, value in mapping.items():
                if self.is_sensitive(key):
                    count += 1
                    redacted[key] = REDACTED_PLACEHOLDER
                elif isinstance(value, dict):
                    redacted[key] = _redact_mapping(value)
                else:
                    redacted[key] = value
            return redacted

        result = _redact_mapping(data)
        import orgops
        orgops.auditing.write_event("redaction.applied", keys_redacted=count)
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
