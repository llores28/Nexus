"""
Nexus Health Check Tool — validates Nexus components work cohesively.

Subcommands:
  check      — full health check (all tiers)
  components — Tier 1: component inventory and integrity
  security   — Tier 2: security posture validation
  usage      — Tier 3: CLI audit trail analysis
  report     — full report with recommendations
"""

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from nexus.cli.utils import (
    OutputFormat,
    Status,
    Severity,
    emit,
    make_result,
    truncate_output,
    find_project_root,
)
from nexus.cli.security import (
    scan_text_for_secrets, validate_path,
    is_template_file, gitignored_files,
)
from nexus.cli.installation import bundled_skill_files


# --- Expected Nexus Components ---

EXPECTED_SKILLS = sorted({
    rel.split("/", 1)[0]
    for rel in bundled_skill_files()
    if rel.endswith("/SKILL.md")
})

EXPECTED_CROSS_IDE = [
    "AGENTS.md",
    "CLAUDE.md",
    ".cursor/rules/00-core.mdc",
    ".github/copilot-instructions.md",
]

# `.nexus/profile.json` is the committed single source of truth.
PROFILE_REL = ".nexus/profile.json"

RULE_MAX_SIZE_BYTES = 12_000  # 12KB limit per rule file

GITIGNORE_REQUIRED_PATTERNS = [
    ".env",
    "__pycache__",
    "node_modules",
    ".venv",
    "*.key",
    "*.pem",
]

CODEIUMIGNORE_EXPECTED = [
    "wizard-reference.md",
]


# --- Tier 1: Component Inventory & Integrity ---

def _check_rules(project_dir: Path) -> dict[str, Any]:
    """Validate canonical AGENTS.md and report legacy inputs separately."""
    agents = project_dir / "AGENTS.md"
    issues: list[dict] = []
    if not agents.is_file():
        issues.append({"severity": "high", "message": "Canonical AGENTS.md is missing"})
    elif agents.stat().st_size > 32_768:
        issues.append({"severity": "medium", "message": "AGENTS.md exceeds the 32 KiB bounded instruction target"})
    legacy = project_dir / ".windsurf" / "rules"
    if legacy.is_dir():
        issues.append({"severity": "info", "message": "Legacy .windsurf/rules inputs are present for migration review"})
    status = "fail" if any(i["severity"] == "high" for i in issues) else (
        "warn" if any(i["severity"] != "info" for i in issues) else "pass"
    )
    return {
        "status": status,
        "found": int(agents.is_file()),
        "expected": 1,
        "all_rules": ["AGENTS.md"] if agents.is_file() else [],
        "issues": issues,
    }


def _check_skills(project_dir: Path) -> dict[str, Any]:
    """Validate skills exist and have valid SKILL.md files."""
    skills_dir = project_dir / ".agents" / "skills"
    issues: list[dict] = []
    found_skills: list[str] = []

    if not skills_dir.is_dir():
        return {
            "status": "warn",
            "found": 0,
            "expected": 0,
            "issues": [{"severity": "medium", "message": ".agents/skills/ not present"}],
        }

    # Discover all skill folders
    for skill_dir in sorted(skills_dir.iterdir()):
        if skill_dir.is_dir() and not skill_dir.name.startswith("."):
            if not any(skill_dir.iterdir()):
                continue
            found_skills.append(skill_dir.name)

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                issues.append({
                    "severity": "high",
                    "message": f"Skill {skill_dir.name}/ missing SKILL.md",
                })
            else:
                # Validate SKILL.md has frontmatter with name and description
                try:
                    content = skill_md.read_text(encoding="utf-8", errors="replace")
                    if not content.startswith("---"):
                        issues.append({
                            "severity": "medium",
                            "message": f"Skill {skill_dir.name}/SKILL.md missing YAML frontmatter",
                        })
                    else:
                        frontmatter_end = content.find("---", 3)
                        if frontmatter_end > 0:
                            fm = content[3:frontmatter_end].lower()
                            if "name" not in fm:
                                issues.append({
                                    "severity": "medium",
                                    "message": f"Skill {skill_dir.name}/SKILL.md missing 'name' in frontmatter",
                                })
                            if "description" not in fm:
                                issues.append({
                                    "severity": "medium",
                                    "message": f"Skill {skill_dir.name}/SKILL.md missing 'description' in frontmatter",
                                })
                except OSError:
                    issues.append({
                        "severity": "medium",
                        "message": f"Cannot read skill: {skill_dir.name}/SKILL.md",
                    })

    # Check expected skills
    for expected in EXPECTED_SKILLS:
        if expected not in found_skills:
            issues.append({
                "severity": "medium",
                "message": f"Missing expected skill: {expected}",
            })

    high_issues = [i for i in issues if i["severity"] == "high"]
    status = "fail" if high_issues else ("warn" if issues else "pass")

    return {
        "status": status,
        "found": len(found_skills),
        "expected": len(EXPECTED_SKILLS),
        "all_skills": found_skills,
        "issues": issues,
    }


def _check_workflows(project_dir: Path) -> dict[str, Any]:
    """Workflows are Agent Skills; do not count them as a duplicate component."""
    return {
        "status": "pass",
        "found": 0,
        "expected": 0,
        "all_workflows": [],
        "issues": [{"severity": "info", "message": "Reusable workflows are validated as Agent Skills"}],
    }


def _check_cross_ide(project_dir: Path) -> dict[str, Any]:
    """Validate provider adapters by managed profile stamp."""
    issues: list[dict] = []
    found_files: list[str] = []
    stamp_hashes: dict[str, str] = {}

    for rel_path in EXPECTED_CROSS_IDE:
        full_path = project_dir / rel_path
        if full_path.exists():
            found_files.append(rel_path)

            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
                match = re.search(r"nexus: profile=([a-f0-9]{12})", content)
                if match:
                    stamp_hashes[rel_path] = match.group(1)
            except OSError:
                pass
        else:
            issues.append({
                "severity": "medium",
                "message": f"Missing cross-IDE file: {rel_path}",
            })

    if len(set(stamp_hashes.values())) > 1:
        issues.append({
            "severity": "medium",
            "message": "Provider adapters have inconsistent profile stamps",
            "details": stamp_hashes,
        })

    status = "fail" if not found_files else ("warn" if issues else "pass")

    return {
        "status": status,
        "found": len(found_files),
        "expected": len(EXPECTED_CROSS_IDE),
        "files": found_files,
        "issues": issues,
    }


def _check_bootstrap_templates(project_dir: Path) -> dict[str, Any]:
    """Validate nexus templates reference required files."""
    templates_dir = project_dir / "nexus"
    issues: list[dict] = []
    checked = 0

    template_patterns = ["*Bootstrap*.md", "*ws-Bootstrap*.md"]
    # Exclude non-output templates (intake forms, PRD templates, README)
    exclude_names = {"README.md", "Bootstrap-Project-Intake.md", "PRD-Template.md"}
    templates: list[Path] = []
    for pattern in template_patterns:
        templates.extend(templates_dir.glob(pattern))

    for tmpl in templates:
        if tmpl.name in exclude_names:
            continue
        checked += 1
        try:
            content = tmpl.read_text(encoding="utf-8", errors="replace")
            if "AGENTS.md" not in content or ".agents/skills" not in content:
                issues.append({
                    "severity": "low",
                    "message": f"Template {tmpl.name} is missing canonical AGENTS.md or Agent Skills guidance",
                })
            if ".cursorrules" in content or ".agents/workflows" in content or ".agents/rules" in content:
                issues.append({
                    "severity": "medium",
                    "message": f"Template {tmpl.name} references an obsolete instruction surface",
                })
        except OSError:
            issues.append({
                "severity": "medium",
                "message": f"Cannot read template: {tmpl.name}",
            })

    status = "warn" if issues else "pass"
    return {
        "status": status,
        "templates_checked": checked,
        "issues": issues,
    }


def _check_profile(project_dir: Path) -> dict[str, Any]:
    """Validate `.nexus/profile.json` is present and parseable."""
    path = project_dir / PROFILE_REL
    if not path.exists():
        return {
            "status": "warn",
            "issues": [{
                "severity": "medium",
                "message": (
                    f"{PROFILE_REL} not found -- run `nexus profile detect` to create it. "
                    "(Old projects can run `nexus init --upgrade` to migrate.)"
                ),
            }],
        }
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {
            "status": "fail",
            "issues": [{
                "severity": "high",
                "message": f"{PROFILE_REL} is unreadable or malformed: {type(e).__name__}",
            }],
        }
    return {"status": "pass", "issues": []}


def run_components(project_dir: Path) -> dict[str, Any]:
    """Tier 1: Full component inventory and integrity check."""
    profile = _check_profile(project_dir)
    rules = _check_rules(project_dir)
    skills = _check_skills(project_dir)
    workflows = _check_workflows(project_dir)
    cross_ide = _check_cross_ide(project_dir)
    templates = _check_bootstrap_templates(project_dir)

    all_issues = (
        profile["issues"] + rules["issues"] + skills["issues"] + workflows["issues"]
        + cross_ide["issues"] + templates["issues"]
    )
    high_count = sum(1 for i in all_issues if i["severity"] == "high")
    med_count = sum(1 for i in all_issues if i["severity"] == "medium")

    if high_count > 0:
        status = "fail"
    elif med_count > 0:
        status = "warn"
    else:
        status = "pass"

    return {
        "status": status,
        "profile": profile,
        "rules": rules,
        "skills": skills,
        "workflows": workflows,
        "cross_ide": cross_ide,
        "templates": templates,
        "total_issues": len(all_issues),
    }


# --- Tier 2: Security & Configuration ---

def _check_gitignore(project_dir: Path) -> dict[str, Any]:
    """Validate .gitignore covers sensitive patterns."""
    gitignore = project_dir / ".gitignore"
    issues: list[dict] = []

    if not gitignore.exists():
        return {
            "status": "fail",
            "issues": [{"severity": "high", "message": ".gitignore not found"}],
        }

    try:
        content = gitignore.read_text(encoding="utf-8", errors="replace")
        for pattern in GITIGNORE_REQUIRED_PATTERNS:
            if pattern not in content:
                issues.append({
                    "severity": "medium",
                    "message": f".gitignore missing pattern: {pattern}",
                })
    except OSError:
        return {
            "status": "fail",
            "issues": [{"severity": "high", "message": "Cannot read .gitignore"}],
        }

    status = "fail" if any(i["severity"] == "high" for i in issues) else ("warn" if issues else "pass")
    return {
        "status": status,
        "patterns_checked": len(GITIGNORE_REQUIRED_PATTERNS),
        "issues": issues,
    }


def _check_codeiumignore(project_dir: Path) -> dict[str, Any]:
    """Treat Codeium/Windsurf ignore support as legacy compatibility only."""
    codeiumignore = project_dir / ".codeiumignore"
    issues: list[dict] = []

    if not codeiumignore.exists():
        return {
            "status": "pass",
            "issues": [{"severity": "info", "message": "No legacy .codeiumignore present"}],
        }

    try:
        content = codeiumignore.read_text(encoding="utf-8", errors="replace")
        for expected in CODEIUMIGNORE_EXPECTED:
            if expected not in content:
                issues.append({
                    "severity": "medium",
                    "message": f".codeiumignore missing exclusion: {expected}",
                })
    except OSError:
        return {
            "status": "fail",
            "issues": [{"severity": "medium", "message": "Cannot read .codeiumignore"}],
        }

    status = "warn" if issues else "pass"
    return {
        "status": status,
        "exclusions": len(CODEIUMIGNORE_EXPECTED),
        "issues": issues,
    }


def _check_secrets(project_dir: Path) -> dict[str, Any]:
    """Quick secrets scan on config files. Skips gitignored (local-only) and
    template (.example/.template) files since neither can leak via commit."""
    all_findings: list[dict] = []
    files_scanned = 0
    files_skipped: list[dict] = []

    config_patterns = [
        ".env", ".env.*", "*.config.js", "*.config.ts",
        "docker-compose*.yml", "docker-compose*.yaml",
    ]

    globbed: list[Path] = []
    for pattern in config_patterns:
        for fpath in project_dir.glob(pattern):
            if fpath.is_file() and fpath not in globbed:
                globbed.append(fpath)

    ignored = gitignored_files(project_dir, globbed)
    scan_targets: list[Path] = []
    for fpath in globbed:
        rel = fpath.relative_to(project_dir).as_posix()
        if rel in ignored:
            files_skipped.append({"file": rel, "reason": "gitignored"})
            continue
        if is_template_file(fpath):
            files_skipped.append({"file": rel, "reason": "template"})
            continue
        scan_targets.append(fpath)

    for fpath in scan_targets[:30]:
        files_scanned += 1
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
            findings = scan_text_for_secrets(content)
            for f in findings:
                f["file"] = str(fpath.relative_to(project_dir))
                all_findings.append(f)
        except OSError:
            continue

    status = "fail" if all_findings else ("pass" if files_scanned else "info")
    return {
        "status": status,
        "files_scanned": files_scanned,
        "files_skipped": files_skipped,
        "secrets_found": len(all_findings),
        "findings": all_findings[:20],
        "coverage": "scanned" if files_scanned else "none",
    }


def _check_dependencies(project_dir: Path) -> dict[str, Any]:
    """Check that CLI toolkit dependencies are importable."""
    issues: list[dict] = []
    checked = 0

    required_packages = {
        "click": "click",
        "rich": "rich",
        "yaml": "pyyaml",
        "httpx": "httpx",
        "bs4": "beautifulsoup4",
    }

    for import_name, pkg_name in required_packages.items():
        checked += 1
        try:
            __import__(import_name)
        except ImportError:
            issues.append({
                "severity": "high",
                "message": f"Cannot import '{import_name}' (pip install {pkg_name})",
            })

    status = "fail" if issues else "pass"
    return {
        "status": status,
        "packages_checked": checked,
        "issues": issues,
    }


def run_security(project_dir: Path) -> dict[str, Any]:
    """Tier 2: Security and configuration health.

    Status hierarchy (most → least severe): fail > warn > pass.
      - fail: any high-severity issue, OR any secret found.
      - warn: any other issue.
      - pass: clean.

    Note: secret findings have shape {file, line, pattern, preview} and lack
    a `severity` field, so they were previously invisible to the high-count
    sum and the score reported "warn" while the dashboard penalty already
    docked points. Now `secrets_found > 0` directly forces fail.
    """
    gitignore = _check_gitignore(project_dir)
    codeiumignore = _check_codeiumignore(project_dir)
    secrets = _check_secrets(project_dir)
    deps = _check_dependencies(project_dir)

    issue_lists = [gitignore["issues"], codeiumignore["issues"], deps["issues"]]
    all_issues = [i for lst in issue_lists for i in lst if i.get("severity") != "info"]
    high_count = sum(1 for i in all_issues if i.get("severity") == "high")
    secrets_found = secrets.get("secrets_found", 0)

    if high_count > 0 or secrets_found > 0:
        status = "fail"
    elif all_issues or secrets.get("files_skipped"):
        # any non-high issue, or skipped files (informational) → warn
        status = "warn" if all_issues else "pass"
    else:
        status = "pass"

    return {
        "status": status,
        "gitignore": gitignore,
        "codeiumignore": codeiumignore,
        "secrets": secrets,
        "dependencies": deps,
    }


# --- Tier 3: Usage Analytics ---

def run_usage(project_dir: Path) -> dict[str, Any]:
    """Tier 3: Analyze CLI audit trail for usage patterns."""
    audit_file = project_dir / ".cache" / "bs-cli" / "audit.jsonl"

    if not audit_file.exists():
        return {
            "status": "info",
            "message": "No audit trail found — CLI tools haven't been used yet",
            "total_invocations": 0,
        }

    entries: list[dict] = []
    try:
        with open(audit_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return {
            "status": "fail",
            "message": "Cannot read audit trail",
        }

    if not entries:
        return {
            "status": "info",
            "message": "Audit trail is empty",
            "total_invocations": 0,
        }

    # Analyze usage
    total = len(entries)
    errors = sum(1 for e in entries if e.get("exit_code", 0) != 0)
    error_rate = errors / total if total > 0 else 0.0

    # Tool usage counts
    tool_counts: dict[str, int] = {}
    for e in entries:
        tool = e.get("tool", "unknown")
        tool_counts[tool] = tool_counts.get(tool, 0) + 1

    most_used = max(tool_counts, key=tool_counts.get) if tool_counts else "none"
    least_used = min(tool_counts, key=tool_counts.get) if tool_counts else "none"

    # Duration analysis
    durations = [e.get("duration_ms", 0) for e in entries if e.get("duration_ms")]
    avg_duration = sum(durations) / len(durations) if durations else 0

    # Last activity
    last_entry = entries[-1] if entries else {}
    last_activity = last_entry.get("timestamp", "unknown")

    # Recent errors (last 10 failures)
    recent_errors = [
        {
            "tool": e.get("tool"),
            "timestamp": e.get("timestamp"),
            "exit_code": e.get("exit_code"),
        }
        for e in reversed(entries)
        if e.get("exit_code", 0) != 0
    ][:10]

    status = "fail" if error_rate > 0.25 else ("warn" if error_rate > 0.1 else "pass")

    return {
        "status": status,
        "total_invocations": total,
        "error_count": errors,
        "error_rate": round(error_rate, 3),
        "most_used_tool": most_used,
        "least_used_tool": least_used,
        "tool_counts": dict(sorted(tool_counts.items(), key=lambda x: -x[1])),
        "avg_duration_ms": round(avg_duration),
        "last_activity": last_activity,
        "recent_errors": recent_errors,
    }


# --- Tier 4: Recommendations ---

def _generate_recommendations(
    components: dict, security: dict, usage: dict
) -> list[dict]:
    """Generate actionable recommendations from health check results."""
    recs: list[dict] = []

    # Component recommendations
    if components.get("rules", {}).get("status") == "fail":
        recs.append({
            "severity": "high",
            "category": "components",
            "message": "Missing canonical project instructions",
            "action": "Run nexus generate to refresh AGENTS.md",
        })

    for issue in components.get("rules", {}).get("issues", []):
        if "exceeds 12KB" in issue.get("message", ""):
            recs.append({
                "severity": "medium",
                "category": "performance",
                "message": issue["message"],
                "action": "Split large rules into multiple files or move content to model_decision trigger",
            })

    if components.get("skills", {}).get("status") in ("fail", "warn"):
        missing = [
            i["message"] for i in components.get("skills", {}).get("issues", [])
            if "Missing" in i.get("message", "")
        ]
        if missing:
            recs.append({
                "severity": "medium",
                "category": "components",
                "message": f"Missing skills: {', '.join(missing)}",
                "action": "Run /migrate-toolkit to install missing skills",
            })

    if components.get("cross_ide", {}).get("found", 0) < len(EXPECTED_CROSS_IDE):
        recs.append({
            "severity": "medium",
            "category": "compatibility",
            "message": "Missing cross-IDE configuration files",
            "action": "Create missing files from Nexus templates for full IDE compatibility",
        })

    # Security recommendations
    if security.get("gitignore", {}).get("status") != "pass":
        recs.append({
            "severity": "high",
            "category": "security",
            "message": ".gitignore missing critical exclusion patterns",
            "action": "Add missing patterns to .gitignore to prevent accidental secret commits",
        })

    if security.get("secrets", {}).get("secrets_found", 0) > 0:
        recs.append({
            "severity": "critical",
            "category": "security",
            "message": f"Potential secrets found in {security['secrets']['secrets_found']} location(s)",
            "action": "Review and remove leaked credentials immediately",
        })

    if security.get("dependencies", {}).get("status") != "pass":
        recs.append({
            "severity": "high",
            "category": "dependencies",
            "message": "Missing CLI toolkit dependencies",
            "action": "Run: pip install -r nexus/cli/requirements.txt",
        })

    # Usage recommendations
    if usage.get("error_rate", 0) > 0.1:
        recs.append({
            "severity": "medium",
            "category": "reliability",
            "message": f"High CLI error rate: {usage['error_rate']:.1%} — on Windows this is often a cp1252 encoding bug (fixed in bs_cli.py startup)",
            "action": (
                "If errors persist after upgrade, investigate with: "
                "python nexus/cli/bs_cli.py debug logs .cache/bs-cli/  "
                "Workaround for old installs: set PYTHONIOENCODING=utf-8"
            ),
        })

    if usage.get("total_invocations", 0) == 0:
        recs.append({
            "severity": "low",
            "category": "adoption",
            "message": "No CLI tool usage detected",
            "action": "Try: python bs_cli.py smoketest --format human",
        })

    # Sort by severity
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    recs.sort(key=lambda r: severity_order.get(r["severity"], 99))

    return recs


# --- Health Score Calculator ---

def _calculate_score(components: dict, security: dict, usage: dict) -> int:
    """Calculate weighted health score (0-100)."""
    score = 100
    weights = {"high": 10, "medium": 5, "low": 2, "critical": 20}

    # Component issues. ``info`` items don't dock the score (they're context,
    # not problems) — used for legacy migration notes.
    for section in ["profile", "rules", "skills", "workflows", "cross_ide", "templates"]:
        section_data = components.get(section, {})
        for issue in section_data.get("issues", []):
            sev = issue.get("severity", "low")
            if sev == "info":
                continue
            score -= weights.get(sev, 2)

    # Security issues
    for section in ["gitignore", "codeiumignore", "dependencies"]:
        section_data = security.get(section, {})
        for issue in section_data.get("issues", []):
            penalty = weights.get(issue.get("severity", "low"), 2)
            score -= penalty

    # Secrets are critical
    secrets_found = security.get("secrets", {}).get("secrets_found", 0)
    score -= secrets_found * 20

    # Usage error rate penalty
    error_rate = usage.get("error_rate", 0)
    if error_rate > 0.25:
        score -= 15
    elif error_rate > 0.1:
        score -= 8

    return max(0, min(100, score))


# --- Main Runners ---

def run_health_check(project_dir: Path) -> dict[str, Any]:
    """Full health check across all tiers."""
    start = time.time()

    components = run_components(project_dir)
    security = run_security(project_dir)
    usage = run_usage(project_dir)
    recommendations = _generate_recommendations(components, security, usage)
    score = _calculate_score(components, security, usage)

    duration_ms = int((time.time() - start) * 1000)

    # Count totals
    total_checks = 0
    passed = 0
    warnings = 0
    failed = 0
    for section in [components, security]:
        for key, val in section.items():
            if isinstance(val, dict) and "status" in val:
                total_checks += 1
                if val["status"] == "pass":
                    passed += 1
                elif val["status"] == "warn":
                    warnings += 1
                elif val["status"] == "fail":
                    failed += 1

    # Overall status
    if failed > 0:
        overall = "fail"
    elif warnings > 0:
        overall = "warn"
    else:
        overall = "pass"

    return {
        "status": overall,
        "score": score,
        "summary": {
            "total_checks": total_checks,
            "passed": passed,
            "warnings": warnings,
            "failed": failed,
            "score": score,
        },
        "components": components,
        "security": security,
        "usage": usage,
        "recommendations": recommendations,
        "duration_ms": duration_ms,
    }


def run_health_report(project_dir: Path) -> dict[str, Any]:
    """Full report with all details and recommendations."""
    result = run_health_check(project_dir)
    result["report_type"] = "full"
    return result


# --- CLI Entry Point ---

def run_health(
    subcommand: str,
    output_format: str = "json",
    project_dir: str = ".",
) -> None:
    """Route to the appropriate health subcommand."""
    fmt = OutputFormat(output_format)
    # Auto-detect the project root from canonical repository markers.
    raw_path = Path(project_dir).resolve()
    proj_path = find_project_root(raw_path)

    if subcommand == "check":
        data = run_health_check(proj_path)
        status = Status(data["status"])
        msg = f"Health score: {data['score']}/100 — {data['summary']['passed']} passed, {data['summary']['warnings']} warnings, {data['summary']['failed']} failed"
        result = make_result("health.check", status, msg, duration_ms=data.get("duration_ms"))
        result["health"] = data

    elif subcommand == "components":
        data = run_components(proj_path)
        status = Status(data["status"])
        msg = f"Components: {data['total_issues']} issue(s) found"
        result = make_result("health.components", status, msg)
        result["components"] = data

    elif subcommand == "security":
        data = run_security(proj_path)
        status = Status(data["status"])
        result = make_result("health.security", status)
        result["security"] = data

    elif subcommand == "usage":
        data = run_usage(proj_path)
        status = Status(data.get("status", "info"))
        msg = f"{data.get('total_invocations', 0)} total invocations, {data.get('error_rate', 0):.1%} error rate"
        result = make_result("health.usage", status, msg)
        result["usage"] = data

    elif subcommand == "report":
        data = run_health_report(proj_path)
        status = Status(data["status"])
        msg = f"Nexus Health Report — Score: {data['score']}/100 — {len(data['recommendations'])} recommendation(s)"
        result = make_result("health.report", status, msg, duration_ms=data.get("duration_ms"))
        result["report"] = data

    else:
        result = make_result("health", Status.FAIL, f"Unknown subcommand: {subcommand}")

    emit(result, fmt)
