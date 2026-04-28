"""AGENTS.md generator -- Linux Foundation cross-tool spec.

Emits a managed block at the bottom of ``AGENTS.md``. The block uses a
distinct marker (``nexus:agents-md``) from the journal-state block
(``nexus:state``), so both can coexist in the same file.
"""

from pathlib import Path

from nexus.cli.profile import Profile, hash_profile, select_rules
from nexus.cli.generators import GeneratedFile, stamp


def _build_body(profile: Profile) -> str:
    h = hash_profile(profile)
    lines: list[str] = [stamp(h, "agents_md"), ""]

    lines.append(f"## Project: {profile.project_name}")
    lines.append("")
    lines.append(f"- Tier: **{profile.tier}**")
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
    lines.append("")

    rules = select_rules(profile, target="agents_md")
    if rules:
        lines.append("## Conventions")
        lines.append("")
        for r in rules:
            scope = f" _(scope: {', '.join(r.applies_to)})_" if r.applies_to else ""
            sev = "" if r.severity == "must" else f" _[{r.severity}]_"
            lines.append(f"- {r.text}{scope}{sev}")
        lines.append("")

    lines.append("## Project state")
    lines.append("")
    lines.append(
        "Recent commits, queued tasks, and blockers live in `.nexus/state-summary.md` "
        "(read this first). Update via:"
    )
    lines.append("")
    lines.append("```bash")
    lines.append('nexus journal next add "<task>"      # queue work')
    lines.append('nexus journal blocker add "<text>"   # record a blocker')
    lines.append('nexus journal log "<note>"           # append to journal')
    lines.append("nexus journal status                # show current state")
    lines.append("```")
    lines.append("")
    lines.append(
        "Run `nexus doctor` to check rule drift, journal health, and missing IDE files."
    )

    return "\n".join(lines)


def generate(profile: Profile, project_root: Path) -> list[GeneratedFile]:
    return [
        GeneratedFile(
            path=project_root / "AGENTS.md",
            content=_build_body(profile),
            mode="upsert",
            target="agents_md",
            block_id="agents-md",
        )
    ]
