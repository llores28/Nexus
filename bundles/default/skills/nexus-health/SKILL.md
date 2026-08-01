---
name: nexus-health
description: Validate Nexus instructions, skills, provider adapters, installation ownership, context efficiency, and journal readiness.
---

# Nexus health

Use after onboarding, upgrades, or whenever agent behavior appears inconsistent.

## Procedure

1. Run `nexus doctor --consumer all --deep --format human` as the authoritative readiness check.
2. Run `nexus context audit --format human` to inspect effective context, duplication, ignore coverage, and optional Repomix availability.
3. Run `nexus journal health --format human` if journal readiness is not clean.
4. Run `nexus debug secrets-scan --format human` before proposing a commit.
5. Treat FAIL as a blocker. Report WARN items explicitly; do not describe a warning-only run as fully clean.

Do not repair files until the user asks for implementation. Use `nexus init --upgrade --dry-run` to preview a safe repair.
