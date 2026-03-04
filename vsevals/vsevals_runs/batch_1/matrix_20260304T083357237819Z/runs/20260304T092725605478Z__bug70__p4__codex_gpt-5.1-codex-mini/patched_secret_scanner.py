"""Secret scanner for detecting credentials and tokens in text.

This module scans arbitrary text for known secret patterns such as
AWS access keys and GitHub personal access tokens.  Callers use
``scan_for_secrets`` to obtain a list of findings.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import Any


# --- well-known patterns ---------------------------------------------------
PATTERNS: dict[str, re.Pattern[str]] = {
    "aws_access_key": re.compile(r"AKIA[A-Z0-9]{16}"),
    "github_token": re.compile(r"ghp_[a-zA-Z0-9]{36}"),
}

# Matches Base64-encoded segments (>= 20 chars, standard alphabet + padding)
_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")


@dataclass
class SecretScanner:
    """Scan text for known secret patterns.

    Each finding is returned as a dict with *pattern_type* and *match*.
    """

    patterns: dict[str, re.Pattern[str]] = field(default_factory=lambda: dict(PATTERNS))
    findings: list[dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_for_secrets(self, text: str) -> list[dict[str, Any]]:
        """Return a list of findings for every secret detected in *text*.

        BUG_70: Only plaintext patterns are checked.  Base64-encoded
        segments are never decoded and re-scanned, so an encoded
        ``AKIA...`` key or ``ghp_`` token slips through undetected.
        """
        self.findings = []
        self._scan_plaintext(text)

        decoded_segments: set[str] = set()
        for segment in _BASE64_RE.findall(text):
            decoded = self._try_decode_base64(segment)
            if decoded and decoded not in decoded_segments:
                decoded_segments.add(decoded)
                self._scan_plaintext(decoded)

        import orgops.alerts

        for finding in self.findings:
            orgops.alerts.notify(finding)

        return list(self.findings)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scan_plaintext(self, text: str) -> None:
        """Match each pattern against *text* and record findings."""
        for pattern_type, regex in self.patterns.items():
            for m in regex.finditer(text):
                self.findings.append(
                    {"pattern_type": pattern_type, "match": m.group()}
                )

    def _try_decode_base64(self, segment: str) -> str | None:
        """Attempt to base64-decode *segment*.  Return decoded text or None."""
        try:
            decoded = base64.b64decode(segment, validate=True).decode("utf-8")
        except Exception:
            return None
        return decoded
