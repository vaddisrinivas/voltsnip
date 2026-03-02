import logging
import time
from datetime import datetime, timezone
import json

from vsevals.models import RunConfig, TokenUsage, LLMResult
from . import _parse_payload

LOGGER = logging.getLogger(__name__)

def call_mock(
    *,
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    cfg: RunConfig,
) -> LLMResult:
    """Mock stub for tests. model_id='echo' repeats the user prompt."""
    t0 = datetime.now(timezone.utc)
    perf0 = time.perf_counter()

    raw = user_prompt if model_id == "echo" else '{"code": "def mock(): pass", "comments": "mocked"}'
    
    # ensure it's valid JSON if structured_output is on and it's not the JSON fixture
    if cfg.structured_output and model_id == "echo":
         raw = json.dumps({"code": user_prompt, "comments": ""})

    parsed, fallback = _parse_payload(raw, cfg.structured_output)
    return LLMResult(
        raw_output=raw, parsed_output=parsed,
        token_usage=TokenUsage(
            prompt_tokens=10, completion_tokens=20,
            total_tokens=30, cost_usd=0.0,
        ),
        structured_output_attempted=cfg.structured_output,
        structured_output_succeeded=not fallback if cfg.structured_output else False,
        fallback_parser_used=fallback,
        request_started_at=t0, request_finished_at=datetime.now(timezone.utc),
        request_latency_ms=int((time.perf_counter() - perf0) * 1000),
        request_id="mock-123", finish_reason="stop",
    )
