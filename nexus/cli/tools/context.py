"""Provider-neutral context inspection, compression, and routing tools."""

from __future__ import annotations

import ast
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal, Optional

from nexus.cli.generators import upsert_managed_block
from nexus.cli.installation import load_manifest, sha256_file, validate_skill_tree
from nexus.cli.utils import OutputFormat, Status, emit, make_result

Consumer = Literal["codex", "devin", "devin-review", "claude", "cursor", "copilot", "vscode"]

CONSUMER_SURFACES: dict[Consumer, tuple[str, ...]] = {
    "codex": ("AGENTS.md", ".agents/skills/*/SKILL.md"),
    "devin": ("AGENTS.md", ".agents/skills/*/SKILL.md"),
    "devin-review": ("AGENTS.md", "REVIEW.md", "CLAUDE.md", ".cursor/rules/*.mdc"),
    "claude": ("CLAUDE.md", ".claude/skills/*/SKILL.md"),
    "cursor": ("AGENTS.md", ".cursor/rules/*.mdc", ".agents/skills/*/SKILL.md"),
    "copilot": ("AGENTS.md", ".github/copilot-instructions.md", ".github/instructions/*.instructions.md", ".agents/skills/*/SKILL.md"),
    "vscode": ("AGENTS.md", ".agents/skills/*/SKILL.md"),
}

IGNORE_FILES = {
    "codeium": ".codeiumignore",
    "cursor": ".cursorignore",
    "aider": ".aiderignore",
    "repomix": ".repomixignore",
}
IGNORE_PATTERNS = (
    ".git/", ".venv/", "node_modules/", "__pycache__/", ".pytest_cache/",
    ".mypy_cache/", ".cache/", "dist/", "build/", "coverage/", "htmlcov/",
    "*.log", "*.min.js", "*.map", ".nexus/journal/", ".nexus/state-dashboard.html",
)
SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".cache", ".nexus", ".windsurf", "dist", "build",
}
TEXT_SUFFIXES = {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".md", ".toml", ".yaml", ".yml", ".json"}

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(\s*[=:]\s*)([^\s,;]+)"),
    re.compile(r"\b(?:sk|ghp|github_pat|xox[baprs])-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*"),
)


def _estimate_tokens(chars: int) -> int:
    return (chars + 3) // 4


def _paths_for_surface(root: Path, pattern: str) -> list[Path]:
    return sorted(p for p in root.glob(pattern) if p.is_file())


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _ambient_content(path: Path, content: str) -> str:
    """Return content loaded for discovery, not a skill's just-in-time body."""
    if path.name != "SKILL.md" or not content.startswith("---"):
        return content
    parts = content.split("---", 2)
    return f"---{parts[1]}---" if len(parts) == 3 else content


def audit_context(project_dir: Path) -> dict[str, Any]:
    """Return an effective-context and duplication audit."""
    root = project_dir.resolve()
    consumers: dict[str, Any] = {}
    all_instruction_files: dict[str, str] = {}
    for name, patterns in CONSUMER_SURFACES.items():
        found: dict[str, str] = {}
        for pattern in patterns:
            for path in _paths_for_surface(root, pattern):
                content = _read_text(path)
                found[_relative(path, root)] = _ambient_content(path, content)
        consumers[name] = {
            "files": sorted(found),
            "chars": sum(len(v) for v in found.values()),
            "estimated_tokens": _estimate_tokens(sum(len(v) for v in found.values())),
            "skill_count": sum(path.endswith("/SKILL.md") for path in found),
            "skill_body_mode": "metadata-only",
        }
        all_instruction_files.update(
            {
                rel: content
                for rel, content in found.items()
                if not rel.startswith(".claude/skills/")
            }
        )

    line_sources: dict[str, set[str]] = {}
    for filename, content in all_instruction_files.items():
        for raw in content.splitlines():
            line = re.sub(r"\s+", " ", raw.strip()).lower()
            if (
                len(line) < 24
                or line.startswith(("#", "<!--", "---", "python ", "nexus ", "load `.agents/skills"))
            ):
                continue
            line_sources.setdefault(line, set()).add(filename)
    duplicates = [
        {"line": line[:160], "files": sorted(files)}
        for line, files in line_sources.items() if len(files) > 1
    ]
    duplicates.sort(key=lambda item: (-len(item["files"]), item["line"]))

    largest: list[tuple[int, str]] = []
    for path in root.rglob("*"):
        parts = path.relative_to(root).parts
        if not path.is_file() or any(part in SKIP_DIRS or part.endswith(".egg-info") for part in parts):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        largest.append((size, _relative(path, root)))
    largest.sort(reverse=True)

    manifest = load_manifest(root)
    selected_consumers = set(manifest.get("consumers", ())) if manifest else set()
    relevant_ignore_tools = {
        tool
        for tool, rel in IGNORE_FILES.items()
        if (tool == "cursor" and "cursor" in selected_consumers)
        or (tool == "repomix" and (root / rel).exists())
        or (tool == "aider" and (root / rel).exists())
        or (tool == "codeium" and (root / rel).exists())
    }
    ignore_coverage = {}
    for tool, rel in IGNORE_FILES.items():
        if tool not in relevant_ignore_tools:
            continue
        path = root / rel
        content = _read_text(path) if path.exists() else ""
        missing = [p for p in IGNORE_PATTERNS if p not in content]
        ignore_coverage[tool] = {"path": rel, "present": path.exists(), "missing": missing}

    state_path = root / ".nexus" / "state.json"
    skill_issues = validate_skill_tree(root / ".agents" / "skills")
    projection_mismatches: list[str] = []
    if manifest and "claude" in manifest.get("consumers", []):
        canonical_root = root / ".agents" / "skills"
        claude_root = root / ".claude" / "skills"
        if canonical_root.is_dir():
            for source in canonical_root.rglob("*"):
                if not source.is_file():
                    continue
                rel = source.relative_to(canonical_root)
                target = claude_root / rel
                if not target.is_file() or sha256_file(source) != sha256_file(target):
                    projection_mismatches.append(rel.as_posix())
    adapter_sizes = {
        rel: (root / rel).stat().st_size
        for rel in ("CLAUDE.md", ".github/copilot-instructions.md")
        if (root / rel).is_file() and (root / rel).stat().st_size > 1024
    }
    from nexus.cli.tools.doctor import diagnose
    from nexus.cli.tools.health import _check_secrets

    readiness = diagnose(root, deep=False, consumer="all")
    secrets = _check_secrets(root)
    return {
        "consumers": consumers,
        "duplicate_lines": duplicates[:25],
        "duplicate_line_count": len(duplicates),
        "largest_context_candidates": [{"path": p, "bytes": s} for s, p in largest[:10]],
        "ignore_coverage": ignore_coverage,
        "journal": {"initialized": state_path.exists(), "state_path": ".nexus/state.json"},
        "repomix": {"available": shutil.which("repomix") is not None},
        "readiness": {
            "status": readiness.get("status", "fail"),
            "failures": readiness.get("details", {}).get("failures", 0),
            "warnings": readiness.get("details", {}).get("warnings", 0),
        },
        "secrets": secrets,
        "installation": {
            "manifest_present": manifest is not None,
            "skill_issues": skill_issues,
            "claude_projection_mismatches": projection_mismatches[:25],
            "oversized_adapters": adapter_sizes,
            "legacy_windsurf_present": (root / ".windsurf").exists(),
            "legacy_artifacts": [
                rel for rel in (".cursorrules", ".windsurf/rules", ".windsurf/skills", ".windsurf/workflows")
                if (root / rel).exists()
            ],
        },
    }


def audit_status(details: dict[str, Any]) -> Status:
    """Derive a truthful CLI status from context audit evidence."""
    installation = details.get("installation", {})
    consumers = details.get("consumers", {})
    canonical = consumers.get("codex", {})
    if (
        details.get("readiness", {}).get("status") == "fail"
        or details.get("secrets", {}).get("secrets_found", 0) > 0
        or not installation.get("manifest_present")
        or installation.get("skill_issues")
        or installation.get("claude_projection_mismatches")
        or "AGENTS.md" not in canonical.get("files", [])
        or canonical.get("skill_count", 0) == 0
    ):
        return Status.FAIL
    cursor_ignore = details.get("ignore_coverage", {}).get("cursor", {})
    if (
        details.get("readiness", {}).get("status") == "warn"
        or details.get("secrets", {}).get("coverage") == "none"
        or details.get("duplicate_line_count", 0)
        or cursor_ignore.get("missing")
        or not details.get("journal", {}).get("initialized")
        or installation.get("oversized_adapters")
        or installation.get("legacy_windsurf_present")
        or installation.get("legacy_artifacts")
    ):
        return Status.WARN
    return Status.PASS


def _python_symbols(path: Path) -> list[str]:
    try:
        tree = ast.parse(_read_text(path))
    except (OSError, SyntaxError):
        return []
    symbols: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            symbols.append(f"{node.__class__.__name__[:-3].lower()} {node.name}({', '.join(args)})")
        elif isinstance(node, ast.ClassDef):
            symbols.append(f"class {node.name}")
    return symbols


def _inventory_map(root: Path, query: Optional[str], max_chars: int) -> str:
    needle = query.lower() if query else None
    lines = [f"# Repository map: {root.name}"]
    candidates: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"AGENTS.md", "CLAUDE.md", "README.md"}:
            continue
        rel = _relative(path, root)
        if needle and needle not in rel.lower():
            try:
                if needle not in _read_text(path).lower():
                    continue
            except OSError:
                continue
        candidates.append(path)
    for path in candidates:
        rel = _relative(path, root)
        symbols = _python_symbols(path) if path.suffix.lower() == ".py" else []
        entry = f"\n- `{rel}`"
        if symbols:
            entry += "\n  - " + "\n  - ".join(symbols)
        if len("\n".join(lines)) + len(entry) > max_chars:
            lines.append(f"\n[omitted {len(candidates) - candidates.index(path)} files: token budget reached]")
            break
        lines.append(entry)
    return "\n".join(lines).rstrip() + "\n"


def build_map(project_dir: Path, query: Optional[str], engine: str, budget_tokens: int) -> dict[str, Any]:
    root = project_dir.resolve()
    max_chars = max(256, budget_tokens * 4)
    if engine == "repomix":
        exe = shutil.which("repomix")
        if not exe:
            content = _inventory_map(root, query, max_chars)
            return {"engine": "inventory", "fallback": "repomix-not-installed", "content": content, "estimated_tokens": _estimate_tokens(len(content))}
        command = [exe, str(root), "--stdout"]
        if query:
            command.extend(["--include", f"**/*{query}*"])
        try:
            proc = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            content = _inventory_map(root, query, max_chars)
            return {"engine": "inventory", "fallback": f"repomix-error:{type(exc).__name__}", "content": content, "estimated_tokens": _estimate_tokens(len(content))}
        if proc.returncode == 0:
            content = proc.stdout[:max_chars]
            return {"engine": "repomix", "truncated": len(proc.stdout) > max_chars, "content": content, "estimated_tokens": _estimate_tokens(len(content))}
        content = _inventory_map(root, query, max_chars)
        return {"engine": "inventory", "fallback": f"repomix-exit-{proc.returncode}", "content": content, "estimated_tokens": _estimate_tokens(len(content))}
    content = _inventory_map(root, query, max_chars)
    return {"engine": "inventory", "content": content, "estimated_tokens": _estimate_tokens(len(content))}


def redact_secrets(text: str) -> tuple[str, int]:
    redacted = text
    count = 0
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 3:
            redacted, n = pattern.subn(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", redacted)
        else:
            redacted, n = pattern.subn("[REDACTED]", redacted)
        count += n
    return redacted, count


def mask_observation(text: str, kind: str, exit_code: int, max_chars: int) -> dict[str, Any]:
    redacted, secret_count = redact_secrets(text)
    lines = redacted.splitlines()
    failure_re = re.compile(r"(?i)(error|fail(?:ed|ure)?|exception|traceback|fatal|warning)")
    failures = [line.strip() for line in lines if failure_re.search(line)][:20]
    counts = {
        "lines": len(lines),
        "errors": len(re.findall(r"(?i)\berrors?\b", redacted)),
        "failures": len(re.findall(r"(?i)\bfail(?:ed|ure|ures)?\b", redacted)),
        "warnings": len(re.findall(r"(?i)\bwarnings?\b", redacted)),
        "passed": len(re.findall(r"(?i)\bpassed\b", redacted)),
    }
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
    compact = "\n".join(failures)
    if not compact:
        compact = "\n".join(lines[-10:])
    compact = compact[:max_chars]
    return {
        "kind": kind,
        "outcome": "pass" if exit_code == 0 else "fail",
        "exit_code": exit_code,
        "counts": counts,
        "failure_signatures": compact.splitlines(),
        "omitted_chars": max(0, len(redacted) - len(compact)),
        "redactions": secret_count,
        "sha256": digest,
    }


def read_mask_input(project_dir: Path, input_value: str) -> str:
    if input_value == "-":
        return sys.stdin.read()
    root = project_dir.resolve()
    candidate = (root / input_value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("input path must stay within project-dir") from exc
    if not candidate.is_file():
        raise ValueError(f"input file not found: {input_value}")
    return _read_text(candidate)


def manage_ignores(project_dir: Path, tool: str, apply: bool) -> dict[str, Any]:
    root = project_dir.resolve()
    names = list(IGNORE_FILES) if tool == "all" else [tool]
    results = []
    body = "# Context-heavy generated/runtime artifacts\n" + "\n".join(IGNORE_PATTERNS)
    for name in names:
        path = root / IGNORE_FILES[name]
        existing = _read_text(path) if path.exists() else ""
        missing = [p for p in IGNORE_PATTERNS if p not in existing]
        action = "would-update" if missing else "unchanged"
        if apply and missing:
            action = upsert_managed_block(path, body, "context-ignore")
        results.append({"tool": name, "path": IGNORE_FILES[name], "missing": missing, "action": action})
    return {"applied": apply, "results": results}


ROUTES = {
    "mechanical": {"role": "execution", "capabilities": ["fast edits", "formatting", "deterministic transforms"], "verification": "targeted check"},
    "routine": {"role": "implementation", "capabilities": ["multi-file coding", "unit tests", "local debugging"], "verification": "targeted tests"},
    "complex": {"role": "reasoning", "capabilities": ["architecture", "root-cause analysis", "schema design"], "verification": "full relevant suite"},
    "high-risk": {"role": "review-and-reasoning", "capabilities": ["security review", "migration design", "threat modeling"], "verification": "independent review and full gates"},
}


def route_task(task_class: str) -> dict[str, Any]:
    return {"task_class": task_class, **ROUTES[task_class], "advisory_only": True}


def _frontmatter_valid(text: str) -> bool:
    if not text.startswith("---\n"):
        return False
    parts = text.split("---", 2)
    return len(parts) == 3 and "name:" in parts[1] and "description:" in parts[1]


LEGACY_SKILL_ALIASES = {
    "research-investigate": "research",
    "webscrape": "scrape-docs",
    "create-tool": "create-cli-tool",
    "bootstrap-wizard": "nexus-onboard",
    "migrate-toolkit": "nexus-onboard",
}


def migrate_legacy_skills(project_dir: Path, apply: bool = False) -> dict[str, Any]:
    """Preview or copy legacy Windsurf skills/workflows into `.agents/skills`."""
    root = project_dir.resolve()
    legacy_skills = root / ".windsurf" / "skills"
    legacy_workflows = root / ".windsurf" / "workflows"
    target_root = root / ".agents" / "skills"
    items: list[dict[str, Any]] = []
    sources: list[tuple[str, Path, Path]] = []
    if legacy_skills.is_dir():
        for source_dir in sorted(p for p in legacy_skills.iterdir() if p.is_dir()):
            source = source_dir / "SKILL.md"
            if source.is_file():
                target_name = LEGACY_SKILL_ALIASES.get(source_dir.name, source_dir.name)
                sources.append(("skill", source, target_root / target_name / "SKILL.md"))
    if legacy_workflows.is_dir():
        for source in sorted(legacy_workflows.glob("*.md")):
            target_name = LEGACY_SKILL_ALIASES.get(source.stem, source.stem)
            sources.append(("workflow", source, target_root / target_name / "SKILL.md"))

    seen: set[Path] = set()
    for kind, source, target in sources:
        source_name = source.parent.name if kind == "skill" else source.stem
        consolidated = source_name in LEGACY_SKILL_ALIASES
        collision = target in seen or target.exists()
        seen.add(target)
        text = _read_text(source)
        if not text.startswith("---\n"):
            title = source.stem.replace("-", " ").title()
            text = f"---\nname: {target.parent.name}\ndescription: {title}\n---\n\n{text.lstrip()}"
        else:
            frontmatter = text.split("---", 2)[1]
            if "name:" not in frontmatter:
                text = text.replace("---\n", f"---\nname: {target.parent.name}\n", 1)
            elif consolidated:
                text = re.sub(
                    r"(?m)^name:\s*[^\n]+$",
                    f"name: {target.parent.name}",
                    text,
                    count=1,
                )
        text = (
            text.replace(".windsurf/", ".agents/")
            .replace("Windsurf", "AI coding agent")
            .replace("Cascade", "AI coding agent")
        )
        status = "consolidated" if consolidated else ("collision" if collision else "would-create")
        if apply and not collision and not consolidated:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            status = "created"
        items.append({"kind": kind, "source": _relative(source, root), "target": _relative(target, root), "status": status, "valid": _frontmatter_valid(text)})
    return {
        "apply": apply,
        "items": items,
        "created": sum(i["status"] == "created" for i in items),
        "collisions": sum(i["status"] == "collision" for i in items),
        "consolidated": sum(i["status"] == "consolidated" for i in items),
    }


def emit_context_result(tool: str, details: dict[str, Any], output_format: str, status: Status = Status.PASS) -> None:
    emit(make_result(tool, status, details=details), OutputFormat(output_format))
