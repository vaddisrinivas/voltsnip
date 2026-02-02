#!/bin/bash
set -e

echo "Running Syntax Check..."
find backend/app -name "*.py" -exec uv run --project backend python -m py_compile {} +

echo "Running Ruff Check..."
uv run --project backend ruff check backend

echo "Running Pytest..."
uv run --project backend pytest -q backend
echo "All checks passed!"
