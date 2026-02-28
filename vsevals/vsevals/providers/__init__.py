"""Base interfaces for LLM providers."""

from __future__ import annotations

import json
from typing import Any

from vsevals.models import RunConfig


def _parse_payload(text: str, structured: bool) -> tuple[Any, bool]:
    """Parse output into (dict, fallback_used).
    If structured=True, requires valid JSON. Otherwise, returns raw text.
    """
    if not structured:
        return {"code": text, "comments": ""}, False
    
    text = text.strip()
    if not text:
        return {"code": "", "comments": ""}, True
        
    # Standard parse
    try:
        if text.startswith("```") and text.endswith("```"):
            lines = text.split("\n")
            if len(lines) >= 2:
                text = "\n".join(lines[1:-1]).strip()
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "code" in parsed:
            return parsed, False
    except Exception:
        pass
        
    # Strategy 2: scan ALL balanced {..} blocks for one with a "code" key.
    # Continues past blocks that are valid JSON but lack "code", and past
    # Python dict literals that fail JSON parsing entirely.
    pos = 0
    while True:
        start = text.find('{', pos)
        if start == -1:
            break
        depth = 0
        in_str = False
        escape = False
        end = -1
        for i, ch in enumerate(text[start:], start):
            if in_str:
                if escape:
                    escape = False
                elif ch == '\\':
                    escape = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end == -1:
            break  # unbalanced remainder — give up
        try:
            parsed = json.loads(text[start:end + 1])
            if isinstance(parsed, dict) and "code" in parsed:
                return parsed, False
        except Exception:
            pass
        pos = end + 1  # advance past this block and keep looking

    # No fallback: structured output is required.
    # Return empty code so the scorer's empty-code guard fires (score=0.0, passed=False).
    return {"code": "", "comments": ""}, True


def _safe_response_json(resp: object) -> str:
    """Serialise an API response object to a JSON string for artifact storage."""
    try:
        fn = getattr(resp, "model_dump_json", None)
        if callable(fn):
            result = fn()
            if isinstance(result, str):
                return result
    except Exception:
        pass
    try:
        return json.dumps(vars(resp), default=str, ensure_ascii=False)
    except Exception:
        pass
    try:
        return str(resp)
    except Exception:
        return ""


def _int_or_none(val: object) -> int | None:
    """Convert to int or return None (handles 0, "", None, False gracefully)."""
    if val is None or val == "" or val is False:
        return None
    try:
        result = int(val)  # type: ignore[arg-type]
        return result if result > 0 else None
    except (TypeError, ValueError):
        return None
