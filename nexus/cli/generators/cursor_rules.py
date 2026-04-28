"""Cursor rules generator -- ``.cursor/rules/*.mdc`` with YAML frontmatter.

Emits two kinds of files:

- ``00-core.mdc`` (alwaysApply: true) -- whole-repo conventions.
- ``10-<framework>.mdc`` (globs: framework-specific) -- per-framework rules.

Files are written in overwrite mode (the entire .mdc is Nexus-owned).
The drift stamp lives in the file body, just below the frontmatter.
"""

from pathlib import Path

from nexus.cli.profile import Profile, Rule, hash_profile, select_rules
from nexus.cli.generators import GeneratedFile, stamp


_FRAMEWORK_GLOBS: dict[str, tuple[str, ...]] = {
    "nextjs": ("**/*.tsx", "**/*.jsx", "app/**/*", "pages/**/*"),
    "nuxt": ("**/*.vue", "**/*.ts", "pages/**/*"),
    "sveltekit": ("**/*.svelte", "**/*.ts"),
    "vite": ("src/**/*",),
    "cra": ("src/**/*",),
    "express": ("**/*.ts", "**/*.js"),
    "fastapi": ("**/*.py",),
    "django": ("**/*.py",),
    "flask": ("**/*.py",),
}


def _frontmatter(*, description: str, always_apply: bool, globs: tuple[str, ...] = ()) -> str:
    lines = ["---", f"description: {description}"]
    if globs:
        lines.append("globs: [" + ", ".join(repr(g) for g in globs) + "]")
    lines.append(f"alwaysApply: {'true' if always_apply else 'false'}")
    lines.append("---")
    return "\n".join(lines)


def _ext_set(globs: tuple[str, ...]) -> set[str]:
    """Extract file extensions from glob patterns, e.g. ('**/*.py',) -> {'.py'}."""
    out: set[str] = set()
    for g in globs:
        if "*." in g:
            ext = "." + g.rsplit("*.", 1)[1]
            # Strip path-suffix parts: '*.py' OR '*.ts/something' (rare)
            ext = ext.split("/")[0]
            out.add(ext)
    return out


def _rule_matches_globs(rule: Rule, fw_globs: tuple[str, ...]) -> bool:
    """A rule matches a framework if their extension sets intersect."""
    if not rule.applies_to:
        return False
    return bool(_ext_set(rule.applies_to) & _ext_set(fw_globs))


def _core_file(profile: Profile, h: str) -> str:
    rules = select_rules(profile, target="cursor", only_global=True)
    out = [
        _frontmatter(
            description="Project conventions and constraints (managed by Nexus)",
            always_apply=True,
        ),
        "",
        stamp(h, "cursor.00-core"),
        "",
        f"# {profile.project_name}",
        "",
        f"**Tier:** {profile.tier}.",
    ]
    if profile.frameworks or profile.languages:
        stack_bits: list[str] = []
        if profile.frameworks:
            stack_bits.append(", ".join(profile.frameworks))
        if profile.languages:
            stack_bits.append(", ".join(profile.languages))
        out.append(f"**Stack:** {' / '.join(stack_bits)}.")
    out.append("")
    out.append("## Conventions")
    out.append("")
    if rules:
        for r in rules:
            sev = "" if r.severity == "must" else f" _[{r.severity}]_"
            out.append(f"- {r.text}{sev}")
    else:
        out.append("- (no whole-repo rules configured)")
    out.append("")
    out.append("Run `nexus doctor` to verify rules and stack are in sync.")
    out.append("")
    return "\n".join(out)


def _framework_file(profile: Profile, fw: str, h: str) -> str | None:
    fw_globs = _FRAMEWORK_GLOBS.get(fw)
    if not fw_globs:
        return None
    scoped = select_rules(profile, target="cursor", only_scoped=True)
    matched = [r for r in scoped if _rule_matches_globs(r, fw_globs)]
    if not matched:
        return None
    out = [
        _frontmatter(
            description=f"{fw} conventions (managed by Nexus)",
            always_apply=False,
            globs=fw_globs,
        ),
        "",
        stamp(h, f"cursor.10-{fw}"),
        "",
        f"# {fw.title()} conventions",
        "",
    ]
    for r in matched:
        sev = "" if r.severity == "must" else f" _[{r.severity}]_"
        out.append(f"- {r.text}{sev}")
    out.append("")
    return "\n".join(out)


def generate(profile: Profile, project_root: Path) -> list[GeneratedFile]:
    h = hash_profile(profile)
    files: list[GeneratedFile] = [
        GeneratedFile(
            path=project_root / ".cursor" / "rules" / "00-core.mdc",
            content=_core_file(profile, h),
            mode="overwrite",
            target="cursor",
            block_id="cursor-00-core",
        )
    ]
    for fw in profile.frameworks:
        body = _framework_file(profile, fw, h)
        if body is not None:
            files.append(
                GeneratedFile(
                    path=project_root / ".cursor" / "rules" / f"10-{fw}.mdc",
                    content=body,
                    mode="overwrite",
                    target="cursor",
                    block_id=f"cursor-10-{fw}",
                )
            )
    return files
