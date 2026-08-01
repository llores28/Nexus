"""
Seed rules composed by ``Profile.from_detection``.

Three groups:
  - CORE_RULES        always emitted
  - TIER_RULES_*      gated by ``tier_min``
  - lang/framework    gated by detected stack

Users override by editing ``.nexus/profile.json`` directly. Adding a rule
here will start emitting it on the next ``nexus profile detect``.
"""

from nexus.cli.profile import Rule, Tier


CORE_RULES: tuple[Rule, ...] = (
    Rule(
        id="no-secrets",
        text=(
            "No secrets in output, commits, logs, or generated code. "
            "Reference environment variables; never hardcode credentials."
        ),
    ),
    Rule(
        id="validate-paths-and-urls",
        text=(
            "Validate filesystem paths and URLs at trust boundaries before use. "
            "Never run untrusted user input through a shell."
        ),
    ),
    Rule(
        id="no-fabrication",
        text=(
            "Don't invent APIs, commands, or file paths. "
            "Mark uncertainty explicitly (e.g. `TODO(verify)`)."
        ),
    ),
    Rule(
        id="prefer-edit-existing",
        text=(
            "Prefer editing existing files over creating new ones. "
            "Don't proliferate scaffolding files."
        ),
    ),
    Rule(
        id="no-bc-shims",
        text=(
            "Don't add backwards-compatibility shims, dead-code comments, "
            "or unused re-exports for code that no longer exists."
        ),
        severity="warn",
    ),
)


TIER_RULES_TEAM: tuple[Rule, ...] = (
    Rule(
        id="tests-required",
        text=(
            "New code paths must have at least one test. "
            "Bug fixes ship with a regression test."
        ),
        tier_min="team",
    ),
    Rule(
        id="conventional-commits",
        text=(
            "Commits follow Conventional Commits "
            "(`feat:`, `fix:`, `docs:`, `chore:`, ...) so the journal can group them."
        ),
        tier_min="team",
    ),
)


TIER_RULES_ENTERPRISE: tuple[Rule, ...] = (
    Rule(
        id="pr-required",
        text=(
            "All non-trivial changes ship via PR with at least one reviewer. "
            "No direct pushes to main."
        ),
        tier_min="enterprise",
    ),
    Rule(
        id="adr-for-decisions",
        text=(
            "Architectural decisions get an ADR in `docs/decisions/`. "
            "Use `nexus journal decision add \"<title>\"` to scaffold."
        ),
        tier_min="enterprise",
    ),
    Rule(
        id="audit-log",
        text=(
            "CLI invocations and security-relevant operations are audit-logged "
            "via `nexus.cli.security.audit_log`."
        ),
        tier_min="enterprise",
    ),
)


# --- Language-scoped rules (applies_to globs select per-IDE projection) ---

PYTHON_RULES: tuple[Rule, ...] = (
    Rule(
        id="py-no-shell-true",
        text=(
            "Never use `shell=True`, `eval()`, or `exec()`. "
            "Use `subprocess` argv lists."
        ),
        applies_to=("**/*.py",),
    ),
    Rule(
        id="py-type-hints",
        text=(
            "Public functions have type hints. Use `Optional`, `Literal`, and "
            "`TypedDict` for shapes that cross module boundaries."
        ),
        applies_to=("**/*.py",),
        severity="warn",
    ),
)

TYPESCRIPT_RULES: tuple[Rule, ...] = (
    Rule(
        id="ts-no-any",
        text=(
            "Avoid `any`. Use `unknown` and narrow, or define a proper type/interface."
        ),
        applies_to=("**/*.ts", "**/*.tsx"),
    ),
    Rule(
        id="ts-explicit-imports",
        text=(
            "Import directly from the source path; avoid barrel re-exports across "
            "module boundaries."
        ),
        applies_to=("**/*.ts", "**/*.tsx"),
        severity="warn",
    ),
)

JAVASCRIPT_RULES: tuple[Rule, ...] = (
    Rule(
        id="js-strict",
        text="Use strict mode and ES modules. Avoid implicit globals.",
        applies_to=("**/*.js", "**/*.mjs"),
        severity="warn",
    ),
)

GO_RULES: tuple[Rule, ...] = (
    Rule(
        id="go-error-wrap",
        text='Wrap returned errors with context: `fmt.Errorf("operation: %w", err)`.',
        applies_to=("**/*.go",),
    ),
    Rule(
        id="go-context-first",
        text="Functions that may block accept `context.Context` as their first parameter.",
        applies_to=("**/*.go",),
        severity="warn",
    ),
)


# --- Framework-scoped rules ---

FASTAPI_RULES: tuple[Rule, ...] = (
    Rule(
        id="fastapi-pydantic",
        text=(
            "Use Pydantic models for request/response bodies. "
            "Don't accept raw dicts."
        ),
        applies_to=("**/*.py",),
    ),
    Rule(
        id="fastapi-deps",
        text=(
            "Push shared logic into `Depends()` providers. "
            "Don't reimplement auth/DB-session boilerplate per route."
        ),
        applies_to=("**/*.py",),
        severity="warn",
    ),
)

DJANGO_RULES: tuple[Rule, ...] = (
    Rule(
        id="django-orm",
        text=(
            "Use the ORM, not raw SQL, unless performance demands it. "
            "Always parameterize when raw."
        ),
        applies_to=("**/*.py",),
    ),
)

FLASK_RULES: tuple[Rule, ...] = (
    Rule(
        id="flask-app-factory",
        text=(
            "Use the application-factory pattern. "
            "Avoid module-level `app = Flask(__name__)`."
        ),
        applies_to=("**/*.py",),
        severity="warn",
    ),
)

NEXTJS_RULES: tuple[Rule, ...] = (
    Rule(
        id="next-server-components",
        text=(
            "Default to Server Components. "
            "Add `'use client'` only when interactivity demands it."
        ),
        applies_to=("**/*.tsx", "**/*.jsx"),
    ),
    Rule(
        id="next-no-secrets-in-client",
        text=(
            "Never reference server-only env vars in client components. "
            "Prefix client-safe vars with `NEXT_PUBLIC_`."
        ),
        applies_to=("**/*.tsx", "**/*.jsx"),
    ),
)

EXPRESS_RULES: tuple[Rule, ...] = (
    Rule(
        id="express-helmet-cors",
        text=(
            "Use `helmet` and explicit `cors` configuration. "
            "Don't rely on default-permissive headers."
        ),
        applies_to=("**/*.ts", "**/*.js"),
        severity="warn",
    ),
)


_LANG_RULES: dict[str, tuple[Rule, ...]] = {
    "python": PYTHON_RULES,
    "typescript": TYPESCRIPT_RULES,
    "javascript": JAVASCRIPT_RULES,
    "go": GO_RULES,
}

_FRAMEWORK_RULES: dict[str, tuple[Rule, ...]] = {
    "fastapi": FASTAPI_RULES,
    "django": DJANGO_RULES,
    "flask": FLASK_RULES,
    "nextjs": NEXTJS_RULES,
    "express": EXPRESS_RULES,
}


def _as_managed(r: Rule) -> Rule:
    """Return a copy of ``r`` with ``nexus_managed=True`` so seed rules are
    distinguishable from user-authored ones at load time."""
    if r.nexus_managed:
        return r
    return Rule(
        id=r.id,
        text=r.text,
        severity=r.severity,
        applies_to=r.applies_to,
        targets=r.targets,
        tier_min=r.tier_min,
        nexus_managed=True,
    )


def compose_rules(
    *,
    tier: Tier,
    languages: tuple[str, ...],
    frameworks: tuple[str, ...],
) -> tuple[Rule, ...]:
    """Compose seed rules for the given tier + stack. Stable ordering, no duplicates.

    All returned rules are stamped ``nexus_managed=True`` so on later re-detection
    they can be replaced wholesale while user-authored rules (``nexus_managed=False``)
    are preserved.
    """
    rules: list[Rule] = list(CORE_RULES)
    if tier in ("team", "enterprise"):
        rules.extend(TIER_RULES_TEAM)
    if tier == "enterprise":
        rules.extend(TIER_RULES_ENTERPRISE)

    seen: set[str] = {r.id for r in rules}
    for lang in languages:
        for r in _LANG_RULES.get(lang, ()):
            if r.id not in seen:
                rules.append(r)
                seen.add(r.id)
    for fw in frameworks:
        for r in _FRAMEWORK_RULES.get(fw, ()):
            if r.id not in seen:
                rules.append(r)
                seen.add(r.id)
    return tuple(_as_managed(r) for r in rules)
