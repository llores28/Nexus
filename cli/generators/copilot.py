"""GitHub Copilot generator.

Emits the tiered instruction layout Copilot supports today:

- ``.github/copilot-instructions.md`` -- repo-wide
- ``.github/instructions/<lang>.instructions.md`` -- per-language with ``applyTo`` frontmatter
"""

from pathlib import Path

from nexus.cli.profile import Profile, Rule, hash_profile, select_rules
from nexus.cli.generators import GeneratedFile, stamp


_LANG_GLOBS: dict[str, tuple[str, ...]] = {
    "python": ("**/*.py",),
    "typescript": ("**/*.ts", "**/*.tsx"),
    "javascript": ("**/*.js", "**/*.jsx", "**/*.mjs"),
    "go": ("**/*.go",),
}


def _ext_set(globs: tuple[str, ...]) -> set[str]:
    out: set[str] = set()
    for g in globs:
        if "*." in g:
            ext = "." + g.rsplit("*.", 1)[1]
            ext = ext.split("/")[0]
            out.add(ext)
    return out


def _rule_matches_lang(rule: Rule, lang_globs: tuple[str, ...]) -> bool:
    if not rule.applies_to:
        return False
    return bool(_ext_set(rule.applies_to) & _ext_set(lang_globs))


def _repo_wide(profile: Profile, h: str) -> str:
    out = [
        stamp(h, "copilot.repo"),
        "",
        f"# Copilot adapter — {profile.project_name}",
        "",
        "Read `AGENTS.md` as the canonical project instruction source.",
        "Load `.agents/skills/*/SKILL.md` only when the task matches a skill.",
        "Copilot-specific scoped deltas live in `.github/instructions/`.",
    ]
    out.append("")
    return "\n".join(out)


def _per_lang(profile: Profile, lang: str, h: str) -> str | None:
    globs = _LANG_GLOBS.get(lang)
    if not globs:
        return None
    scoped = [
        r for r in select_rules(profile, target="copilot", only_scoped=True)
        if r.targets is not None
    ]
    matched = [r for r in scoped if _rule_matches_lang(r, globs)]
    if not matched:
        return None
    apply_to_value = ",".join(globs)
    out = [
        "---",
        f"applyTo: '{apply_to_value}'",
        "---",
        "",
        stamp(h, f"copilot.{lang}"),
        "",
        f"# {lang.title()} conventions",
        "",
    ]
    for r in matched:
        sev = "" if r.severity == "must" else f" ({r.severity})"
        out.append(f"- {r.text}{sev}")
    out.append("")
    return "\n".join(out)


def generate(profile: Profile, project_root: Path) -> list[GeneratedFile]:
    h = hash_profile(profile)
    # Repo-wide copilot-instructions.md uses upsert: many projects have rich,
    # hand-curated existing content here (project context, coding standards,
    # journal sections). Upsert preserves user content outside the
    # `<!-- nexus:copilot-repo:* -->` markers across regenerations.
    files: list[GeneratedFile] = [
        GeneratedFile(
            path=project_root / ".github" / "copilot-instructions.md",
            content=_repo_wide(profile, h),
            mode="upsert",
            target="copilot",
            block_id="copilot-repo",
        )
    ]
    # Per-language `.github/instructions/<lang>.instructions.md` is fully
    # Nexus-owned: it has YAML frontmatter (`applyTo:`) and is rarely
    # hand-edited. Overwrite is fine here — drift is detected by stamp.
    for lang in profile.languages:
        body = _per_lang(profile, lang, h)
        if body is not None:
            files.append(
                GeneratedFile(
                    path=project_root / ".github" / "instructions" / f"{lang}.instructions.md",
                    content=body,
                    mode="overwrite",
                    target="copilot",
                    block_id=f"copilot-{lang}",
                )
            )
    return files
