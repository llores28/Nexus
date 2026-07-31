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
    lines += [f"# Claude adapter — {profile.project_name}", ""]
    lines.append("@AGENTS.md")
    lines.append("")
    lines.append("Project skills are discovered from `.claude/skills/*/SKILL.md`.")
    lines.append("")

    rules = [r for r in select_rules(profile, target="claude") if r.targets is not None]
    if rules:
        lines.append("## Claude-specific deltas")
        lines.append("")
        for r in rules:
            scope = f" (scope: `{', '.join(r.applies_to)}`)" if r.applies_to else ""
            sev = "" if r.severity == "must" else f" [{r.severity}]"
            lines.append(f"- {r.text}{scope}{sev}")
        lines.append("")

    lines.append("Use `nexus journal handoff` for compact cross-agent state.")

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
