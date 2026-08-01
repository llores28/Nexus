# Nexus Enterprise Project Enhancement

Nexus is already installed. Use `AGENTS.md` for shared policy and `.agents/skills/<name>/SKILL.md` for procedures loaded only when relevant.

## Goal

Add evidence-backed governance for a high-risk repository without duplicating policy across agent providers.

## Discovery

- Map components, trust boundaries, sensitive data, authentication, deployment, ownership, CI gates, rollback paths, and incident surfaces.
- Cite repository paths for non-trivial claims and mark uncertainty as `TODO(verify)`.
- Do not expose secrets, contact services, install dependencies, or perform privileged operations without approval.

## Changes

- Put stable security, approval, testing, audit, and release requirements in root or scoped `AGENTS.md` through `.nexus/profile.json`.
- Add project-specific skills for secure setup, quality gates, dependency review, incident diagnosis, release readiness, rollback, and handoff where supported by evidence.
- Keep procedures concise; move detailed references, templates, and scripts into each skill's own directory.
- Use `REVIEW.md` only for review-specific deltas. Keep Claude, Cursor, and Copilot adapters delta-only.
- Preserve all unowned files and legacy `.windsurf` inputs. Do not create `.agents/rules`, flat workflows, `.cursorrules`, or VS Code-specific copies.

## Verify

Run all verified repository gates and:

```text
nexus smoketest --level quick --isolated-install --format human
nexus doctor --consumer all --deep --format human
nexus context audit --format human
nexus journal health --format human
nexus debug secrets-scan --format human
```

Report control evidence, failures, warnings, approval requirements, rollback notes, and unresolved assumptions.
