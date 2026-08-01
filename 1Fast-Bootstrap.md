# Nexus Fast Project Enhancement

Nexus is already installed. Treat `AGENTS.md` as the canonical shared instruction file and `.agents/skills/<name>/SKILL.md` as the canonical workflow surface.

## Goal

Inspect this repository and make the smallest useful project-specific additions for daily development.

## Discovery

- Search manifests, README files, CI configuration, and existing tests before reading large files.
- Verify every command from repository evidence.
- Never print secret values; record environment variable names only.

## Changes

- Refine the Nexus-managed profile only through `.nexus/profile.json`; preserve user content outside managed blocks.
- Add scoped `AGENTS.md` files only when a subtree has genuinely different rules.
- Add at most three project-specific skills under `.agents/skills/<name>/SKILL.md` for repeatable setup, testing, or quality workflows.
- Do not create `.agents/rules`, flat workflow files, `.cursorrules`, VS Code rules, or provider copies.
- Keep provider adapters delta-only. Run `nexus generate` after profile changes.

## Verify

Run the repository's verified tests, then:

```text
nexus doctor --consumer all --deep --format human
nexus context audit --format human
nexus debug secrets-scan --format human
```

Report changed paths, evidence for commands, warnings, and unresolved `TODO(verify)` items.
