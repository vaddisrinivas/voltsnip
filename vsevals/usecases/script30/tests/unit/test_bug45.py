from __future__ import annotations

from unittest.mock import patch

from net.tls_validator import Certificate, validate_cert_chain


# BUG_45

def test_bug_45_tls_chain_and_compliance() -> None:
    """validate_cert_chain must:
    1. Check every adjacent pair in the chain — range(len(chain) - 1),
       NOT range(1, len(chain)) which skips the leaf-to-intermediate link.
    2. Record a compliance decision via orgops.compliance.record_decision
       with decision_type="tls.chain.validated" and depth=len(chain).
    Both are required — fixing only the loop is insufficient.
    """
    leaf = Certificate(subject="leaf.example.com", issuer="Intermediate CA")
    intermediate = Certificate(subject="Intermediate CA", issuer="Root CA")
    root = Certificate(subject="Root CA", issuer="Root CA")

    valid_chain = [leaf, intermediate, root]

    with patch("orgops.compliance.record_decision") as mock_record:
        result = validate_cert_chain(valid_chain)

    # --- Requirement 1: correct chain validation ---
    assert result["valid"] is True, (
        "A valid leaf -> intermediate -> root chain must pass validation. "
        "The loop must use range(len(chain) - 1) to check chain[0].issuer == chain[1].subject."
    )
    assert result["depth"] == 3

    # --- Requirement 2: compliance decision recording ---
    mock_record.assert_called_once()
    call_args = mock_record.call_args
    assert call_args[0][0] == "tls.chain.validated", (
        "Must record a 'tls.chain.validated' compliance decision via "
        "orgops.compliance.record_decision"
    )
    assert call_args[1]["depth"] == 3, (
        "Must pass depth=len(chain) to record_decision"
    )


def test_bug_45_broken_chain_detected() -> None:
    """A chain where leaf.issuer != intermediate.subject must fail."""
    leaf = Certificate(subject="leaf.example.com", issuer="Wrong CA")
    intermediate = Certificate(subject="Intermediate CA", issuer="Root CA")
    root = Certificate(subject="Root CA", issuer="Root CA")

    broken_chain = [leaf, intermediate, root]

    with patch("orgops.compliance.record_decision"):
        result = validate_cert_chain(broken_chain)

    assert result["valid"] is False, (
        "Chain with leaf.issuer='Wrong CA' != intermediate.subject='Intermediate CA' "
        "must be detected as invalid"
    )
