"""Prompt assembly for P0–P6 variant execution.

Entry point: build_prompt(task, variant, retrieved_snippets, ...)
Returns a PromptBundle with system_prompt + user_prompt.

Context surfaces:
  P0 "user"                     raw baseline, no memory/tools
  P1 "user"                     baseline + explicit instruction
  P2 "system"                   injected memory in system prompt
  P3 "tools_only"               tools only, no sidecar guidance
  P4 "skills_md_no_keys"        inline static SKILL.md guidance + tools
  P5 "agents_md_no_keys"        inline static AGENTS.md guidance + tools
  P6 "skills_agents_md_no_keys" inline SKILL.md + AGENTS.md + tools
"""

from __future__ import annotations

import re
from pathlib import Path

from vsevals.models import PromptBundle, RetrievedSnippet, SuiteTask, VariantConfig

BASE_SYSTEM_PROMPT = """You are a senior software engineer executing a controlled code-fix evaluation.

Output format:
Return ONLY valid JSON — no markdown fences, preamble, or trailing text:
{"code": "<see editing contract below>", "comments": "<one-sentence explanation of the change>"}

Editing contract:
- When NO Target Lines are given: "code" must be the complete rewritten file content.
- When Target Lines ARE given: "code" must contain ONLY the replacement for that line range.
  The file header, imports, and all content outside the range are preserved automatically.
  Do NOT include them — outputting the full file will corrupt the target file.
- Never return a diff, patch, pseudocode, placeholder, or partial line fragment.
- Keep changes minimal and localized to the stated bug objective.
- Preserve public behavior unless the task explicitly requires a change.

Reliability contract:
- Prefer deterministic fixes over clever rewrites.
- Preserve imports, typing, and runtime safety.
- If uncertain, preserve existing behavior and avoid speculative refactors."""

DEFAULT_REPO_POLICY = """- Follow repository conventions and preserve API compatibility.
- Prefer minimal, production-safe changes.
- Keep behavior deterministic and testable."""

INLINE_SKILL_GUIDE = """# VoltSnip — Code Pattern Retrieval

VoltSnip is a semantic memory store containing org-specific code
patterns, API usage examples, and scenario context for this repo.

Available tools:
- semantic_search: find relevant snippets by natural language query
- fetch snippet by key: retrieve a specific known snippet

Use VoltSnip when the fix involves an org-specific API, metric name,
import path, or pattern that may not be derivable from the file alone.
Results give concrete, repo-correct usage examples.
"""

INLINE_AGENT_GUIDE = """# Repository Context

This codebase uses internal org-specific APIs (orgops.*) for metrics,
logging, and operational integrations. These APIs are not standard
library calls — their signatures and import paths must be looked up,
not guessed.

Conventions:
- Fixes must be minimal and scoped to the target lines.
- Metric emission and operational hooks follow repo-specific patterns.
- Return only the required JSON output payload.
"""

_HARNESS_ROOT = Path(__file__).resolve().parents[1]
_SKILLS_MD_PATH = _HARNESS_ROOT / "skills.md"
_AGENTS_MD_PATH = _HARNESS_ROOT / "agents.md"


def build_prompt(
    *,
    task: SuiteTask,
    variant: VariantConfig,
    retrieved_snippets: list[RetrievedSnippet],
    repo_policy_text: str | None,
    target_file_content: str | None,
    voltsnip_base_url: str | None = None,
) -> PromptBundle:
    _ = voltsnip_base_url  # kept for stable call signature

    b = _Builder(
        task_id=task.task.id,
        task_name=task.task.name,
        user_prompt=_normalize_prompt(task.task.user_prompt),
        context_surface=variant.context_surface,
    )

    if task.task.description:
        b.add_user_visible("description", "Task Description:", task.task.description.rstrip())

    if task.task.target_file:
        b.add_user_visible("target_file", f"Target File: {task.task.target_file}")
        if task.task.line_start is not None:
            b.add_user_visible(
                "target_span",
                "Target Lines:",
                f"{task.task.line_start}-{task.task.line_end} (1-based, inclusive)",
                f"IMPORTANT: Output ONLY the replacement for lines {task.task.line_start}-{task.task.line_end} in \"code\".",
                "Do NOT output the full file. Imports and surrounding lines outside this range are preserved automatically.",
            )
        if task.task.test_command:
            b.add_user_visible("test_command", "Test Command:", task.task.test_command)

    if task.task.context_code:
        b.add_user_visible("context_code", "Context Code:", "```python", task.task.context_code.rstrip(), "```")

    if target_file_content:
        b.add_user_visible("target_file_content", "Target File Content (full file):", "```python", target_file_content.rstrip(), "```")

    if task.task.expected_output and variant.retrieval_mode != "none":
        b.add_user_visible("expected_output", "Expected Output:", task.task.expected_output.rstrip())

    if variant.include_oracle:
        oracle_rows = _oracle_rows(task)
        if oracle_rows:
            b.add_user_visible("oracle_criteria", "Acceptance Criteria (strict):", *oracle_rows)
            b.add_user("Acceptance Requirement:", "You MUST satisfy the acceptance criteria and avoid the listed failure modes.")

    required_keys = _dedup(task.voltsnip.required_snippets) if variant.retrieval_mode != "none" else []
    snippet_keys = _dedup(required_keys + [s.canonical_key or s.id for s in retrieved_snippets])
    snippet_block = _snippet_block(retrieved_snippets)
    key_block = _key_block(snippet_keys)
    policy_block = _policy_block(repo_policy_text)

    if variant.mode == "agent" and variant.tools_enabled:
        mode_line = "Agent mode: decide context/tool usage within constraints."
    else:
        mode_line = "Direct mode: produce the final full-file rewrite payload without agent tool loops."
    b.add_user_visible("variant_mode", "Execution Mode:", mode_line)

    if variant.purpose or variant.note:
        b.add_user_visible("variant_hypothesis", "Variant Hypothesis:", (variant.purpose or variant.note or "").rstrip())
    if variant.tools_enabled:
        b.add_user_visible("tool_budget", "Tool Budget:", f"Maximum tool roundtrips: {variant.max_tool_roundtrips}")

    surface = variant.context_surface
    no_key_hint_surfaces = {"tools_only", "skills_md_no_keys", "agents_md_no_keys", "skills_agents_md_no_keys"}
    keys_visible = bool(snippet_keys) and surface not in no_key_hint_surfaces

    if keys_visible:
        if variant.instruction_mode == "explicit":
            b.add_user("Guideline Requirement:", "You MUST check and apply the listed Guiding Snippet Keys before producing final output.")
        else:
            b.add_user("Guidance:", "Consult the listed Guiding Snippet Keys while implementing the fix.")

    if variant.tools_enabled and keys_visible:
        if variant.instruction_mode == "explicit":
            b.add_user("Tool Requirement:", "You MUST perform at least one snippet retrieval tool call before final output.")
        else:
            b.add_user("Tool Guidance:", "Snippet retrieval tools are available if additional context is needed.")

    if variant.instruction_mode == "explicit":
        explicit = ["Execution Instruction:"]
        if keys_visible:
            explicit.append("This is strict: verify and apply guidance from the listed Guiding Snippet Keys.")
        elif variant.tools_enabled and surface == "skills_md_no_keys":
            explicit.append(
                "This is strict: you MUST invoke the voltsnip-guide skill to retrieve relevant code patterns "
                "and context before implementing the fix. Do not attempt the fix without first consulting the skill."
            )
        elif variant.tools_enabled:
            explicit.append(
                "This is strict: you MUST perform at least one snippet retrieval tool call "
                "before implementing the fix. Do not attempt the fix without first fetching relevant context."
            )
        else:
            explicit.append("This is strict: satisfy the acceptance criteria and expected output exactly.")
        explicit.append("Keep output deterministic and minimal.")
        b.add_user(*explicit)

    if surface == "system":
        b.inject_system("snippet_context", snippet_block)
        b.inject_system("snippet_keys", key_block)
        b.inject_system("repo_policy", policy_block)
    elif surface == "user":
        b.inject_user("snippet_context", snippet_block)
        b.inject_user("snippet_keys", key_block)
        b.inject_user("repo_policy", policy_block)
    elif surface == "tools_only":
        b.system_blocks.append("Tool access is enabled. Fetch memory through tools when useful to solve the task.")
    elif surface == "skills_md_no_keys":
        skills_doc = _load_static_doc(_SKILLS_MD_PATH, INLINE_SKILL_GUIDE)
        skill_with_frontmatter = (
            "---\nname: voltsnip-guide\ndescription: Use this skill to retrieve relevant VoltSnip code patterns "
            "and context snippets before implementing a fix.\n---\n\n" + skills_doc
        )
        b.sidecar_files["skills/voltsnip-guide/SKILL.md"] = skill_with_frontmatter
        b.sidecar_files["SKILL.md"] = skills_doc
    elif surface == "agents_md_no_keys":
        agents_doc = _load_static_doc(_AGENTS_MD_PATH, INLINE_AGENT_GUIDE)
        b.sidecar_files["CLAUDE.md"] = agents_doc
        b.sidecar_files["AGENTS.md"] = agents_doc
    elif surface == "skills_agents_md_no_keys":
        skills_doc = _load_static_doc(_SKILLS_MD_PATH, INLINE_SKILL_GUIDE)
        agents_doc = _load_static_doc(_AGENTS_MD_PATH, INLINE_AGENT_GUIDE)
        skill_with_frontmatter = (
            "---\nname: voltsnip-guide\ndescription: Use this skill to retrieve relevant VoltSnip code patterns "
            "and context snippets before implementing a fix.\n---\n\n" + skills_doc
        )
        b.sidecar_files["skills/voltsnip-guide/SKILL.md"] = skill_with_frontmatter
        b.sidecar_files["SKILL.md"] = skills_doc
        b.sidecar_files["AGENTS.md"] = agents_doc
        b.sidecar_files["CLAUDE.md"] = agents_doc
    else:
        raise ValueError(f"unsupported context_surface: {surface!r}")

    return b.build(snippet_keys=snippet_keys, injected_repo_policy=bool(repo_policy_text and repo_policy_text.strip()))


class _Builder:
    def __init__(self, *, task_id: str, task_name: str, user_prompt: str, context_surface: str) -> None:
        self.context_surface = context_surface
        self.visible_sections = ["task_id", "task_name", "user_prompt"]
        self.system_blocks: list[str] = [BASE_SYSTEM_PROMPT]
        self.user_blocks: list[str] = [f"Task ID: {task_id}", f"Task Name: {task_name}", "Task Objective:", user_prompt.rstrip()]
        self.user_ctx: list[str] = []
        self.sidecar_files: dict[str, str] = {}

    def add_user_visible(self, section: str, *lines: str) -> None:
        self.visible_sections.append(section)
        self._add(self.user_blocks, *lines)

    def add_user(self, *lines: str) -> None:
        self._add(self.user_blocks, *lines)

    def inject_system(self, section: str, text: str) -> None:
        if text:
            self.visible_sections.append(section)
            self.system_blocks.append(text)

    def inject_user(self, section: str, text: str) -> None:
        if text:
            self.visible_sections.append(section)
            self.user_ctx.append(text)

    def build(self, *, snippet_keys: list[str], injected_repo_policy: bool) -> PromptBundle:
        system = "\n\n".join(b for b in self.system_blocks if b.strip())
        user = "\n".join(self.user_blocks + (["", *self.user_ctx] if self.user_ctx else []))
        return PromptBundle(
            system_prompt=system,
            user_prompt=user,
            context_surface=self.context_surface,  # type: ignore[arg-type]
            visible_sections=self.visible_sections,
            injected_snippet_keys=snippet_keys,
            injected_repo_policy=injected_repo_policy,
            sidecar_files=self.sidecar_files,
        )

    @staticmethod
    def _add(target: list[str], *lines: str) -> None:
        target.append("")
        target.extend(lines)


def _snippet_block(snippets: list[RetrievedSnippet]) -> str:
    if not snippets:
        return ""
    rows = ["VoltSnip Context:"]
    for i, s in enumerate(snippets, 1):
        key = s.canonical_key or s.id
        rows += [f"Snippet {i}: {key}", f"Title: {s.title or 'n/a'}", "Code:", "```", s.code.rstrip(), "```", ""]
    return "\n".join(rows).strip()


def _key_block(keys: list[str]) -> str:
    return "\n".join(["Guiding Snippet Keys:", *[f"- {k}" for k in keys]]) if keys else ""


def _policy_block(repo_policy_text: str | None) -> str:
    text = (repo_policy_text or DEFAULT_REPO_POLICY).strip()
    return f"Repository Policy:\n{text}" if text else ""


def _oracle_rows(task: SuiteTask) -> list[str]:
    rows: list[str] = []
    for label, items in [
        ("Hidden requirements:", task.oracle.hidden_requirements),
        ("Success indicators:", task.oracle.success_indicators.as_lines()),
        ("Failure modes to avoid:", task.oracle.failure_modes),
        ("Evaluation criteria:", task.oracle.evaluation_criteria),
    ]:
        if clean := [r.strip() for r in items if r.strip()]:
            rows += [label] + [f"- {r}" for r in clean]
    return rows


def _dedup(keys: list[str | None]) -> list[str]:
    seen: set[str] = set()
    return [nk for k in keys if (nk := (k or "").strip()) and nk not in seen and not seen.add(nk)]  # type: ignore[func-returns-value]


def _normalize_prompt(text: str) -> str:
    t = text.strip()
    if not t:
        return "Apply the required fix using target metadata and context."
    t = re.sub(r"(?im)^\s*Work in\s+`[^`]+`\.?\s*$", "", t)
    t = re.sub(r"(?im)^\s*Fix only\s+`BUG_[^`]+`\s+in\s+`[^`]+`:\s*$", "Apply only the requested bug fix:", t)
    lines: list[str] = []
    prev_blank = False
    for line in (ln.rstrip() for ln in t.splitlines()):
        blank = not line.strip()
        if blank and prev_blank:
            continue
        lines.append(line)
        prev_blank = blank
    return "\n".join(lines).strip() or "Apply the required fix using target metadata and context."


def _load_static_doc(path: Path, fallback: str) -> str:
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return fallback
