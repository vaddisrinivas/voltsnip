from __future__ import annotations

import httpx

from orgops.http import OrgHTTPClient, RetryPolicy


def make_http_client() -> OrgHTTPClient:
    return OrgHTTPClient(client=httpx.Client(), retry_policy=RetryPolicy())
