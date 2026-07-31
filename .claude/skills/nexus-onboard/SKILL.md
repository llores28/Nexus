---
name: nexus-onboard
description: Install or upgrade Nexus in a repository with a dry-run preview, collision-safe skills, and provider-specific verification.
---

# Nexus onboarding

## Fresh project

1. Confirm the repository root and desired Fast, Team, or Enterprise tier.
2. Preview with `nexus init --project-dir . --template <tier> --dry-run`.
3. Review preserved files and collisions.
4. Apply with `nexus init --project-dir . --template <tier> --yes`.

## Existing project

1. Run `nexus init --project-dir . --upgrade --dry-run`.
2. Confirm Nexus will preserve user-modified files and legacy `.windsurf` inputs.
3. Apply with `nexus init --project-dir . --upgrade --yes`.

## Verify

Run `nexus doctor --consumer all --deep --format human`. Claude users should approve the `@AGENTS.md` import and restart Claude Code if `.claude/skills` was created after the session began.
