"""Prompt assembly for P0–P6a variant execution.

Entry point: build_prompt(task, variant, retrieved_snippets, ...)
Returns a PromptBundle with system_prompt + user_prompt.

Context surface per variant:
  P0 / P1        — "user"               : no injected snippets
  P2 / P3        — "system"             : injected snippets in system prompt
  P4             — "tools_only"         : MCP tools, zero guidance
  P5b            — "skills_md_no_keys"  : skill docs (how to use VoltSnip) only; no key hints
  P5a            — "skills_md"          : skill docs + specific keys; model knows exactly what to fetch
  P6b / P6a      — "agents_md"          : agents.md sidecar; P6b has no pre-fetch, P6a has memory
  (ext)          — "fetch_skill"        : REST API endpoint + key hints, no MCP tools

Tool ladder (ablation): P4 → P5b → P5a → P6b → P6a
Each step adds exactly one thing for clean attribution.

Template resolution order (skills_md / agents_md / fetch_skill):
  1. category-specific file   skills/{category}.md  /  agents/{category}.md  /  fetch_skills/{category}.md
  2. generic fallback          skills.md             /  agents.md              /  fetch_skill.md
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from vsevals.models import PromptBundle, RetrievedSnippet, SuiteTask, VariantConfig

# --- Constants ---------------------------------------------------------------

BASE_SYSTEM_PROMPT = """You are a senior software engineer executing a controlled code-fix evaluation.

Non-negotiable output contract:
- Return exactly one JSON object with required string field "code" and optional string field "comments".
- Valid shape only: {"code":"...","comments":"..."}
- No markdown fences, no prose outside JSON, no extra keys.

Editing contract:
- If Target File is provided, "code" must be the full rewritten file content.
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

_HARNESS_ROOT = Path(__file__).resolve().parents[1]

# Generic fallback templates (used when no category-specific file exists)
_SKILLS_MD_PATH = _HARNESS_ROOT / "skills.md"
_AGENTS_MD_PATH = _HARNESS_ROOT / "agents.md"
_FETCH_SKILL_MD_PATH = _HARNESS_ROOT / "fetch_skill.md"

# Category-specific template directories
_SKILLS_DIR = _HARNESS_ROOT / "skills"
_AGENTS_DIR = _HARNESS_ROOT / "agents"
_FETCH_SKILLS_DIR = _HARNESS_ROOT / "fetch_skills"


def _resolve_path(category: str | None, directory: Path, fallback: Path) -> Path:
    """Return category-specific template if it exists, else the generic fallback."""
    if category:
        p = directory / f"{category}.md"
        if p.exists():
            return p
    return fallback


_skills_path      = lambda c: _resolve_path(c, _SKILLS_DIR,       _SKILLS_MD_PATH)
_agents_path      = lambda c: _resolve_path(c, _AGENTS_DIR,       _AGENTS_MD_PATH)
_fetch_skill_path = lambda c: _resolve_path(c, _FETCH_SKILLS_DIR, _FETCH_SKILL_MD_PATH)


# --- Public entry point ------------------------------------------------------


def build_prompt(
    *,
    task: SuiteTask,
    variant: VariantConfig,
    retrieved_snippets: list[RetrievedSnippet],
    repo_policy_text: str | None,
    target_file_content: str | None,
    voltsnip_base_url: str | None = None,
) -> PromptBundle:
    """Assemble system + user prompts for a (task, variant) combination."""
    b = _Builder(
        task_id=task.task.id,
        task_name=task.task.name,
        user_prompt=_normalize_prompt(task.task.user_prompt),
        context_surface=variant.context_surface,
    )

    # --- Task context blocks -------------------------------------------------
    if task.task.description:
        b.add_user_visible("description", "Task Description:", task.task.description.rstrip())

    if task.task.target_file:
        b.add_user_visible("target_file", f"Target File: {task.task.target_file}")
        if task.task.line_start is not None:
            b.add_user_visible("target_span", "Target Lines:", f"{task.task.line_start}-{task.task.line_end} (1-based, inclusive)")
        if task.task.test_command:
            b.add_user_visible("test_command", "Test Command:", task.task.test_command)

    if task.task.context_code:
        b.add_user_visible("context_code", "Context Code:", "```python", task.task.context_code.rstrip(), "```")

    if target_file_content:
        b.add_user_visible("target_file_content", "Target File Content (full file):", "```python", target_file_content.rstrip(), "```")

    if task.task.expected_output:
        b.add_user_visible("expected_output", "Expected Output:", task.task.expected_output.rstrip())

    if variant.include_oracle:
        oracle_rows = _oracle_rows(task)
        if oracle_rows:
            b.add_user_visible("oracle_criteria", "Acceptance Criteria (strict):", *oracle_rows)
            b.add_user("Acceptance Requirement:", "You MUST satisfy the acceptance criteria and avoid the listed failure modes.")

    # --- Snippet + key assembly ----------------------------------------------
    required_keys = _dedup(task.voltsnip.required_snippets) if variant.retrieval_mode != "none" else []
    snippet_keys = _dedup(required_keys + [s.canonical_key or s.id for s in retrieved_snippets])
    snippet_block = _snippet_block(retrieved_snippets)
    key_block = _key_block(snippet_keys)
    policy_block = _policy_block(repo_policy_text)

    # --- Execution mode banner -----------------------------------------------
    if variant.mode == "agent" and variant.tools_enabled:
        mode_line = "Agent mode: decide context/tool usage within constraints."
    else:
        mode_line = "Direct mode: produce the final full-file rewrite payload without agent tool loops."
    b.add_user_visible("variant_mode", "Execution Mode:", mode_line)
    if variant.purpose or variant.note:
        b.add_user_visible("variant_hypothesis", "Variant Hypothesis:", (variant.purpose or variant.note or "").rstrip())
    if variant.tools_enabled:
        b.add_user_visible("tool_budget", "Tool Budget:", f"Maximum tool roundtrips: {variant.max_tool_roundtrips}")

    # --- Instruction strength ------------------------------------------------
    if snippet_keys:
        if variant.instruction_mode == "explicit":
            b.add_user("Guideline Requirement:", "You MUST check and apply the listed Guiding Snippet Keys before producing final output.")
        else:
            b.add_user("Guidance:", "Consult the listed Guiding Snippet Keys while implementing the fix.")

    if variant.tools_enabled and snippet_keys:
        if variant.instruction_mode == "explicit":
            b.add_user("Tool Requirement:", "You MUST perform at least one snippet retrieval tool call before final output.")
        else:
            b.add_user("Tool Guidance:", "Snippet retrieval tools are available if additional context is needed.")

    if variant.instruction_mode == "explicit":
        explicit = ["Execution Instruction:"]
        if snippet_keys:
            explicit.append("This is strict: verify and apply guidance from the listed Guiding Snippet Keys.")
        else:
            explicit.append("This is strict: satisfy the acceptance criteria and expected output exactly.")
        explicit.append("Keep output deterministic and minimal.")
        b.add_user(*explicit)

    # --- Context surface injection -------------------------------------------
    surface = variant.context_surface
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
        rendered_skills_bare = _render_skills_no_keys(category=task.task.category)
        # No inline key hint — model must decide what to search for.
        # Sidecars: SKILL.md/CLAUDE.md for claude auto-load, AGENTS.md for codex.
        b.sidecar_files["SKILL.md"] = rendered_skills_bare
        b.sidecar_files["CLAUDE.md"] = rendered_skills_bare
        b.sidecar_files["AGENTS.md"] = rendered_skills_bare
    elif surface == "skills_md":
        rendered_skills = _render_skills(snippet_keys, category=task.task.category)
        b.inject_user("snippet_keys", _snippet_key_hint(snippet_keys))
        # Sidecars: SKILL.md/CLAUDE.md for claude auto-load, AGENTS.md for codex.
        b.sidecar_files["SKILL.md"] = rendered_skills
        b.sidecar_files["CLAUDE.md"] = rendered_skills
        b.sidecar_files["AGENTS.md"] = rendered_skills
    elif surface == "agents_md":
        rendered_agents = _render_agents(repo_policy_text, snippet_keys, retrieved_snippets, category=task.task.category)
        b.inject_system("snippet_keys", _snippet_key_hint(snippet_keys))
        # Sidecars: CLAUDE.md for claude auto-load, AGENTS.md for codex auto-load.
        b.sidecar_files["CLAUDE.md"] = rendered_agents
        b.sidecar_files["AGENTS.md"] = rendered_agents
    elif surface == "fetch_skill":
        rendered_fetch = _render_fetch_skill(snippet_keys, category=task.task.category, voltsnip_base_url=voltsnip_base_url)
        b.inject_user("fetch_skill", rendered_fetch)
        # Sidecar: SKILL.md for claude, AGENTS.md for codex.
        b.sidecar_files["SKILL.md"] = rendered_fetch
        b.sidecar_files["AGENTS.md"] = rendered_fetch

    return b.build(snippet_keys=snippet_keys, injected_repo_policy=bool(repo_policy_text and repo_policy_text.strip()))


# --- Builder helper ----------------------------------------------------------


class _Builder:
    def __init__(self, *, task_id: str, task_name: str, user_prompt: str, context_surface: str) -> None:
        self.context_surface = context_surface
        self.visible_sections = ["task_id", "task_name", "user_prompt"]
        self.system_blocks: list[str] = [BASE_SYSTEM_PROMPT]
        self.user_blocks: list[str] = [
            f"Task ID: {task_id}",
            f"Task Name: {task_name}",
            "Task Objective:",
            user_prompt.rstrip(),
        ]
        self.user_ctx: list[str] = []
        # Sidecar files for claudecode/codex subprocess cwd auto-loading.
        # CLAUDE.md → auto-loaded by claude CLI from cwd
        # AGENTS.md → auto-loaded by codex exec from cwd
        # SKILL.md  → loaded as a skill by claude CLI
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


# --- Rendering helpers -------------------------------------------------------


def _snippet_block(snippets: list[RetrievedSnippet]) -> str:
    if not snippets:
        return ""
    rows = ["VoltSnip Context:"]
    for i, s in enumerate(snippets, 1):
        key = s.canonical_key or s.id
        rows += [f"Snippet {i}: {key}", f"Title: {s.title or 'n/a'}", "Code:", "```", s.code.rstrip(), "```", ""]
    return "\n".join(rows).strip()


def _key_block(keys: list[str]) -> str:
    if not keys:
        return ""
    return "\n".join(["Guiding Snippet Keys:", *[f"- {k}" for k in keys]])


def _policy_block(repo_policy_text: str | None) -> str:
    text = (repo_policy_text or DEFAULT_REPO_POLICY).strip()
    return f"Repository Policy:\n{text}" if text else ""


def _render_skills(snippet_keys: list[str], *, category: str | None = None) -> str:
    """Render skills.md template. Prefers category-specific file over generic fallback."""
    template = _load_template(_skills_path(category))
    csv = ", ".join(snippet_keys) if snippet_keys else "none"
    bullets = "\n".join(f"- {k}" for k in snippet_keys) if snippet_keys else "- none"
    if template:
        return _apply_template(template, {"SNIPPET_KEYS_CSV": csv, "SNIPPET_KEYS_BULLETS": bullets, "SNIPPET_KEY_COUNT": str(len(snippet_keys))})
    return f"Skills:\n- Use voltsnip retrieval tools for canonical snippets.\n- Suggested keys for this task: {csv}.\n- Keep tool usage minimal and deterministic."


_SNIPPET_KEYS_SECTION_RE = re.compile(
    r"## Snippet Keys for This Task\n.*?(?=\n##|\Z)", re.DOTALL
)
_SNIPPET_KEYS_REPLACEMENT = (
    "## No Pre-Identified Keys\n"
    "No specific snippet keys have been pre-identified for this task.\n"
    "Use `voltsnip_semantic_search` with the query guidance above to find relevant snippets."
)


def _render_skills_no_keys(*, category: str | None = None) -> str:
    """Render minimal skill stub for P5b: teaches HOW to use VoltSnip, not WHICH keys.

    Intentionally omits any snippet key guidance so the model must decide
    what to search for based on the task description alone.
    The empty 'Snippet Keys' section is replaced with a note to use semantic search.
    """
    template = _load_template(_skills_path(category))
    if template:
        rendered = _apply_template(template, {
            "SNIPPET_KEYS_CSV": "",
            "SNIPPET_KEYS_BULLETS": "",
            "SNIPPET_KEY_COUNT": "0",
        })
        return _SNIPPET_KEYS_SECTION_RE.sub(_SNIPPET_KEYS_REPLACEMENT, rendered)
    return (
        "Skills:\n"
        "- Use VoltSnip retrieval tools to fetch canonical code patterns relevant to the bug.\n"
        "- Search by category, tag, or pattern name based on the task description.\n"
        "- Retrieve snippets before writing your fix."
    )


def _render_agents(repo_policy_text: str | None, snippet_keys: list[str], snippets: list[RetrievedSnippet], *, category: str | None = None) -> str:
    """Render agents.md template. Prefers category-specific file over generic fallback."""
    policy = (repo_policy_text or DEFAULT_REPO_POLICY).strip()
    csv = ", ".join(snippet_keys) if snippet_keys else "none"
    bullets = "\n".join(f"- {k}" for k in snippet_keys) if snippet_keys else "- none"
    template = _load_template(_agents_path(category))
    retrieved_text = _agents_snippets_text(snippets)
    if template:
        return _apply_template(template, {
            "REPO_POLICY": policy,
            "SNIPPET_KEYS_CSV": csv,
            "SNIPPET_KEYS_BULLETS": bullets,
            "SNIPPET_KEY_COUNT": str(len(snippet_keys)),
            "RETRIEVED_SNIPPETS": retrieved_text,
        })
    rows = ["Repository Policy (agents.md style):", policy, "", f"Available snippet keys: {csv}", "Follow conventions strictly."]
    if snippets:
        rows += ["", "Retrieved Snippet Context:"] + retrieved_text.splitlines()
    return "\n".join(rows).strip()


def _render_fetch_skill(snippet_keys: list[str], *, category: str | None = None, voltsnip_base_url: str | None = None) -> str:
    """Render fetch_skill.md template. Prefers category-specific file over generic fallback."""
    template = _load_template(_fetch_skill_path(category))
    csv = ", ".join(snippet_keys) if snippet_keys else "none"
    bullets = "\n".join(f"- {k}" for k in snippet_keys) if snippet_keys else "- none"
    base_url = (voltsnip_base_url or "http://localhost:8001").rstrip("/")
    if template:
        return _apply_template(template, {
            "SNIPPET_KEYS_CSV": csv,
            "SNIPPET_KEYS_BULLETS": bullets,
            "SNIPPET_KEY_COUNT": str(len(snippet_keys)),
            "VOLTSNIP_BASE_URL": base_url,
        })
    return (
        f"Fetch Skill:\n"
        f"- Retrieve canonical snippets from VoltSnip REST API before fixing.\n"
        f"- Base URL: {base_url}\n"
        f"- GET {base_url}/api/v1/snippets/{{canonical_key}}\n"
        f"- Suggested keys: {csv}.\n"
        f"- Keep fix minimal and deterministic."
    )


def _snippet_key_hint(snippet_keys: list[str]) -> str:
    if not snippet_keys:
        return ""
    return "Relevant snippet keys: " + ", ".join(snippet_keys)


def _agents_snippets_text(snippets: list[RetrievedSnippet]) -> str:
    if not snippets:
        return "none"
    rows: list[str] = []
    for i, s in enumerate(snippets, 1):
        key = s.canonical_key or s.id
        rows += [f"Snippet {i}: {key}", f"Title: {s.title or 'n/a'}", "```", s.code.rstrip(), "```"]
    return "\n".join(rows)


def _oracle_rows(task: SuiteTask) -> list[str]:
    rows: list[str] = []
    hidden = [r.strip() for r in task.oracle.hidden_requirements if r.strip()]
    success = [r.strip() for r in task.oracle.success_indicators.as_lines() if r.strip()]
    failures = [r.strip() for r in task.oracle.failure_modes if r.strip()]
    criteria = [r.strip() for r in task.oracle.evaluation_criteria if r.strip()]
    if hidden:
        rows += ["Hidden requirements:"] + [f"- {r}" for r in hidden]
    if success:
        rows += ["Success indicators:"] + [f"- {r}" for r in success]
    if failures:
        rows += ["Failure modes to avoid:"] + [f"- {r}" for r in failures]
    if criteria:
        rows += ["Evaluation criteria:"] + [f"- {r}" for r in criteria]
    return rows


@lru_cache(maxsize=32)  # 5 categories × 3 template types × 2 (skill+agent) + fallbacks
def _load_template(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def _apply_template(template: str, subs: dict[str, str]) -> str:
    result = template
    for token, value in subs.items():
        result = result.replace(f"{{{{{token}}}}}", value)
    return result.strip()


def _dedup(keys: list[str | None]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        nk = (k or "").strip()
        if nk and nk not in seen:
            seen.add(nk)
            out.append(nk)
    return out


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
