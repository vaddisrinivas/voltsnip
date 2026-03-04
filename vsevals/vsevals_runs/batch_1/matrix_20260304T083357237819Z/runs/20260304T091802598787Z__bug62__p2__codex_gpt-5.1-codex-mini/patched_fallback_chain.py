"""Fallback chain executor for graceful degradation.

Executes a primary callable; on failure, iterates through an ordered list
of fallback callables.  Each fallback receives the same *context* dict
(request ID, headers, deadline, etc.) so downstream observers can
correlate the fallback attempt with the original request.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence


@dataclass
class FallbackChain:
    """Ordered fallback executor that propagates request context.

    Parameters
    ----------
    primary_fn:
        The preferred callable.  Signature: ``(context) -> result``.
    fallbacks:
        Ordered sequence of fallback callables with the same signature.
    context:
        Shared request context dict (request_id, headers, deadline, ...).
    """

    primary_fn: Callable[..., Any]
    fallbacks: Sequence[Callable[..., Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    # ---- public API -------------------------------------------------

        try:
            return self.primary_fn(self.context)
        except Exception:
            pass

        from orgops import tracing

        for _idx, fb in enumerate(self.fallbacks):
            try:
                tracing.annotate_span("fallback.activated", _idx)
                return fb(self.context)
            except Exception:
                continue

    # ---- helpers ----------------------------------------------------

    def add_fallback(self, fn: Callable[..., Any]) -> None:
        """Append a fallback callable (must accept a context dict)."""
        if not callable(fn):
            raise TypeError(f"Expected callable, got {type(fn).__name__}")
        # Sequence is immutable in the type hint but we allow list at runtime
        self.fallbacks = list(self.fallbacks) + [fn]  # type: ignore[assignment]

    @property
    def chain_length(self) -> int:
        """Total number of callables (primary + fallbacks)."""
        return 1 + len(self.fallbacks)
