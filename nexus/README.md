# Nexus Bootstrap Templates

This folder contains provider-neutral Fast, Team, Enterprise, and universal
bootstrap prompts. They generate one cohesive operating surface for OpenAI
Codex, Devin, Claude, Cursor, GitHub Copilot, and VS Code extension hosts.

## Canonical surfaces

| Surface | Purpose |
|---|---|
| `AGENTS.md` | Stable shared constraints and verified project commands |
| `.agents/skills/*/SKILL.md` | Just-in-time reusable workflows |
| `CLAUDE.md` | Claude-only adapter and deltas |
| `.cursor/rules/` | Cursor-only scoped deltas |
| `.github/copilot-instructions.md` | Copilot-only adapter and deltas |
| `.nexus/state-summary.md` | At-most-80-line four-field handoff |

Legacy `.windsurf/rules`, `.windsurf/skills`, and `.windsurf/workflows` are
accepted only as migration inputs by `nexus init --upgrade`. New projects use
`AGENTS.md` and `.agents/skills`; Nexus does not ship or generate legacy files.

The distributable skill bundle lives under `bundles/default/skills`. Each skill
is self-contained: optional scripts, references, and assets travel with its
`SKILL.md`. Tests install that bundle into temporary target repositories and
verify the generated `.agents/skills` and `.claude/skills` projections there;
generated target surfaces are not stored in the source checkout.

## Context-efficient workflow

1. Choose the Fast, Team, or Enterprise template through `nexus init`.
2. Search before reading implementation files and load skills just in time.
3. Run `nexus context audit` to find duplicated or oversized context.
4. Use `nexus context map <query>` for a bounded repository skeleton.
5. Use `nexus context mask` for large test, lint, and build observations.
6. Preserve intent and handoff state with `nexus journal intent`,
   `journal decision note`, and `journal handoff`.

Repomix support is optional and never downloaded automatically. Routing advice
is provider-neutral and available through `nexus context route`.
