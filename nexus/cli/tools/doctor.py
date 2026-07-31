"""Authoritative Nexus installation, discovery, and drift diagnostics."""

from __future__ import annotations

import importlib.metadata
import sys
from pathlib import Path
from typing import Any

import click

from nexus import __version__
from nexus.cli.generators import run_all
from nexus.cli.installation import (
    ALL_CONSUMERS,
    bundled_skill_files,
    load_manifest,
    parse_consumers,
    sha256_file,
    validate_skill_tree,
)
from nexus.cli.profile import NEXUS_VERSION, from_detection, hash_profile, load
from nexus.cli.utils import OutputFormat, Status, emit, make_result

DOCTOR_CONSUMERS = ALL_CONSUMERS + ("vscode",)


def _read_stamp_hash(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    needle = "<!-- nexus: profile="
    idx = text.find(needle)
    if idx < 0:
        return None
    start = idx + len(needle)
    return text[start : start + 12] or None


def _check_file(path: Path, expected_hash: str) -> tuple[str, str]:
    if not path.exists():
        return ("missing", "file not present")
    found = _read_stamp_hash(path)
    if found is None:
        return ("unstamped", "no profile stamp -- file is user-owned or pre-Nexus")
    if found != expected_hash:
        return ("drift", f"stamp={found}, expected={expected_hash}")
    return ("ok", "stamp current")


def _targets(consumers: tuple[str, ...]) -> list[str]:
    targets = ["agents_md"]
    if "claude" in consumers or "devin-review" in consumers:
        targets.append("claude")
    if "cursor" in consumers or "devin-review" in consumers:
        targets.append("cursor")
    if "copilot" in consumers:
        targets.append("copilot")
    if "devin-review" in consumers:
        targets.append("devin-review")
    return targets


def _review_duplicates(project_dir: Path) -> list[dict[str, Any]]:
    """Find substantive shared-rule duplication across Devin Review inputs."""
    paths = [project_dir / "AGENTS.md", project_dir / "CLAUDE.md", project_dir / "REVIEW.md"]
    paths.extend(sorted((project_dir / ".cursor" / "rules").glob("*.mdc")))
    occurrences: dict[str, set[str]] = {}
    for path in paths:
        if not path.is_file():
            continue
        rel = path.relative_to(project_dir).as_posix()
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = " ".join(raw.strip().lower().split())
            if (
                len(line) < 32
                or line.startswith(("#", "<!--", "---", "@agents.md"))
                or "canonical" in line
                or ".agents/skills" in line
                or ".claude/skills" in line
            ):
                continue
            occurrences.setdefault(line, set()).add(rel)
    return [
        {"line": line[:160], "files": sorted(files)}
        for line, files in sorted(occurrences.items())
        if len(files) > 1
    ]


def _package_versions() -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for dist in importlib.metadata.distributions():
        if (dist.metadata.get("Name") or "").lower() != "nexus-bootstrap":
            continue
        found.append({"version": dist.version, "path": str(dist._path)})
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in found:
        key = (item["version"], item["path"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def diagnose(project_dir: Path, *, deep: bool, consumer: str) -> dict[str, Any]:
    pd = project_dir.resolve()
    try:
        normalized_consumer = consumer.strip().lower()
        if normalized_consumer != "all" and normalized_consumer not in DOCTOR_CONSUMERS:
            raise ValueError(
                f"Unknown consumer '{normalized_consumer}'. Choose from: all, "
                f"{', '.join(DOCTOR_CONSUMERS)}"
            )
        requested = (
            ("vscode",)
            if normalized_consumer == "vscode"
            else parse_consumers(consumer)
        )
    except ValueError as exc:
        return {
            "status": "fail",
            "message": str(exc),
            "items": [{"check": "consumer", "status": "fail", "detail": str(exc)}],
        }

    items: list[dict[str, Any]] = []
    failures = 0
    warnings = 0
    drift_count = 0
    missing_count = 0

    def add(check: str, status: str, **extra: Any) -> None:
        nonlocal failures, warnings
        items.append({"check": check, "status": status, **extra})
        failures += status == "fail"
        warnings += status == "warn"

    versions = _package_versions()
    add(
        "package-provenance",
        "warn" if len(versions) != 1 else "ok",
        detail=f"cli={__version__}; executable={sys.executable}",
        distributions=versions,
    )

    profile = load(pd)
    if profile is None:
        add("profile-present", "fail", detail="missing or invalid .nexus/profile.json")
        return {
            "status": "fail",
            "message": "profile missing or invalid",
            "items": items,
            "details": {
                "failures": failures,
                "warnings": warnings,
                "drift_count": drift_count,
                "missing_count": missing_count,
            },
        }
    add("profile-present", "ok")
    add(
        "version-match",
        "ok" if profile.nexus_version == NEXUS_VERSION else "warn",
        detail=f"profile={profile.nexus_version}; cli={NEXUS_VERSION}",
    )

    manifest = load_manifest(pd)
    if manifest is None:
        add("install-manifest", "fail", detail="missing or invalid .nexus/install-manifest.json")
        installed_consumers = requested
    else:
        manifest_consumers = tuple(manifest.get("consumers", ()))
        installed_consumers = requested if consumer != "all" else (
            manifest_consumers or ALL_CONSUMERS
        )
        manifest_ok = (
            manifest.get("schema_version") == 1
            and isinstance(manifest.get("files"), dict)
            and isinstance(manifest.get("consumers"), list)
            and manifest.get("tier") in {"fast", "team", "enterprise"}
        )
        add(
            "install-manifest",
            "ok" if manifest_ok else "fail",
            detail=(
                f"schema={manifest.get('schema_version')}; "
                f"version={manifest.get('nexus_version')}"
            ),
        )
        add(
            "manifest-version",
            "ok" if manifest.get("nexus_version") == NEXUS_VERSION else "warn",
            detail=f"manifest={manifest.get('nexus_version')}; cli={NEXUS_VERSION}",
        )
        if consumer != "all" and any(
            name != "vscode" and name not in manifest_consumers for name in requested
        ):
            add(
                "consumer-selected",
                "fail",
                detail=f"requested={','.join(requested)}; installed={','.join(manifest_consumers)}",
            )

        manifest_drift: list[str] = []
        manifest_missing: list[str] = []
        for rel, metadata in manifest.get("files", {}).items() if manifest_ok else ():
            path = pd / rel
            expected = metadata.get("sha256") if isinstance(metadata, dict) else None
            if not path.is_file():
                manifest_missing.append(rel)
            elif not expected or sha256_file(path) != expected:
                manifest_drift.append(rel)
        add(
            "manifest-integrity",
            "fail" if manifest_missing or manifest_drift else "ok",
            detail=f"{len(manifest_missing)} missing; {len(manifest_drift)} modified",
            missing=manifest_missing[:25],
            modified=manifest_drift[:25],
        )

    expected_hash = hash_profile(profile)
    planned = run_all(profile, pd, targets=_targets(installed_consumers), dry_run=True)
    adapter_paths: list[Path] = []
    for generated, _ in planned:
        adapter_paths.append(generated.path)
        state, detail = _check_file(generated.path, expected_hash)
        drift_count += state in {"drift", "unstamped"}
        missing_count += state == "missing"
        add(
            f"adapter:{generated.target}:{generated.block_id}",
            "ok" if state == "ok" else "fail",
            path=str(generated.path.relative_to(pd)),
            detail=detail,
        )
        if generated.path.exists() and generated.path.stat().st_size > 1024 and generated.target != "agents_md":
            add(
                f"adapter-size:{generated.target}:{generated.block_id}",
                "warn",
                path=str(generated.path.relative_to(pd)),
                detail=f"{generated.path.stat().st_size} bytes; target is <=1024",
            )

    canonical = pd / ".agents" / "skills"
    skill_issues = validate_skill_tree(canonical)
    expected_bundle = bundled_skill_files()
    missing_bundle_files = [
        rel for rel in sorted(expected_bundle)
        if not (canonical / rel).is_file()
    ]
    if missing_bundle_files:
        skill_issues["<bundle>"] = [
            f"missing packaged file: {rel}" for rel in missing_bundle_files[:25]
        ]
    if skill_issues:
        add("canonical-skills", "fail", detail="invalid or missing canonical skills", issues=skill_issues)
    else:
        skill_count = len(list(canonical.glob("*/SKILL.md")))
        add("canonical-skills", "ok", detail=f"{skill_count} valid skill(s)")

    if "claude" in installed_consumers:
        mirror = pd / ".claude" / "skills"
        mismatches: list[str] = []
        if canonical.is_dir():
            for source in canonical.rglob("*"):
                if not source.is_file():
                    continue
                rel = source.relative_to(canonical)
                target = mirror / rel
                if not target.is_file() or sha256_file(target) != sha256_file(source):
                    mismatches.append(rel.as_posix())
        add(
            "claude-skill-projection",
            "fail" if mismatches else "ok",
            detail=(f"{len(mismatches)} missing or divergent file(s)" if mismatches else "byte-equivalent"),
            mismatches=mismatches[:25],
        )
        claude_md = pd / "CLAUDE.md"
        has_import = claude_md.is_file() and "@AGENTS.md" in claude_md.read_text(encoding="utf-8", errors="replace")
        add("claude-agents-import", "ok" if has_import else "fail", path="CLAUDE.md")

    if "devin-review" in installed_consumers:
        duplicates = _review_duplicates(pd)
        add(
            "devin-review-duplication",
            "fail" if duplicates else "ok",
            detail=f"{len(duplicates)} duplicated shared instruction line(s)",
            duplicates=duplicates[:25],
        )

    relevant_ignores: list[str] = []
    if "cursor" in installed_consumers:
        relevant_ignores.append(".cursorignore")
    for rel in relevant_ignores:
        add(f"ignore:{rel}", "ok" if (pd / rel).is_file() else "warn", detail="relevant context ignore")

    legacy_artifacts = [
        rel for rel in (".cursorrules", ".windsurf/rules", ".windsurf/skills", ".windsurf/workflows")
        if (pd / rel).exists()
    ]
    add(
        "legacy-artifacts",
        "warn" if legacy_artifacts else "ok",
        detail=(", ".join(legacy_artifacts) if legacy_artifacts else "none"),
    )

    if deep:
        fresh = from_detection(pd, tier=profile.tier, project_name=profile.project_name)
        diffs = []
        for field_name in (
            "languages", "frameworks", "package_managers", "test_runner", "ci", "deployment",
        ):
            old = getattr(profile, field_name)
            new = getattr(fresh, field_name)
            if old != new:
                diffs.append({"field": field_name, "stored": old, "detected": new})
        add("stack-drift", "warn" if diffs else "ok", diffs=diffs)

    try:
        from nexus.cli.tools.journal import _diagnose_journal

        journal = _diagnose_journal(pd)
        add(
            "journal-health",
            "ok" if journal.get("status") == "ok" else "warn",
            detail=str(journal.get("status", "unknown")),
        )
    except Exception as exc:  # pragma: no cover - defensive
        add("journal-health", "warn", detail=f"unavailable: {type(exc).__name__}")

    status = "fail" if failures else ("warn" if warnings else "pass")
    message = "all clean" if status == "pass" else f"{failures} failure(s), {warnings} warning(s)"
    return {
        "status": status,
        "message": message,
        "items": items,
        "details": {
            "profile_hash": expected_hash,
            "consumers": list(installed_consumers),
            "failures": failures,
            "warnings": warnings,
            "drift_count": drift_count,
            "missing_count": missing_count,
        },
    }


def run_doctor(
    *,
    output_format: str,
    project_dir: str,
    deep: bool,
    consumer: str = "all",
) -> dict[str, Any]:
    result_data = diagnose(Path(project_dir), deep=deep, consumer=consumer)
    status = Status(result_data["status"])
    result = make_result("doctor", status, message=result_data["message"])
    result["items"] = result_data["items"]
    result["details"] = result_data.get("details", {})
    fmt = OutputFormat(output_format)
    if fmt == OutputFormat.HUMAN:
        click.echo(f"\n  Doctor -- {result_data['message']}")
        for item in result_data["items"]:
            mark = {"ok": "+", "warn": "!", "fail": "x"}.get(item["status"], "-")
            line = f"    [{mark}] {item['check']}"
            if item.get("path"):
                line += f"  {item['path']}"
            if item.get("detail"):
                line += f" -- {item['detail']}"
            click.echo(line)
        click.echo("")
    else:
        emit(result, fmt)
    return result
