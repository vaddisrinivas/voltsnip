"""Core data models for the vsevals harness."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    from vsevals.execution_trace import ExecutionTrace

LOGGER = logging.getLogger(__name__)


class SuiteMeta(BaseModel):
    version: str
    description: str | None = None
    usecase_id: str | None = None
    usecase_manifest: str | None = None
    default_repo_root: str | None = None
    pytest_docker_image: str | None = None
    pytest_docker_workdir: str | None = None


class VariantConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(..., min_length=1)
    mode: Literal["direct", "agent"]
    memory_enabled: bool
    tools_enabled: bool
    retrieval_mode: Literal["injected", "agent_decides", "none"]
    instruction_mode: Literal["none", "explicit"]
    context_surface: Literal["system", "user", "tools_only", "skills_md_no_keys", "agents_md_no_keys", "skills_agents_md_no_keys"]
    max_tool_roundtrips: int = Field(default=4, ge=1, le=32)
    include_oracle: bool = False
    note: str | None = None
    purpose: str | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> "VariantConfig":
        if self.context_surface == "tools_only" and not self.tools_enabled:
            raise ValueError("context_surface=tools_only requires tools_enabled=true")
        if self.retrieval_mode == "agent_decides" and not self.tools_enabled:
            raise ValueError("retrieval_mode=agent_decides requires tools_enabled=true")
        return self


class TaskVisible(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str | None = None
    category: str | None = None
    difficulty: str | None = None
    user_prompt: str = Field(..., min_length=1)
    context_code: str | None = None
    expected_output: str | None = None
    repo_root: str | None = None
    target_file: str | None = None
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    test_command: str | None = None

    @model_validator(mode="after")
    def _check_line_range(self) -> "TaskVisible":
        if (self.line_start is None) != (self.line_end is None):
            raise ValueError("line_start and line_end must be provided together")
        if self.line_start is not None and self.line_end is not None and self.line_end < self.line_start:
            raise ValueError("line_end must be >= line_start")
        return self


class TaskVoltsnipConfig(BaseModel):
    required_snippets: list[str] = Field(default_factory=list)
    snippet_context_limit: int = Field(default=6, ge=1, le=50)
    snippet_context_max_chars: int = Field(default=8000, ge=100, le=100000)


class SuccessIndicators(BaseModel):
    correctness: list[str] = Field(default_factory=list)
    consistency: list[str] = Field(default_factory=list)
    completeness: list[str] = Field(default_factory=list)
    cost_efficiency: list[str] = Field(default_factory=list)
    memory_usage: list[str] = Field(default_factory=list)

    def as_lines(self) -> list[str]:
        return [f"{k}: {v}" for k, vals in self.model_dump(mode="python").items() for v in vals]


class OracleConstraint(BaseModel):
    id: str = Field(..., min_length=1)
    voltsnip_key: str | None = None
    check: str = Field(..., min_length=1)
    judge_prompt: str = Field(..., min_length=1)
    expected: bool = True
    trap_baseline: float | None = Field(default=None, ge=0.0, le=1.0)


class TaskOracle(BaseModel):
    hidden_requirements: list[str] = Field(default_factory=list)
    success_indicators: SuccessIndicators = Field(default_factory=SuccessIndicators)
    failure_modes: list[str] = Field(default_factory=list)
    evaluation_criteria: list[str] = Field(default_factory=list)
    constraints: list[OracleConstraint] = Field(default_factory=list)


class SuiteTask(BaseModel):
    task: TaskVisible
    voltsnip: TaskVoltsnipConfig = Field(default_factory=TaskVoltsnipConfig)
    oracle: TaskOracle = Field(default_factory=TaskOracle)

    @property
    def id(self) -> str:
        return self.task.id


class SuiteConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    suite: SuiteMeta
    models: list[dict]
    variants: list[VariantConfig]
    tasks: list[SuiteTask] = Field(default_factory=list)
    task_files: list[str] = Field(default_factory=list)

    @field_validator("models", mode="before")
    @classmethod
    def _normalize_models(cls, raw: object) -> object:
        if not isinstance(raw, list):
            raise TypeError("models must be a list")
        normalized: list[dict] = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                normalized.append({"name": item.strip()})
            elif isinstance(item, dict):
                name = item.get("name") or item.get("model") or item.get("model_name")
                if isinstance(name, str) and name.strip():
                    normalized.append({"name": name.strip()})
        return normalized

    @model_validator(mode="after")
    def _check_unique(self) -> "SuiteConfig":
        _assert_unique([str(r.get("name", "")) for r in self.models], "models")
        _assert_unique([r.id for r in self.variants], "variants")
        _assert_unique([r.id for r in self.tasks], "tasks")
        return self

    @property
    def task_map(self) -> dict[str, SuiteTask]:
        return {t.id: t for t in self.tasks}

    @property
    def variant_map(self) -> dict[str, VariantConfig]:
        return {v.id: v for v in self.variants}

    @property
    def model_names(self) -> list[str]:
        return [str(r.get("name", "")) for r in self.models]


class RetrievedSnippet(BaseModel):
    id: str
    canonical_key: str | None = None
    title: str = ""
    language: str | None = None
    tags: list[str] = Field(default_factory=list)
    description: str | None = None
    code: str = ""


class PromptBundle(BaseModel):
    system_prompt: str
    user_prompt: str
    context_surface: Literal["system", "user", "tools_only", "skills_md_no_keys", "agents_md_no_keys", "skills_agents_md_no_keys"]
    visible_sections: list[str] = Field(default_factory=list)
    injected_snippet_keys: list[str] = Field(default_factory=list)
    injected_repo_policy: bool = False
    sidecar_files: dict[str, str] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int = 0
    thinking_tokens: int | None = None
    cost_usd: float | None = None


class MessageTrace(BaseModel):
    role: str
    content: str


class ToolTrace(BaseModel):
    roundtrip: int
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_args: dict = Field(default_factory=dict)
    tool_result: object | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None


class TimingInfo(BaseModel):
    started_at: datetime
    finished_at: datetime
    latency_ms: int


class RunArtifactPaths(BaseModel):
    run_dir: str
    full_dump_json: str
    summary_dump_json: str
    code_output: str
    comments_output: str


class SummaryMetrics(BaseModel):
    latency_ms: int
    prompt_chars: int
    output_chars: int
    prompt_system_chars: int = 0
    prompt_user_chars: int = 0
    snippet_injected_chars: int = 0
    model_provider: str | None = None
    model_id: str | None = None
    snippet_count: int = 0
    tool_call_count: int = 0
    voltsnip_tool_call_count: int = 0
    native_tool_call_count: int = 0
    tool_error_count: int = 0
    used_tools: bool = False
    used_voltsnip_tools: bool = False
    structured_output_attempted: bool = False
    structured_output_succeeded: bool = False
    fallback_parser_used: bool = False
    retrieval_latency_ms: int | None = None
    voltsnip_retry_count: int = 0
    voltsnip_rate_limit_count: int = 0
    voltsnip_timeout_count: int = 0
    voltsnip_error_count: int = 0
    model_request_latency_ms: int | None = None
    model_request_started_at: datetime | None = None
    model_request_finished_at: datetime | None = None
    model_request_id: str | None = None
    model_finish_reason: str | None = None
    scoring_latency_ms: int | None = None
    artifact_write_latency_ms: int | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class GeneratedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    comments: str = ""


class RunError(BaseModel):
    type: str
    message: str
    error_class: str = "UNKNOWN_ERROR"


class PytestResult(BaseModel):
    ran: bool = False
    returncode: int | None = None
    passed: bool = False
    stdout: str = ""
    stderr: str = ""
    duration_ms: int | None = None
    error: str | None = None
    docker_image: str | None = None
    patched_file: str | None = None


class ScoreDimension(BaseModel):
    matched: int
    total: int
    score: float = Field(ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list)


class ScoreResult(BaseModel):
    overall_score: float = Field(ge=0.0, le=1.0)
    hidden_requirements: ScoreDimension
    success_indicators: ScoreDimension
    failure_modes: ScoreDimension
    evaluation_criteria: ScoreDimension = Field(
        default_factory=lambda: ScoreDimension(matched=0, total=0, score=1.0, notes=[])
    )
    evaluation_criteria_notes: list[str] = Field(default_factory=list)
    constraint_scoring_used: bool = False
    constraint_checks_passed: int | None = None
    constraint_checks_total: int | None = None
    constraint_pass_threshold: float | None = None
    constraint_results: list[dict] = Field(default_factory=list)
    judge_payload: dict | None = None
    judge_raw_response: str | None = None
    passed: bool


class RunResult(BaseModel):
    run_id: str
    suite_path: str
    output_root: str
    task_id: str
    task_name: str
    variant_id: str
    model_name: str
    status: Literal["ok", "error"]
    variant_mode: str = "direct"
    variant_memory_enabled: bool = False
    variant_tools_enabled: bool = False
    variant_retrieval_mode: str = "none"
    variant_instruction_mode: str = "none"
    variant_context_surface: str = "system"
    variant_max_tool_roundtrips: int = 4
    task_category: str | None = None
    task_difficulty: str | None = None
    task_line_start: int | None = None
    task_line_end: int | None = None
    required_snippet_keys: list[str] = Field(default_factory=list)
    prompt: PromptBundle
    prompt_after_tools: PromptBundle | None = None
    retrieved_snippets: list[RetrievedSnippet] = Field(default_factory=list)
    messages: list[MessageTrace] = Field(default_factory=list)
    tool_traces: list[ToolTrace] = Field(default_factory=list)
    raw_model_output: str = ""
    parsed_output: GeneratedPayload = Field(default_factory=lambda: GeneratedPayload(code="", comments=""))
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    execution_trace: object | None = Field(default=None, description="ExecutionTrace for dynamic tour generation")
    timings: TimingInfo
    summary_metrics: SummaryMetrics
    artifacts: RunArtifactPaths
    score: ScoreResult | None = None
    pytest_result: PytestResult | None = None
    error: RunError | None = None


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    temperature: float = 0.0
    max_tokens: int | None = Field(default=None, ge=1)
    structured_output: bool = True
    reasoning_effort: str | None = None
    llm_runtime: Literal["native_sdk", "auto"] = "native_sdk"
    api_key: str | None = None
    provider_api_keys: dict[str, str] = Field(default_factory=dict)
    voltsnip_base_url: str | None = None
    voltsnip_timeout_seconds: int = Field(default=20, ge=1)
    voltsnip_retry_attempts: int = Field(default=3, ge=1, le=10)
    snippet_context_limit: int | None = Field(default=None, ge=1, le=50)
    snippet_context_max_chars: int | None = Field(default=None, ge=100, le=20000)
    scoring_match_mode: Literal["lexical", "hybrid", "llm"] = "hybrid"
    scoring_primary_endpoint: Literal["auto", "constraint_binary", "legacy_weighted"] = "auto"
    auto_constraints_from_legacy_oracle: bool = True
    scoring_judge_model: str = "openai:gpt-5-mini"
    scoring_judge_max_tokens: int = Field(default=800, ge=64, le=8192)
    constraint_pass_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    judge_prompt_variant: Literal["verdict-true", "verdict-false", "none", "both", "pre-67f6ed0"] = "both"
    skip_scoring: bool = False
    auto_apply_patch: bool = False
    pytest_docker_image: str = "moltsnip-pytest:latest"
    pytest_docker_workdir: str = "/workspace"
    pytest_timeout_seconds: int = Field(default=300, ge=1)
    llm_timeout_seconds: int = Field(default=300, ge=10)
    repo_policy_text: str | None = None


def _assert_unique(values: list[str], label: str) -> None:
    seen: set[str] = set()
    dups = {v for v in values if (k := v.strip().lower()) in seen or seen.add(k)}  # type: ignore[func-returns-value]
    if dups:
        raise ValueError(f"duplicate {label}: {', '.join(sorted(dups))}")


_PRICING: dict[str, tuple[float, float]] = {
    "gpt-5.2":            (15.00,  60.00),
    "gpt-5":              (15.00,  60.00),
    "gpt-5.3-codex":      (15.00,  60.00),
    "gpt-5.2-codex":      (15.00,  60.00),
    "gpt-5.1-codex":      (15.00,  60.00),
    "gpt-5.1-codex-mini": ( 0.40,   1.60),
    "gpt-5-mini":         ( 0.40,   1.60),
    "gpt-5-nano":         ( 0.10,   0.40),
    "gpt-4o":             ( 2.50,  10.00),
    "gpt-4o-mini":        ( 0.15,   0.60),
    "o3":                 (10.00,  40.00),
    "o3-mini":            ( 1.10,   4.40),
    "o1":                 (15.00,  60.00),
    "o1-mini":            ( 3.00,  12.00),
    "claude-opus-4-6":    (15.00,  75.00),
    "claude-opus-4-5":    (15.00,  75.00),
    "claude-sonnet-4-6":  ( 3.00,  15.00),
    "claude-sonnet-4-5":  ( 3.00,  15.00),
    "claude-haiku-4-5":   ( 0.80,   4.00),
    "claude-haiku-4-4":   ( 0.25,   1.25),
}


def compute_cost(model_id: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0) -> float | None:
    pricing = _PRICING.get(model_id)
    if pricing is None:
        LOGGER.warning("No pricing entry for model %r — cost will be None", model_id)
        return None
    in_rate, out_rate = pricing
    if cached_tokens > 0:
        cache_rate = in_rate * (0.10 if "claude" in model_id else 0.50)
        cost = (max(0, prompt_tokens - cached_tokens) * in_rate + cached_tokens * cache_rate + completion_tokens * out_rate) / 1_000_000
    else:
        cost = (prompt_tokens * in_rate + completion_tokens * out_rate) / 1_000_000
    return round(cost, 8)


class LLMResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    raw_output: str
    parsed_output: GeneratedPayload
    token_usage: TokenUsage
    structured_output_attempted: bool
    structured_output_succeeded: bool
    fallback_parser_used: bool
    request_started_at: datetime | None
    request_finished_at: datetime | None
    request_latency_ms: int | None
    request_id: str | None
    finish_reason: str | None
    tool_traces: list[ToolTrace] = Field(default_factory=list)
    subprocess_stdout: str = ""
    subprocess_stderr: str = ""
    api_response_raw: str = ""


def parse_model(model_name: str) -> tuple[str, str]:
    provider, model_id = model_name.split(":", 1) if ":" in model_name else ("openai", model_name)
    norm = {"openai": "openai", "anthropic": "anthropic", "claudecode": "claudecode", "codex": "codex", "mock": "mock"}.get(
        provider.strip().lower(), provider.strip().lower()
    )
    model_id_stripped = model_id.strip()
    if not model_id_stripped:
        raise ValueError(f"Invalid model name {model_name!r}: model_id portion is empty. Expected format: 'provider:model_id' or just 'model_id'.")
    return norm, model_id_stripped


def resolve_key(provider: str, cfg: RunConfig, provider_keys: dict[str, str]) -> str | None:
    import os
    if cfg.api_key:
        return cfg.api_key
    if provider in cfg.provider_api_keys:
        return cfg.provider_api_keys[provider]
    if provider == "openai":
        return os.environ.get("OPENAI_API_KEY")
    if provider == "anthropic":
        return os.environ.get("ANTHROPIC_API_KEY")
    return None
