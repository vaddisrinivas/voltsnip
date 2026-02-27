"""Core data models for the vsevals harness.

Hierarchy (top-down):
  SuiteConfig           — loaded from suite YAML; contains variants + tasks
    VariantConfig       — P0-P6a execution strategy
    SuiteTask
      TaskVisible       — task prompt, target file, line range
      TaskVoltsnipConfig — snippet keys, limits
      TaskOracle        — scoring criteria (constraints, hidden_requirements …)

Execution:
  RunResult             — full output of a single run_one() call
    PromptBundle        — assembled system + user prompts
    RetrievedSnippet    — snippets fetched from VoltSnip
    ToolTrace           — per-roundtrip tool call record
    TokenUsage / TimingInfo / RunArtifactPaths

Scoring:
  ScoreResult           — final score (constraint binary or legacy weighted)
    ScoreDimension      — per-dimension matched/total/score
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Suite configuration
# ---------------------------------------------------------------------------


class SuiteMeta(BaseModel):
    version: str
    description: str | None = None
    usecase_id: str | None = None
    usecase_manifest: str | None = None
    default_repo_root: str | None = None
    # Populated by loader from usecase.yaml when present
    pytest_docker_image: str | None = None
    pytest_docker_workdir: str | None = None


class VariantConfig(BaseModel):
    """Execution strategy for one hypothesis (P0–P6b).

    P0   direct / no memory / no tools          — baseline
    P1   direct / no memory / no tools          — explicit instruction only
    P2   agent  / injected memory               — implicit guidance
    P3   agent  / injected memory               — explicit guidance
    P4   agent  / tools only                    — raw tool use, zero guidance
    P5b  agent  / tools + skill docs (no keys)  — knows how to use VoltSnip, not which keys
    P5a  agent  / tools + skill docs + keys     — knows exactly which keys to fetch
    P6b  agent  / tools + agents.md + keys      — richer sidecar, no pre-fetch
    P6a  agent  / tools + agents.md + memory    — full: pre-fetched snippets in sidecar
    """

    model_config = ConfigDict(extra="allow")

    id: str = Field(..., min_length=1)
    mode: Literal["direct", "agent"]
    memory_enabled: bool
    tools_enabled: bool
    retrieval_mode: Literal["injected", "agent_decides", "none"]
    instruction_mode: Literal["none", "explicit"]
    context_surface: Literal["system", "user", "tools_only", "skills_md", "skills_md_no_keys", "agents_md"]
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
    """What the model sees about the task."""

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
    """Snippet retrieval settings for a task."""

    required_snippets: list[str] = Field(default_factory=list)
    snippet_context_limit: int = Field(default=6, ge=1, le=50)
    snippet_context_max_chars: int = Field(default=1200, ge=100, le=20000)


class SuccessIndicators(BaseModel):
    correctness: list[str] = Field(default_factory=list)
    consistency: list[str] = Field(default_factory=list)
    completeness: list[str] = Field(default_factory=list)
    cost_efficiency: list[str] = Field(default_factory=list)
    memory_usage: list[str] = Field(default_factory=list)

    def as_lines(self) -> list[str]:
        rows: list[str] = []
        for key, values in self.model_dump(mode="python").items():
            for value in values:
                rows.append(f"{key}: {value}")
        return rows


class OracleConstraint(BaseModel):
    """A single binary pass/fail constraint evaluated by LLM judge."""

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
    """Fully parsed suite YAML.  task_map and variant_map are computed properties."""

    model_config = ConfigDict(extra="allow")

    suite: SuiteMeta
    models: list[dict]  # kept loose; caller checks names
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


# ---------------------------------------------------------------------------
# Prompt / execution
# ---------------------------------------------------------------------------


class RetrievedSnippet(BaseModel):
    id: str
    canonical_key: str | None = None
    title: str = ""
    language: str | None = None
    tags: list[str] = Field(default_factory=list)
    description: str | None = None
    code: str = ""


class PromptBundle(BaseModel):
    """Assembled prompt sent to the model."""

    system_prompt: str
    user_prompt: str
    context_surface: Literal["system", "user", "tools_only", "skills_md", "skills_md_no_keys", "agents_md", "fetch_skill"]
    visible_sections: list[str] = Field(default_factory=list)
    injected_snippet_keys: list[str] = Field(default_factory=list)
    injected_repo_policy: bool = False
    # Files to write into the subprocess working directory so claudecode / codex can
    # auto-load them from cwd (CLAUDE.md for claude, AGENTS.md for codex, SKILL.md for skills).
    # Populated for skills_md / agents_md / fetch_skill surfaces.
    sidecar_files: dict[str, str] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    # Server-side prompt cache hits (OpenAI: prompt_tokens_details.cached_tokens;
    # Anthropic: usage.cache_read_input_tokens). 0 = no cache hit or not supported.
    cached_tokens: int = 0
    # Reasoning / extended-thinking tokens.
    # OpenAI o-series / gpt-5 with reasoning: usage.completion_tokens_details.reasoning_tokens.
    # Anthropic extended thinking: usage.thinking_tokens (if exposed by SDK).
    # Subprocess providers (claudecode/codex): extracted from JSONL event stream.
    thinking_tokens: int | None = None
    # Estimated cost in USD computed from the per-model pricing table in dispatch.py.
    # None = model not in pricing table (unknown cost).
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
    rewrite_output: str


class SummaryMetrics(BaseModel):
    latency_ms: int
    prompt_chars: int
    output_chars: int
    # Prompt breakdown (populated by runner)
    prompt_system_chars: int = 0
    prompt_user_chars: int = 0
    # Total chars of all snippets injected into the prompt
    snippet_injected_chars: int = 0
    model_provider: str | None = None
    model_id: str | None = None
    snippet_count: int = 0
    tool_call_count: int = 0
    tool_error_count: int = 0
    used_tools: bool = False
    structured_output_attempted: bool = False
    structured_output_succeeded: bool = False
    fallback_parser_used: bool = False
    retrieval_latency_ms: int | None = None
    # VoltSnip client retry telemetry (per run)
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
    # Coarse class for filtering/grouping in analysis
    # Values: AUTH_ERROR, RATE_LIMIT_ERROR, TIMEOUT, NETWORK_ERROR, LLM_PARSE_ERROR,
    #         RETRIEVAL_ERROR, SCORING_ERROR, CONFIG_ERROR, EMPTY_OUTPUT, UNKNOWN_ERROR
    error_class: str = "UNKNOWN_ERROR"


# ---------------------------------------------------------------------------
# Pytest execution
# ---------------------------------------------------------------------------


class PytestResult(BaseModel):
    """Result of running the generated code against the project's test suite."""

    ran: bool = False
    returncode: int | None = None
    passed: bool = False
    stdout: str = ""
    stderr: str = ""
    duration_ms: int | None = None
    error: str | None = None
    docker_image: str | None = None
    overlay_path: str | None = None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


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
    # Per-constraint detail: [{id, passed, lexical_hit, llm_verdict}]
    constraint_results: list[dict] = Field(default_factory=list)
    passed: bool


# ---------------------------------------------------------------------------
# Run result
# ---------------------------------------------------------------------------


class RunResult(BaseModel):
    run_id: str
    suite_path: str
    output_root: str
    task_id: str
    task_name: str
    variant_id: str
    model_name: str
    status: Literal["ok", "error"]
    # Variant metadata — populated at run time for downstream analysis
    variant_mode: str = "direct"
    variant_memory_enabled: bool = False
    variant_tools_enabled: bool = False
    variant_retrieval_mode: str = "none"
    variant_instruction_mode: str = "none"
    variant_context_surface: str = "system"
    variant_max_tool_roundtrips: int = 4
    # Task metadata — for grouping and filtering
    task_category: str | None = None
    task_difficulty: str | None = None
    task_line_start: int | None = None
    task_line_end: int | None = None
    # Required snippet keys from task definition — for snippet coverage tracking
    required_snippet_keys: list[str] = Field(default_factory=list)
    prompt: PromptBundle
    prompt_after_tools: PromptBundle | None = None
    retrieved_snippets: list[RetrievedSnippet] = Field(default_factory=list)
    messages: list[MessageTrace] = Field(default_factory=list)
    tool_traces: list[ToolTrace] = Field(default_factory=list)
    raw_model_output: str = ""
    parsed_output: GeneratedPayload = Field(default_factory=lambda: GeneratedPayload(code="", comments=""))
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    timings: TimingInfo
    summary_metrics: SummaryMetrics
    artifacts: RunArtifactPaths
    score: ScoreResult | None = None
    pytest_result: PytestResult | None = None
    error: RunError | None = None


# ---------------------------------------------------------------------------
# Run-time configuration (overrides passed to run_one)
# ---------------------------------------------------------------------------


class RunConfig(BaseModel):
    """Everything you can tune per-run without touching the suite YAML."""

    model_config = ConfigDict(extra="allow")

    # LLM
    temperature: float = 0.0
    max_tokens: int | None = Field(default=None, ge=1)
    structured_output: bool = True
    # "native_sdk" uses openai/anthropic SDK directly; claudecode uses subprocess
    llm_runtime: Literal["native_sdk", "auto"] = "native_sdk"

    # Auth — explicit keys take priority; else env vars are used
    api_key: str | None = None
    provider_api_keys: dict[str, str] = Field(default_factory=dict)

    # VoltSnip backend
    voltsnip_base_url: str | None = None
    voltsnip_timeout_seconds: int = Field(default=20, ge=1)
    voltsnip_retry_attempts: int = Field(default=3, ge=1, le=10)

    # Snippet retrieval limits
    snippet_context_limit: int | None = Field(default=None, ge=1, le=50)
    snippet_context_max_chars: int | None = Field(default=None, ge=100, le=20000)

    # Scoring
    scoring_match_mode: Literal["lexical", "hybrid", "llm"] = "hybrid"
    scoring_primary_endpoint: Literal["auto", "constraint_binary", "legacy_weighted"] = "auto"
    auto_constraints_from_legacy_oracle: bool = True
    scoring_judge_model: str = "openai:gpt-5-mini"
    scoring_judge_max_tokens: int = Field(default=800, ge=64, le=8192)
    constraint_pass_threshold: float = Field(default=0.7, ge=0.0, le=1.0)

    # Scoring gate
    skip_scoring: bool = False  # Pass 1 only: skip LLM judge; rescore_scoring.py runs it later

    # Pytest / code execution (Docker only)
    auto_apply_patch: bool = False
    pytest_docker_image: str = "moltsnip-pytest:latest"
    pytest_docker_workdir: str = "/workspace"
    pytest_timeout_seconds: int = Field(default=300, ge=1)
    unapply_patch_after_test: bool = True

    # LLM call limits
    # max_tokens caps the *output* side (maps to max_completion_tokens / max_tokens per provider).
    # llm_timeout_seconds is the subprocess/SDK call timeout for single-shot paths;
    # MCP/tool-loop paths use max(600, llm_timeout_seconds) to allow for multi-turn latency.
    llm_timeout_seconds: int = Field(default=300, ge=10)

    # Misc
    repo_policy_text: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_unique(values: list[str], label: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for v in values:
        key = v.strip().lower()
        if key in seen:
            duplicates.add(v)
        seen.add(key)
    if duplicates:
        raise ValueError(f"duplicate {label}: {', '.join(sorted(duplicates))}")
