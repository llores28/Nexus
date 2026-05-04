"""CLAUDE.md generator -- Claude Code's per-project instructions.

Uses upsert mode so any user-authored sections outside the managed block
are preserved across regenerations.
"""

from pathlib import Path

from nexus.cli.profile import Profile, hash_profile, select_rules
from nexus.cli.generators import GeneratedFile, stamp


def _build_body(profile: Profile) -> str:
    h = hash_profile(profile)
    lines: list[str] = [stamp(h, "claude"), ""]

    lines.append(f"# Claude Code instructions -- {profile.project_name}")
    lines.append("")

    lines.append("## Stack")
    if profile.languages:
        lines.append(f"- Languages: {', '.join(profile.languages)}")
    if profile.frameworks:
        lines.append(f"- Frameworks: {', '.join(profile.frameworks)}")
    if profile.package_managers:
        lines.append(f"- Package managers: {', '.join(profile.package_managers)}")
    if profile.test_runner:
        lines.append(f"- Test runner: `{profile.test_runner}`")
    if profile.ci:
        lines.append(f"- CI: {profile.ci}")
    if profile.deployment:
        lines.append(f"- Deployment: {profile.deployment}")
    lines.append(f"- Tier: {profile.tier}")
    lines.append("")

    rules = select_rules(profile, target="claude")
    if rules:
        lines.append("## Constraints")
        lines.append("")
        for r in rules:
            scope = f" (scope: `{', '.join(r.applies_to)}`)" if r.applies_to else ""
            sev = "" if r.severity == "must" else f" [{r.severity}]"
            lines.append(f"- {r.text}{scope}{sev}")
        lines.append("")

    sub_repos = profile.extras.get("sub_repos", []) if isinstance(profile.extras, dict) else []
    if sub_repos:
        lines.append("## Sub-repositories")
        lines.append("")
        lines.append(
            "Nested standalone git repos. Commits to each auto-log to the parent "
            "journal via post-commit hooks (run `nexus journal setup-hooks` if missing):"
        )
        lines.append("")
        for sub in sub_repos:
            path = sub.get("path", "?")
            bits: list[str] = []
            if sub.get("frameworks"):
                bits.append("/".join(sub["frameworks"]))
            if sub.get("languages"):
                bits.append("+".join(sub["languages"]))
            if sub.get("package_managers"):
                bits.append("(" + ", ".join(sub["package_managers"]) + ")")
            stack_str = " — " + " ".join(bits) if bits else ""
            lines.append(f"- `{path}`{stack_str}")
        lines.append("")

    lines.append("## Project state")
    lines.append("")
    lines.append("- Read `.nexus/state-summary.md` at session start for current tasks and recent commits.")
    lines.append('- Track tasks via `nexus journal next add "<task>"`; blockers via `nexus journal blocker add "<text>"`.')
    lines.append('- Architectural decisions go in `docs/decisions/` via `nexus journal decision add "<title>"`.')
    lines.append("- Run `nexus doctor` to check rule drift and journal health.")

    return "\n".join(lines)


def generate(profile: Profile, project_root: Path) -> list[GeneratedFile]:
    return [
        GeneratedFile(
            path=project_root / "CLAUDE.md",
            content=_build_body(profile),
            mode="upsert",
            target="claude",
            block_id="claude-md",
        )
    ]
