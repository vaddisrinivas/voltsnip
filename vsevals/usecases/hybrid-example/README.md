# Hybrid OrgOps + FastAPI Example

This target is an intentionally buggy evaluation fixture for VoltSnip + DebugMate workflows.

## What this contains

- `orgops/`: a small internal SDK with HTTP helpers, logging utilities, error contracts, DB session helpers, and policy defaults.
- `service/`: a toy production-style FastAPI service that uses `orgops` for external calls, logging, error shaping, and request correlation.
- `tests/`: unit and integration tests designed to expose each bug marker (`BUG_01` .. `BUG_22`).

## Run locally

```bash
cd /Users/srinivasvaddi/moltsnip/voltsnip-evals/usecases/hybrid-example
uv run pytest -q
```

Run service:

```bash
cd /Users/srinivasvaddi/moltsnip/voltsnip-evals/usecases/hybrid-example
uv run uvicorn service.app:app --reload
```

## Notes

- The code is intentionally incorrect in localized ways.
- Each bug has a small patch surface and corresponding test coverage.
