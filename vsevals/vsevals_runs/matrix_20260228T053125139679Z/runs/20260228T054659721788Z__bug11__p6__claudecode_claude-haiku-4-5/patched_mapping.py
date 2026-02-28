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
        details={},
    )
    return status, schema
