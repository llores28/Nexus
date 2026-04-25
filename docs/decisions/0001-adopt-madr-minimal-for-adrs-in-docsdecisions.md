# 0001. Adopt MADR-minimal for ADRs in docs/decisions

- **Status:** accepted
- **Date:** 2026-04-25
- **Deciders:** lannys.lores

## Context and Problem Statement

The Nexus journal Phase 1–3 refactor introduced commit-message grouping, daily
rotation, and a cross-tool state surface, but had no place for one-off design
decisions (commits capture changes, not the reasoning behind them). We need a
lightweight, version-controlled format for "why we chose X over Y" notes —
discoverable by any AI agent reading the repo and durable across sessions.

## Considered Options

- **MADR 4.0 minimal** (~25-line template, single Decision Outcome section)
- **MADR 4.0 full** (Pros/Cons per option, deciders, links — heavier)
- **Y-Statement** (single sentence, too terse for non-trivial decisions)
- **Free-form notes in `docs/`** (no structure, no agent-discoverability)

## Decision Outcome

Chosen option: **MADR 4.0 minimal**, because it gives a fixed shape (Status,
Context, Options, Decision, Consequences) without ceremony, fits in ~25 lines,
and is the format the AGENTS.md / Cursor / Claude ecosystems are converging on
in 2025–2026.

ADRs live at `docs/decisions/NNNN-slug.md` (committed by default; `.nexus/` is
gitignored so we deliberately do NOT put them under `.nexus/decisions/`). New
ADRs are created via `nexus journal decision add "<title>"`, which auto-numbers,
slugifies, and emits a stub the author fills in.

### Consequences

- Good: each non-trivial design decision has a permanent home, agent-readable
  and grep-able. The `journal decision` CLI keeps numbering consistent.
- Good: ADRs travel with the code in version control — surviving `.nexus/`
  resets, branch switches, and machine moves.
- Bad: requires authorial effort. Trivial decisions don't justify an ADR;
  judgment call on what's worth recording.

<!-- Authored via `nexus journal decision add`. Edit freely; Nexus does not regenerate this file. -->
