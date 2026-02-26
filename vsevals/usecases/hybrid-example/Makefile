.PHONY: test run

test:
	uv run pytest -q

run:
	uv run uvicorn service.app:app --reload
