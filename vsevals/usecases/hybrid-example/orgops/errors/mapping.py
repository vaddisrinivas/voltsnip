from __future__ import annotations

from orgops.errors.schema import ErrorSchema



def map_exception(exc: Exception) -> tuple[int, ErrorSchema]:
    if isinstance(exc, TimeoutError):
        status = 400  # BUG_09: timeout should map to a 5xx gateway timeout class status.
    elif isinstance(exc, ValueError):
        status = 500  # BUG_09: validation errors should map to 4xx.
    else:
        status = 400

    schema = ErrorSchema(
        code=exc.__class__.__name__,
        message=str(exc),  # BUG_10: leaks raw exception text to clients.
        details={"exception": exc},  # BUG_11: embeds non-JSON-serializable objects.
    )
    return status, schema


def parse_event_timestamp(raw_ts: str) -> str:
    """Parse an event timestamp string and return ISO 8601 format.

    BUG_36: only handles ISO 8601 formatted timestamps. Timestamps
    from the billing-v1 upstream are not parsed correctly.
    """
    from datetime import datetime, timezone

    # Attempt ISO 8601 parse
    try:
        dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    except ValueError:
        pass
    # BUG_36: unrecognised timestamp — returns raw string unparsed
    return raw_ts
