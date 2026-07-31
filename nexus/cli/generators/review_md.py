"""Optional Devin Review adapter containing review-only deltas."""

from pathlib import Path

from nexus.cli.generators import GeneratedFile, stamp
from nexus.cli.profile import Profile, hash_profile, select_rules


def generate(profile: Profile, project_root: Path) -> list[GeneratedFile]:
    rules = [
        rule for rule in select_rules(profile, target="devin-review")
        if rule.targets is not None and "devin-review" in rule.targets
    ]
    if not rules:
        return []
    lines = [stamp(hash_profile(profile), "devin-review"), "", "# Review-specific guidance", ""]
    for rule in rules:
        scope = f" (scope: `{', '.join(rule.applies_to)}`)" if rule.applies_to else ""
        lines.append(f"- {rule.text}{scope}")
    return [
        GeneratedFile(
            path=project_root / "REVIEW.md",
            content="\n".join(lines) + "\n",
            mode="upsert",
            target="devin-review",
            block_id="devin-review",
        )
    ]
