#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
PYPROJECT = ROOT / "backend" / "pyproject.toml"
SKILL_MD = ROOT / "voltsnip-skill" / "SKILL.md"
SKILL_PKG = ROOT / "voltsnip-skill" / "package.json"
AGENT_SKILL_MD = ROOT / ".agent" / "skills" / "voltsnip" / "SKILL.md"


def read_version_from_pyproject(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    in_project = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "[project]":
            in_project = True
            continue
        if in_project and stripped.startswith("["):
            break
        if in_project and stripped.startswith("version"):
            _, _, value = stripped.partition("=")
            return value.strip().strip('"')
    raise SystemExit("Unable to find [project].version in backend/pyproject.toml")


def write_version_to_pyproject(path: Path, version: str) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines()
    in_project = False
    changed = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[project]":
            in_project = True
            continue
        if in_project and stripped.startswith("["):
            break
        if in_project and stripped.startswith("version"):
            prefix = line.split("=")[0]
            lines[i] = f"{prefix}= \"{version}\""
            changed = True
            break
    if changed:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def write_version_to_skill_md(path: Path, version: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise SystemExit(f"{path} missing YAML frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise SystemExit(f"{path} missing YAML frontmatter end marker")
    frontmatter = parts[1].splitlines()
    changed = False
    for i, line in enumerate(frontmatter):
        if line.lstrip().startswith("version:"):
            indent = line[: len(line) - len(line.lstrip())]
            frontmatter[i] = f"{indent}version: {version}"
            changed = True
            break
    if not changed:
        raise SystemExit(f"{path} missing version field in frontmatter")
    rebuilt = "---" + "\n" + "\n".join(frontmatter) + "\n---" + parts[2]
    path.write_text(rebuilt, encoding="utf-8")
    return True


def write_version_to_package_json(path: Path, version: str) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") == version:
        return False
    data["version"] = version
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def main() -> int:
    if VERSION_FILE.exists():
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
    else:
        version = read_version_from_pyproject(PYPROJECT)
        VERSION_FILE.write_text(version + "\n", encoding="utf-8")

    changed = False
    changed |= write_version_to_pyproject(PYPROJECT, version)
    if SKILL_MD.exists():
        changed |= write_version_to_skill_md(SKILL_MD, version)
    if SKILL_PKG.exists():
        changed |= write_version_to_package_json(SKILL_PKG, version)
    if AGENT_SKILL_MD.exists():
        changed |= write_version_to_skill_md(AGENT_SKILL_MD, version)

    if changed:
        print(f"Synced versions to {version}")
    else:
        print(f"Versions already in sync ({version})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
