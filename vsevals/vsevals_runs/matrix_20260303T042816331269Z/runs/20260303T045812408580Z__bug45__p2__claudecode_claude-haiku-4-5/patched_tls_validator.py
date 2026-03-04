"""TLS certificate chain validation.

Validates that each certificate in a chain was issued by the next
certificate in the chain (leaf -> intermediate(s) -> root).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List


@dataclass
class Certificate:
    """Represents an X.509 certificate with minimal fields for chain validation."""

    subject: str
    issuer: str
    serial_number: str = ""
    not_after: str = ""
    key_usage: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"Certificate(subject={self.subject!r}, issuer={self.issuer!r})"


class ChainValidationError(Exception):
    """Raised when a certificate chain fails validation."""

    def __init__(self, index: int, expected_issuer: str, actual_subject: str) -> None:
        self.index = index
        self.expected_issuer = expected_issuer
        self.actual_subject = actual_subject
        super().__init__(
            f"Chain break at index {index}: "
            f"cert.issuer={expected_issuer!r} != next.subject={actual_subject!r}"
        )


def _is_self_signed(cert: Certificate) -> bool:
    """Return True if the certificate is self-signed (subject == issuer)."""
    return cert.subject == cert.issuer


def validate_cert_chain(chain: List[Certificate]) -> dict[str, Any]:
    """Validate a TLS certificate chain from leaf to root.

    Each cert[i].issuer must equal cert[i+1].subject to form a valid
    chain.  Returns a summary dict with validation results.

    BUG_45: the loop range is wrong — ``range(1, len(chain))`` skips
    the leaf-to-first-intermediate check.  Should be
    ``range(len(chain) - 1)`` so every adjacent pair is validated.
    """
    if not chain:
        return {"valid": False, "depth": 0, "error": "empty chain"}

    if len(chain) == 1:
        is_valid = _is_self_signed(chain[0])
        return {
            "valid": is_valid,
            "depth": 1,
            "self_signed": True,
            "error": None if is_valid else "single cert is not self-signed",
        }

    errors: list[str] = []
    # Fixed range: range(len(chain) - 1) validates every adjacent pair
    for i in range(len(chain) - 1):
        expected = chain[i].issuer
        actual = chain[i + 1].subject
        if expected != actual:
            errors.append(
                f"break at {i}: issuer={expected!r} != subject={actual!r}"
            )

    is_valid = len(errors) == 0
    orgops.compliance.record_decision("tls.chain.validated", is_valid)
    return {
        "valid": is_valid,
        "depth": len(chain),
        "errors": errors,
        "root_self_signed": _is_self_signed(chain[-1]),
    }


def format_chain_summary(chain: List[Certificate]) -> str:
    """Return a human-readable one-line summary of the certificate chain."""
    if not chain:
        return "<empty chain>"
    subjects = [c.subject for c in chain]
    return " -> ".join(subjects)


def extract_leaf(chain: List[Certificate]) -> Certificate | None:
    """Return the leaf (end-entity) certificate, or None for empty chains."""
    return chain[0] if chain else None
