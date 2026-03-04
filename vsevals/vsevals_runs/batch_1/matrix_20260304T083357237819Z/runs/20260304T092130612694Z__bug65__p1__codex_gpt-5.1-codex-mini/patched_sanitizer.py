"""PII sanitizer for structured log fields.

This module provides text sanitization for log payloads before they are
persisted or forwarded to external aggregators.  It redacts emails,
phone numbers, and US SSNs so that PII never reaches long-term storage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Redaction patterns
# ---------------------------------------------------------------------------

# BUG_65: missing '+' in the local-part character class -- plus-addressed
# emails like user+tag@domain.com slip through unredacted.
_EMAIL_RE = re.compile(r"[\w.]+@[\w.]+")  # BUG_65: misses plus-addressing

_PHONE_RE = re.compile(
    r"\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
)

_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

_REDACTED_EMAIL = "[REDACTED_EMAIL]"
_REDACTED_PHONE = "[REDACTED_PHONE]"
_REDACTED_SSN = "[REDACTED_SSN]"


@dataclass
class SanitizationResult:
    """Outcome of a single sanitize pass."""

    text: str
    emails_redacted: int = 0
    phones_redacted: int = 0
    ssns_redacted: int = 0

    @property
    def total_redacted(self) -> int:
        return self.emails_redacted + self.phones_redacted + self.ssns_redacted


@dataclass
class PiiSanitizer:
    """Redacts PII tokens from free-form text.

    Intended for pre-persist log sanitization so that PII never
    reaches the log aggregator or downstream analytics pipelines.
    """

    redact_emails: bool = True
    redact_phones: bool = True
    redact_ssns: bool = True
    _history: list[SanitizationResult] = field(
        default_factory=list, repr=False
    )

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

        # BUG_65: _EMAIL_RE misses plus-addressed emails
        email_re = re.compile(r"[\w.+]+@[\w.]+")
        result = email_re.sub(_REDACTED_EMAIL, text)
        count = len(email_re.findall(text))
        self._history.append(
            SanitizationResult(text=result, emails_redacted=count)
        )
        return result

    def sanitize_phone(self, text: str) -> str:
        """Replace US phone numbers with ``[REDACTED_PHONE]``."""
        result = _PHONE_RE.sub(_REDACTED_PHONE, text)
        count = len(_PHONE_RE.findall(text))
        self._history.append(
            SanitizationResult(text=result, phones_redacted=count)
        )
        return result

    def sanitize_ssn(self, text: str) -> str:
        """Replace US SSNs (xxx-xx-xxxx) with ``[REDACTED_SSN]``."""
        result = _SSN_RE.sub(_REDACTED_SSN, text)
        count = len(_SSN_RE.findall(text))
        self._history.append(
            SanitizationResult(text=result, ssns_redacted=count)
        )
        return result

    def sanitize_all(self, text: str) -> SanitizationResult:
        """Run every enabled redaction pass and return aggregated result."""
        emails = phones = ssns = 0
        if self.redact_emails:
            emails = len(_EMAIL_RE.findall(text))
            text = _EMAIL_RE.sub(_REDACTED_EMAIL, text)
        if self.redact_phones:
            phones = len(_PHONE_RE.findall(text))
            text = _PHONE_RE.sub(_REDACTED_PHONE, text)
        if self.redact_ssns:
            ssns = len(_SSN_RE.findall(text))
            text = _SSN_RE.sub(_REDACTED_SSN, text)
        result = SanitizationResult(
            text=text,
            emails_redacted=emails,
            phones_redacted=phones,
            ssns_redacted=ssns,
        )
        self._history.append(result)
        return result
