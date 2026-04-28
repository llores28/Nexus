# Nexus - Intelligent Project Operating System

Nexus creates a complete, AI-powered project operating system that optimizes development workflows and agent behaviors based on task complexity.

## Project Overview

This is `Nexus`, a reusable bootstrap toolkit that generates project-specific AI-powered operating systems including rules, agents, skills, workflows, and documentation.

### Key directories
- `nexus/` — Bootstrap prompt templates (Fast/Team/Enterprise) and a model cost reference doc
- `nexus/cli/` — Python CLI tools (smoketest, debug, research, scrape, local-env, scaffold)
- `.windsurf/rules/` — Nexus rule files with activation triggers
- `.windsurf/skills/` — Reusable skill definitions (SKILL.md + resources)
- `.windsurf/workflows/` — Slash-command workflow definitions

### Stack
- Python 3.10+ (CLI tools)
- Click + Rich (CLI framework)
- httpx + beautifulsoup4 (web scraping)
- Markdown (all config/templates)

## Operating Constraints

1. **No secrets** in output, commits, or logs.
2. **No invented commands** — verify from repo files before suggesting.
3. **Minimal changes** — prefer small, reversible edits.
4. **Security defaults** — validate paths, validate URLs, no shell=True, no eval/exec.
5. **Evidence-based** — cite file paths for non-trivial claims.
6. Mark uncertainty as `TODO(verify)`.

## Token/Quota Efficiency

- Use code search / Fast Context before reading full files.
- Read files in large chunks to avoid repeated small reads.
- Batch independent tool calls in parallel.
- Keep responses concise — no restating known context.
- For simple edits, suggest Ctrl+I (Command mode, free, no quota cost).
- For routine tasks, use SWE-1.5 (free model) or SWE-1.
- Suggest user run tests manually rather than auto-executing.

## Testing

- Run `python nexus/cli/bs_cli.py smoketest --level quick` for quick verification.
- Run `python nexus/cli/bs_cli.py prereqs` to check prerequisites.
- CLI tools emit structured JSON by default (`--format json`), human output via `--format human`.

## CLI Toolkit Commands

```
python nexus/cli/bs_cli.py prereqs              # Check prerequisites
python nexus/cli/bs_cli.py smoketest            # Run smoke tests
python nexus/cli/bs_cli.py debug secrets-scan   # Scan for leaked secrets
python nexus/cli/bs_cli.py research docs <q>    # Search docs
python nexus/cli/bs_cli.py scaffold <name>      # Create new CLI tool
python nexus/cli/bs_cli.py health check         # Nexus health check
python -m pytest tests/                         # Run journal test suite

# Journal (state, drift detection, ADRs, cross-tool surface)
python nexus/cli/bs_cli.py journal status                # Show current state
python nexus/cli/bs_cli.py journal log "<msg>"           # Log entry (auto-rolls stale sessions)
python nexus/cli/bs_cli.py journal next add "<task>"     # Queue work
python nexus/cli/bs_cli.py journal next done "<sub>"     # Mark queued task done
python nexus/cli/bs_cli.py journal blocker add "<text>"  # Record a blocker
python nexus/cli/bs_cli.py journal decision add "<t>"    # Create MADR ADR
python nexus/cli/bs_cli.py journal health                # Diagnose drift
python nexus/cli/bs_cli.py journal health refresh        # Auto-fix drift
python nexus/cli/bs_cli.py journal blame <file>          # Cross-ref file
python nexus/cli/bs_cli.py journal export                # Regen summary + dashboard
python nexus/cli/bs_cli.py journal setup-hooks [--force] # Install/upgrade git hooks
```

## Project State (Cross-Agent Contract)

All AI agents (Cascade, Claude Code, Cursor, Codex, or any future tool) MUST
follow this protocol:

1. **Before starting any multi-step task**: read `.nexus/state-summary.md`
   (AI-optimized, ≤200 lines). Fall back to `.nexus/state.md` for the full
   journal if more detail is needed.
   - Respect "What's Done" — do not revert recently completed fixes.
   - Check "Blockers" before proceeding.
   - Check "Active Now" / "What's Next" — these are the user-curated
     priorities; do not silently expand scope past them.

2. **After completing a significant change**: append a log entry. The
   post-commit hook auto-logs every commit, so explicit logging is only
   needed for non-commit work (research, decisions, planning):
   ```
   python nexus/cli/bs_cli.py journal log "<brief description>"
   ```

3. **Sessions auto-roll** when stale (idle ≥4h, new UTC date, or branch
   changed). Manual `journal session-start` / `journal session-end` are
   optional — the auto-roll path keeps `session_log` populated and
   `session_number` current without ceremony.

4. **For non-trivial design decisions**, create a MADR ADR:
   ```
   python nexus/cli/bs_cli.py journal decision add "<title>"
   ```
   This writes a stub at `docs/decisions/NNNN-slug.md` and auto-logs the
   decision creation to the journal.

5. **State files** (tool-agnostic, plain text):
   - `.nexus/state-summary.md` — AI-optimized snapshot (read this first)
   - `.nexus/state.md` — full journal grouped by Conventional Commits type
   - `.nexus/state.json` — machine-readable state (rolling buffer of last 100 done)
   - `.nexus/journal/YYYY-MM/DD.md` — append-only daily archive (system of record)
   - `.nexus/state-dashboard.html` — visual dashboard
   - `docs/decisions/NNNN-slug.md` — ADRs (committed by default)

6. **If the journal looks stale or out of sync with reality**, run:
   ```
   python nexus/cli/bs_cli.py journal health refresh
   ```
   This backfills any commits not reflected in `done` and regenerates the
   dashboards. `nexus init --upgrade` runs this automatically.

## Model Cost Reference (indicative)

There is no automated selection layer — the AI assistant or user picks a model based on task complexity. Rough tiers:

- **Simple tasks** (typos, formatting): SWE-1.5 (Free)
- **Moderate tasks** (multi-file edits): GPT-5 Low (0.5x)
- **Complex tasks** (refactoring): GPT-5 Med / Gemini 3.1 Pro (1x)
- **Expert tasks** (architecture): Claude Sonnet 4.6 / GPT-5 High (2x)
- **Frontier tasks** (threat modeling): Claude Opus 4.6 (2-3x)

<!-- nexus:state:begin -->
## Project State (auto-managed by `nexus journal init-agents`)

Current state, active tasks, and recent work for this project live in:

- `.nexus/state-summary.md` — AI-optimized summary (≤200 lines, **read this first**)
- `.nexus/state.md` — full journal (commit log grouped by Conventional Commits type)
- `.nexus/state-dashboard.html` — visual dashboard

Update via the journal CLI. Sessions auto-roll when stale (idle ≥4h, new
UTC date, or branch changed) — explicit `session-start`/`session-end` is
optional, and the post-commit hook keeps the journal current automatically.

```bash
python nexus/cli/bs_cli.py journal next add "<task>"        # queue work
python nexus/cli/bs_cli.py journal next done "<idx|substr>" # mark complete
python nexus/cli/bs_cli.py journal blocker add "<text>"     # record a blocker
python nexus/cli/bs_cli.py journal log "<note>"             # append to journal
python nexus/cli/bs_cli.py journal status                   # show current state
```

This block is regenerated by `nexus journal init-agents`. Edit content
outside the markers; anything between them will be replaced.
<!-- nexus:state:end -->

<!-- nexus:agents-md:begin -->
<!-- nexus: profile=754255363160 generator=agents_md nexus_version=0.2.0 -->

## Project: ws-bootstrap-master

- Tier: **team**
- Languages: python
- Package managers: pip
- Test runner: `pytest`
- CI: github-actions

## Conventions

- No secrets in output, commits, logs, or generated code. Reference environment variables; never hardcode credentials.
- Validate filesystem paths and URLs at trust boundaries before use. Never run untrusted user input through a shell.
- Don't invent APIs, commands, or file paths. Mark uncertainty explicitly (e.g. `TODO(verify)`).
- Prefer editing existing files over creating new ones. Don't proliferate scaffolding files.
- Don't add backwards-compatibility shims, dead-code comments, or unused re-exports for code that no longer exists. _[warn]_
- New code paths must have at least one test. Bug fixes ship with a regression test.
- Commits follow Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, ...) so the journal can group them.
- Never use `shell=True`, `eval()`, or `exec()`. Use `subprocess` argv lists. _(scope: **/*.py)_
- Public functions have type hints. Use `Optional`, `Literal`, and `TypedDict` for shapes that cross module boundaries. _(scope: **/*.py)_ _[warn]_

## Project state

Recent commits, queued tasks, and blockers live in `.nexus/state-summary.md` (read this first). Update via:

```bash
nexus journal next add "<task>"      # queue work
nexus journal blocker add "<text>"   # record a blocker
nexus journal log "<note>"           # append to journal
nexus journal status                # show current state
```

Run `nexus doctor` to check rule drift, journal health, and missing IDE files.
<!-- nexus:agents-md:end -->
