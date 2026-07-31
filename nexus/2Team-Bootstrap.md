# Nexus Team Project Enhancement

Nexus is already installed. `AGENTS.md` is authoritative for shared rules; `.agents/skills/<name>/SKILL.md` contains reusable just-in-time workflows.

## Goal

Create a concise team operating layer grounded in this repository's real stack, tests, CI, ownership, and release process.

## Discovery

- Build a compact component and command map from manifests, CI, tests, and key documentation.
- Identify risk zones, approval boundaries, deployment surfaces, and unknowns without reading generated or ignored content unnecessarily.
- Never expose secrets or invent commands.

## Changes

- Update `.nexus/profile.json` with stable shared rules and genuine provider-only deltas.
- Keep one root `AGENTS.md`; add scoped copies only for distinct components.
- Add project-specific Agent Skills for setup, test/quality gates, debugging, release readiness, and handoff when repository evidence supports them.
- Each skill must follow the Agent Skills standard and reference supporting resources with shallow relative paths.
- Keep `CLAUDE.md`, Cursor rules, Copilot instructions, and optional `REVIEW.md` below 1 KB where practical and free of shared-rule duplication.
- Do not create legacy Windsurf artifacts, `.cursorrules`, separate workflow directories, or a VS Code ruleset.

## Verify

Run verified repository checks plus:

```text
nexus doctor --consumer all --deep --format human
nexus context audit --format human
nexus journal health --format human
nexus debug secrets-scan --format human
```

Report evidence, preserved collisions, warnings, and next steps.
