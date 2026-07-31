"""Deterministic installation of Nexus-owned project resources.

The project copy under ``.agents/skills`` is the canonical editable surface.
The package bundle is only the source used for first install and safe upgrades.
Claude receives a byte-equivalent projection under ``.claude/skills`` because
Claude Code does not discover the canonical open location directly.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from nexus.cli.profile import NEXUS_VERSION

if TYPE_CHECKING:
    from nexus.cli.generators import GeneratedFile

MANIFEST_REL = Path(".nexus/install-manifest.json")
MANIFEST_SCHEMA = 1
ALL_CONSUMERS = ("codex", "devin", "claude", "cursor", "copilot", "devin-review")
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


@dataclass(frozen=True)
class InstallAction:
    path: str
    action: str
    source: str
    detail: str = ""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def parse_consumers(value: str | Iterable[str] | None) -> tuple[str, ...]:
    if value is None or value == "all":
        return ALL_CONSUMERS
    raw = value.split(",") if isinstance(value, str) else list(value)
    selected: list[str] = []
    for item in raw:
        name = item.strip().lower()
        if not name:
            continue
        if name == "all":
            return ALL_CONSUMERS
        if name not in ALL_CONSUMERS:
            raise ValueError(
                f"Unknown consumer '{name}'. Choose from: all, {', '.join(ALL_CONSUMERS)}"
            )
        if name not in selected:
            selected.append(name)
    return tuple(selected) or ALL_CONSUMERS


def load_manifest(project_dir: Path) -> dict[str, Any] | None:
    path = project_dir / MANIFEST_REL
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_manifest(project_dir: Path, manifest: dict[str, Any]) -> Path:
    path = project_dir / MANIFEST_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def ensure_gitignore(project_dir: Path, *, dry_run: bool = False) -> InstallAction:
    """Install a small idempotent safety block without replacing user rules."""
    rel = ".gitignore"
    path = project_dir / rel
    begin = "# nexus:project-safety:begin"
    end = "# nexus:project-safety:end"
    body = "\n".join(
        (
            begin,
            ".venv/",
            ".cache/",
            ".env",
            ".env.*",
            "*.key",
            "*.pem",
            ".nexus/*",
            "!.nexus/profile.json",
            "!.nexus/install-manifest.json",
            end,
            "",
        )
    )
    existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    if begin in existing and end in existing:
        before, _, rest = existing.partition(begin)
        _, _, after = rest.partition(end)
        desired = before + body.rstrip("\n") + "\n" + after.lstrip("\r\n")
        action = "unchanged" if desired == existing else "update"
    else:
        separator = "" if not existing else ("\n" if existing.endswith("\n") else "\n\n")
        desired = existing + separator + body
        action = "create" if not path.exists() else "update"
    if not dry_run and action != "unchanged":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(desired, encoding="utf-8")
    return InstallAction(rel, action, "nexus:project-safety")


def _bundle_skill_files() -> dict[str, bytes]:
    root = resources.files("nexus.bundles.default").joinpath("skills")
    found: dict[str, bytes] = {}

    def walk(node: Any, prefix: Path = Path()) -> None:
        for child in node.iterdir():
            rel = prefix / child.name
            if child.is_dir():
                walk(child, rel)
            else:
                found[rel.as_posix()] = child.read_bytes()

    walk(root)
    return found


def bundled_skill_files() -> dict[str, bytes]:
    """Return a copy of the recursively packaged default skill bundle."""
    return dict(_bundle_skill_files())


def _render_generated(existing: str, generated: "GeneratedFile") -> str:
    if generated.mode == "overwrite":
        return generated.content
    from nexus.cli.generators import begin_marker, end_marker

    begin = begin_marker(generated.block_id)
    end = end_marker(generated.block_id)
    block = f"{begin}\n{generated.content.rstrip()}\n{end}\n"
    if begin in existing and end in existing:
        before, _, rest = existing.partition(begin)
        _, _, after = rest.partition(end)
        return before + block.rstrip("\n") + "\n" + after.lstrip("\n")
    separator = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    return existing + separator + block


def apply_generated_files(
    project_dir: Path,
    generated_files: Iterable["GeneratedFile"],
    *,
    tier: str,
    consumers: tuple[str, ...],
    dry_run: bool = False,
    force: bool = False,
) -> list[InstallAction]:
    """Apply generated surfaces with manifest-aware collision preservation."""
    project_dir = project_dir.resolve()
    previous = load_manifest(project_dir) or {}
    previous_files = previous.get("files", {}) if isinstance(previous, dict) else {}
    actions: list[InstallAction] = []
    desired_by_rel: dict[str, bytes] = {}

    for generated in generated_files:
        rel = generated.path.relative_to(project_dir).as_posix()
        target = project_dir / rel
        existing = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
        desired = _render_generated(existing, generated).encode("utf-8")
        desired_by_rel[rel] = desired
        if not target.exists():
            action = "create"
        elif target.read_bytes() == desired:
            action = "unchanged"
        else:
            prior = previous_files.get(rel, {}) if isinstance(previous_files, dict) else {}
            prior_hash = prior.get("sha256") if isinstance(prior, dict) else None
            owned_unchanged = bool(prior_hash and sha256_file(target) == prior_hash)
            from nexus.cli.generators import begin_marker, end_marker

            has_managed_block = (
                begin_marker(generated.block_id) in existing
                and end_marker(generated.block_id) in existing
            )
            safe_initial_agents_insert = generated.target == "agents_md" and not has_managed_block
            if force or owned_unchanged:
                action = "update"
            elif safe_initial_agents_insert:
                action = "inserted"
            else:
                action = "preserve"
        detail = ""
        if action == "preserve":
            detail = "unowned or user-modified collision"
        actions.append(InstallAction(rel, action, f"generator:{generated.target}", detail))

    if dry_run:
        return actions

    for action in actions:
        if action.action not in {"create", "update", "inserted"}:
            continue
        target = project_dir / action.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(desired_by_rel[action.path])

    files = dict(previous_files) if isinstance(previous_files, dict) else {}
    for action in actions:
        target = project_dir / action.path
        if target.is_file() and action.action != "preserve":
            files[action.path] = {"sha256": sha256_file(target), "source": action.source}
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "nexus_version": NEXUS_VERSION,
        "tier": tier,
        "consumers": list(consumers),
        "files": files,
    }
    save_manifest(project_dir, manifest)
    return actions


def validate_skill(skill_dir: Path) -> list[str]:
    """Return portable Agent Skills validation errors for one directory."""
    errors: list[str] = []
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return ["missing SKILL.md"]
    if not SKILL_NAME_RE.fullmatch(skill_dir.name) or len(skill_dir.name) > 64:
        errors.append("directory name must be lowercase hyphenated text (max 64 chars)")
    try:
        text = skill_file.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read SKILL.md: {exc}"]
    if len(text.splitlines()) > 500:
        errors.append("SKILL.md exceeds 500 lines")
    if not text.startswith("---\n"):
        errors.append("missing YAML frontmatter")
        return errors
    end = text.find("\n---", 4)
    if end < 0:
        errors.append("unterminated YAML frontmatter")
        return errors
    try:
        import yaml

        metadata = yaml.safe_load(text[4:end]) or {}
    except Exception as exc:
        errors.append(f"invalid YAML frontmatter: {type(exc).__name__}")
        return errors
    if not isinstance(metadata, dict):
        errors.append("frontmatter must be a mapping")
        return errors
    name = metadata.get("name")
    description = metadata.get("description")
    if name != skill_dir.name:
        errors.append(f"name must match directory ({skill_dir.name})")
    if not isinstance(description, str) or not description.strip():
        errors.append("description is required")
    elif len(description) > 1024:
        errors.append("description exceeds 1024 characters")
    if "auto_execution_mode" in metadata:
        errors.append("auto_execution_mode is not portable Agent Skills frontmatter")
    for raw_target in MARKDOWN_LINK_RE.findall(text[end + 4 :]):
        target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
        if not target or target.startswith("#") or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
            continue
        # Normalize using POSIX semantics because skills are portable across hosts.
        from pathlib import PurePosixPath

        portable = PurePosixPath(target.split("#", 1)[0].replace("\\", "/"))
        if portable.is_absolute() or ".." in portable.parts:
            errors.append(f"unsafe relative reference: {target}")
        elif not (skill_dir / Path(*portable.parts)).exists():
            errors.append(f"missing relative reference: {target}")
    return errors


def validate_skill_tree(root: Path) -> dict[str, list[str]]:
    if not root.is_dir():
        return {"<root>": ["skills directory is missing"]}
    issues: dict[str, list[str]] = {}
    for child in sorted(root.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            errors = validate_skill(child)
            if errors:
                issues[child.name] = errors
    return issues


def _plan_file(
    project_dir: Path,
    rel: str,
    data: bytes,
    previous_files: dict[str, Any],
    *,
    source: str,
    claim_unowned: bool,
) -> InstallAction:
    target = project_dir / rel
    if not target.exists():
        return InstallAction(rel, "create", source)
    current = sha256_file(target)
    desired = sha256_bytes(data)
    if current == desired:
        return InstallAction(rel, "unchanged", source)
    prior = previous_files.get(rel, {}) if isinstance(previous_files, dict) else {}
    prior_hash = prior.get("sha256") if isinstance(prior, dict) else None
    if prior_hash and current == prior_hash:
        return InstallAction(rel, "update", source)
    if claim_unowned:
        return InstallAction(rel, "preserve", source, "unowned or user-modified collision")
    return InstallAction(rel, "update", source, "refreshing generated projection")


def install_skills(
    project_dir: Path,
    *,
    consumers: tuple[str, ...],
    tier: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Plan/apply bundled canonical skills and Claude's native projection."""
    project_dir = project_dir.resolve()
    previous = load_manifest(project_dir) or {}
    previous_files = previous.get("files", {}) if isinstance(previous, dict) else {}
    bundle = _bundle_skill_files()
    actions: list[InstallAction] = []

    for bundle_rel, data in sorted(bundle.items()):
        rel = f".agents/skills/{bundle_rel}"
        actions.append(
            _plan_file(
                project_dir,
                rel,
                data,
                previous_files,
                source=f"bundle:{bundle_rel}",
                claim_unowned=True,
            )
        )

    if not dry_run:
        for action in actions:
            if action.action not in {"create", "update"}:
                continue
            bundle_rel = action.path.removeprefix(".agents/skills/")
            target = project_dir / action.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle[bundle_rel])

    # Claude mirrors every valid canonical project skill, including user skills.
    projection_actions: list[InstallAction] = []
    canonical_root = project_dir / ".agents" / "skills"
    if "claude" in consumers:
        canonical_files: dict[str, bytes] = {}
        if canonical_root.is_dir():
            for path in sorted(canonical_root.rglob("*")):
                if path.is_file():
                    canonical_files[path.relative_to(canonical_root).as_posix()] = path.read_bytes()
        elif dry_run:
            canonical_files = dict(bundle)
        for skill_rel, data in canonical_files.items():
            rel = f".claude/skills/{skill_rel}"
            projection_actions.append(
                _plan_file(
                    project_dir,
                    rel,
                    data,
                    previous_files,
                    source=f"projection:.agents/skills/{skill_rel}",
                    claim_unowned=True,
                )
            )
        if not dry_run:
            for action in projection_actions:
                if action.action not in {"create", "update"}:
                    continue
                source_rel = action.path.removeprefix(".claude/skills/")
                data = canonical_files[source_rel]
                target = project_dir / action.path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)

    all_actions = actions + projection_actions
    if dry_run:
        return {"actions": [a.__dict__ for a in all_actions], "manifest": previous}

    files: dict[str, dict[str, str]] = {}
    for action in all_actions:
        target = project_dir / action.path
        if target.is_file() and action.action != "preserve":
            files[action.path] = {"sha256": sha256_file(target), "source": action.source}
        elif action.action == "preserve" and action.path in previous_files:
            files[action.path] = previous_files[action.path]
    # Retain hashes for other Nexus-managed files recorded by the caller.
    for rel, metadata in previous_files.items() if isinstance(previous_files, dict) else ():
        if rel not in files and not rel.startswith((".agents/skills/", ".claude/skills/")):
            files[rel] = metadata
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "nexus_version": NEXUS_VERSION,
        "tier": tier,
        "consumers": list(consumers),
        "files": files,
    }
    save_manifest(project_dir, manifest)
    return {"actions": [a.__dict__ for a in all_actions], "manifest": manifest}


def record_managed_files(project_dir: Path, paths: Iterable[Path]) -> dict[str, Any]:
    manifest = load_manifest(project_dir) or {
        "schema_version": MANIFEST_SCHEMA,
        "nexus_version": NEXUS_VERSION,
        "tier": "fast",
        "consumers": list(ALL_CONSUMERS),
        "files": {},
    }
    files = manifest.setdefault("files", {})
    for path in paths:
        if path.is_file():
            rel = path.relative_to(project_dir).as_posix()
            files[rel] = {"sha256": sha256_file(path), "source": "generator"}
    save_manifest(project_dir, manifest)
    return manifest
