"""
Project profile -- single source of truth for cross-IDE generation.

A ``Profile`` captures the project's tier, detected stack (languages,
frameworks, package managers, test runner, CI, deployment), and a list
of ``Rule`` objects. Generators (in ``nexus.cli.generators``) project
this onto IDE-specific files: AGENTS.md, CLAUDE.md, .cursor/rules/,
.github/copilot-instructions.md.

The profile is stored as ``.nexus/profile.json`` and is the input to
both ``nexus generate`` and ``nexus doctor``.

Design notes:
- The data model is a plain dataclass (not Pydantic) because we don't
  ship Pydantic and the validation surface is small.
- Tuples (not lists) for fields that should be hashable / treated as
  immutable -- JSON serialization happens through ``to_dict``.
- ``hash_profile`` returns a 12-char sha256 prefix used as the drift
  fingerprint stamped into every generated file.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

from nexus import __version__

PROFILE_REL = ".nexus/profile.json"
NEXUS_VERSION = __version__

Tier = Literal["fast", "team", "enterprise"]
Severity = Literal["info", "warn", "must"]
Target = Literal["agents_md", "claude", "cursor", "copilot", "devin-review"]
ALL_TARGETS: tuple[Target, ...] = (
    "agents_md", "claude", "cursor", "copilot", "devin-review",
)
_TIER_ORDER = {"fast": 0, "team": 1, "enterprise": 2}


@dataclass(frozen=True)
class Rule:
    """A single convention/constraint emitted to one or more IDE rule files.

    ``nexus_managed`` distinguishes seed rules (composed by ``compose_rules``,
    default ``True``) from user-authored ones (default ``False`` when loaded
    from disk without the field set, which is the case for hand-added rules).

    On ``profile detect`` re-runs, managed rules are replaced wholesale from
    the current seed library; unmanaged rules are preserved verbatim. This
    is how users add custom rules without losing them on the next upgrade.
    """

    id: str
    text: str
    severity: Severity = "must"
    applies_to: tuple[str, ...] = ()
    targets: Optional[tuple[Target, ...]] = None
    tier_min: Tier = "fast"
    nexus_managed: bool = False


@dataclass
class Profile:
    """Everything needed to regenerate IDE rule files for a project."""

    nexus_version: str
    tier: Tier
    project_name: str
    languages: tuple[str, ...] = ()
    frameworks: tuple[str, ...] = ()
    package_managers: tuple[str, ...] = ()
    test_runner: Optional[str] = None
    ci: Optional[str] = None
    deployment: Optional[str] = None
    rules: tuple[Rule, ...] = ()
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # asdict converts tuples -> tuples; json.dumps handles those as arrays.
        # Normalize Rule.targets None -> None (asdict already keeps it).
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        rules_raw = data.get("rules", []) or []
        rules = tuple(
            Rule(
                id=r["id"],
                text=r["text"],
                severity=r.get("severity", "must"),
                applies_to=tuple(r.get("applies_to", ()) or ()),
                targets=tuple(r["targets"]) if r.get("targets") else None,
                tier_min=r.get("tier_min", "fast"),
                # Default to False so a user who hand-adds a rule (and thus
                # omits this field) gets it preserved on the next detect.
                nexus_managed=bool(r.get("nexus_managed", False)),
            )
            for r in rules_raw
        )
        return cls(
            nexus_version=data.get("nexus_version", NEXUS_VERSION),
            tier=data.get("tier", "fast"),
            project_name=data.get("project_name", "project"),
            languages=tuple(data.get("languages", ()) or ()),
            frameworks=tuple(data.get("frameworks", ()) or ()),
            package_managers=tuple(data.get("package_managers", ()) or ()),
            test_runner=data.get("test_runner"),
            ci=data.get("ci"),
            deployment=data.get("deployment"),
            rules=rules,
            extras=dict(data.get("extras", {}) or {}),
        )


def hash_profile(profile: Profile) -> str:
    """Return first 12 chars of sha256 of the canonical JSON form."""
    canonical = json.dumps(profile.to_dict(), sort_keys=True, separators=(",", ":"), default=list)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def load(project_dir: Path) -> Optional[Profile]:
    """Load profile from ``<project_dir>/.nexus/profile.json``. Returns None if missing/unreadable."""
    path = project_dir / PROFILE_REL
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Profile.from_dict(data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None


def save(project_dir: Path, profile: Profile) -> Path:
    path = project_dir / PROFILE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(profile.to_dict(), indent=2, default=list) + "\n",
        encoding="utf-8",
    )
    return path


def from_detection(
    project_dir: Path,
    *,
    tier: Tier = "fast",
    project_name: Optional[str] = None,
) -> Profile:
    """Build a Profile by composing _detect_stack + _detect_project + seed rules."""
    # Lazy imports to avoid coupling profile.py to tools/* at module load.
    from nexus.cli.tools.local_env import _detect_stack
    from nexus.cli.tools.smoketest import _detect_project
    from nexus.cli.profile_seeds import compose_rules

    stack = _detect_stack(project_dir)
    info = _detect_project(project_dir)

    # --- Languages ---
    langs: list[str] = []
    proj_type = info.get("type", "unknown")
    if proj_type in ("python", "fullstack"):
        langs.append("python")
    if proj_type in ("node", "fullstack"):
        # Prefer typescript if any .ts config is present.
        if (project_dir / "tsconfig.json").exists() or (project_dir / "tsconfig.base.json").exists():
            langs.append("typescript")
        else:
            langs.append("javascript")
    if proj_type == "go":
        langs.append("go")

    # --- Frameworks ---
    fw = stack.get("stack")
    frameworks: list[str] = []
    if fw and fw not in ("unknown", "node", "python"):
        frameworks.append(fw)

    # --- Package managers ---
    pms: list[str] = []
    if info.get("package_manager"):
        pms.append(info["package_manager"])
    if "python" in langs and "pip" not in pms:
        pms.append("pip")
    if "go" in langs and "go" not in pms:
        pms.append("go")

    # --- Multi-repo: merge sub-repo stacks into the parent ---
    # The wizard explicitly anticipates polyrepo / multi-app projects (per
    # nexus/Bootstrap-Project-Intake.md and nexus/Universal-Bootstrap.md).
    # When the actual code lives in a nested standalone git repo (e.g. a
    # parent project with a webapp/ repo), detection on the parent alone
    # misses the real stack. Walk discovered sub-repos and merge their
    # languages / frameworks / package_managers into the parent's lists so
    # the seed-rule library composes rules covering the full polyrepo.
    # Per-sub-repo detail is recorded in extras["sub_repos"] for visibility
    # and so generators can emit a "Sub-repositories" section.
    sub_repo_records: list[dict[str, Any]] = []
    try:
        from nexus.cli.tools.journal import _find_sub_git_repos, _resolve_git_root
        parent_git_root = _resolve_git_root(project_dir)
        sub_paths = _find_sub_git_repos(project_dir, parent_git_root)
    except Exception:
        sub_paths = []

    for sub_path in sub_paths:
        try:
            sub_stack = _detect_stack(sub_path)
            sub_info = _detect_project(sub_path)
        except Exception:
            continue
        sub_type = sub_info.get("type", "unknown")
        sub_langs: list[str] = []
        if sub_type in ("python", "fullstack"):
            sub_langs.append("python")
        if sub_type in ("node", "fullstack"):
            if (sub_path / "tsconfig.json").exists() or (sub_path / "tsconfig.base.json").exists():
                sub_langs.append("typescript")
            else:
                sub_langs.append("javascript")
        if sub_type == "go":
            sub_langs.append("go")
        sub_fw = sub_stack.get("stack")
        sub_frameworks: list[str] = []
        if sub_fw and sub_fw not in ("unknown", "node", "python"):
            sub_frameworks.append(sub_fw)
        sub_pms: list[str] = []
        if sub_info.get("package_manager"):
            sub_pms.append(sub_info["package_manager"])
        if "python" in sub_langs and "pip" not in sub_pms:
            sub_pms.append("pip")
        if "go" in sub_langs and "go" not in sub_pms:
            sub_pms.append("go")

        # Merge into parent's lists, preserving order + uniqueness.
        for l in sub_langs:
            if l not in langs:
                langs.append(l)
        for f in sub_frameworks:
            if f not in frameworks:
                frameworks.append(f)
        for pm in sub_pms:
            if pm not in pms:
                pms.append(pm)

        try:
            rel = sub_path.relative_to(project_dir).as_posix()
        except ValueError:
            rel = sub_path.name
        sub_repo_records.append({
            "path": rel,
            "languages": sub_langs,
            "frameworks": sub_frameworks,
            "package_managers": sub_pms,
        })

    # --- Test runner ---
    # Detect from the actual script body (package.json) or from pyproject.toml,
    # not from the smoketest-generated "npm run test" wrapper which loses the
    # underlying tool name.
    test_runner: Optional[str] = None
    if "python" in langs:
        py_text = ""
        try:
            if (project_dir / "pyproject.toml").exists():
                py_text = (project_dir / "pyproject.toml").read_text(encoding="utf-8")
        except OSError:
            pass
        if "pytest" in py_text or info.get("commands", {}).get("test", "").startswith("pytest"):
            test_runner = "pytest"
    if test_runner is None and (project_dir / "package.json").exists():
        try:
            pkg = json.loads((project_dir / "package.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pkg = {}
        scripts = pkg.get("scripts", {}) or {}
        test_script = (scripts.get("test") or "").lower()
        if "vitest" in test_script:
            test_runner = "vitest"
        elif "jest" in test_script:
            test_runner = "jest"
        elif "playwright" in test_script:
            test_runner = "playwright"
        elif test_script:
            # Best-effort: first token of the script (e.g. "mocha", "ava")
            test_runner = test_script.split()[0]
    if test_runner is None and "go" in langs:
        test_runner = "go-test"

    # --- CI ---
    ci: Optional[str] = None
    if (project_dir / ".github" / "workflows").is_dir():
        ci = "github-actions"
    elif (project_dir / ".gitlab-ci.yml").exists():
        ci = "gitlab-ci"
    elif (project_dir / ".circleci").is_dir():
        ci = "circleci"

    # --- Deployment ---
    deployment: Optional[str] = None
    if (project_dir / "vercel.json").exists():
        deployment = "vercel"
    elif any((project_dir / d).is_dir() for d in ("k8s", "kubernetes", "manifests")):
        deployment = "k8s"
    elif info.get("has_dockerfile"):
        deployment = "docker"

    seed_rules = compose_rules(
        tier=tier,
        languages=tuple(langs),
        frameworks=tuple(frameworks),
    )

    # Preserve user-authored rules + extras from any existing profile so
    # `nexus profile detect` is non-destructive.
    existing = load(project_dir)
    user_rules: tuple[Rule, ...] = ()
    extras: dict[str, Any] = {}
    if existing is not None:
        seed_ids = {r.id for r in seed_rules}
        user_rules = tuple(
            r for r in existing.rules
            if not r.nexus_managed and r.id not in seed_ids
        )
        extras = dict(existing.extras)

    # Refresh the detection-derived sub_repos record. User-authored extras keys
    # are preserved; only `sub_repos` is overwritten (or removed if none found).
    if sub_repo_records:
        extras["sub_repos"] = sub_repo_records
    elif "sub_repos" in extras:
        del extras["sub_repos"]

    return Profile(
        nexus_version=NEXUS_VERSION,
        tier=tier,
        project_name=project_name or (existing.project_name if existing else project_dir.name) or "project",
        languages=tuple(langs),
        frameworks=tuple(frameworks),
        package_managers=tuple(pms),
        test_runner=test_runner,
        ci=ci,
        deployment=deployment,
        rules=seed_rules + user_rules,
        extras=extras,
    )


def select_rules(
    profile: Profile,
    *,
    target: Target,
    only_global: bool = False,
    only_scoped: bool = False,
) -> list[Rule]:
    """Filter ``profile.rules`` to those active for ``profile.tier`` and ``target``.

    - ``only_global=True``: rules without ``applies_to`` (whole-repo)
    - ``only_scoped=True``: rules with at least one glob in ``applies_to``
    """
    p_tier = _TIER_ORDER.get(profile.tier, 0)
    out: list[Rule] = []
    for r in profile.rules:
        if _TIER_ORDER.get(r.tier_min, 0) > p_tier:
            continue
        if r.targets is not None and target not in r.targets:
            continue
        if only_global and r.applies_to:
            continue
        if only_scoped and not r.applies_to:
            continue
        out.append(r)
    return out
