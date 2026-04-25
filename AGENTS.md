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
python nexus/cli/bs_cli.py prereqs          # Check prerequisites
python nexus/cli/bs_cli.py smoketest         # Run smoke tests
python nexus/cli/bs_cli.py debug logs <path> # Inspect logs
python nexus/cli/bs_cli.py debug secrets-scan # Scan for leaked secrets
python nexus/cli/bs_cli.py research docs <q> # Search docs
python nexus/cli/bs_cli.py scrape page <url> # Scrape a page
python nexus/cli/bs_cli.py local-env up      # Start containers
python nexus/cli/bs_cli.py scaffold <name>   # Create new CLI tool
python nexus/cli/bs_cli.py journal session-start  # Start session, show last state
python nexus/cli/bs_cli.py journal log "<msg>"    # Log a change event
python nexus/cli/bs_cli.py journal session-end    # Close session, capture changes
python nexus/cli/bs_cli.py journal export         # Generate state-dashboard.html
python nexus/cli/bs_cli.py journal status         # Show current project state
python nexus/cli/bs_cli.py journal setup-hooks    # Install git hooks (post-commit auto-log, pre-push dashboard)
```

## Project State (Cross-Agent Contract)

All AI agents (Cascade, Claude Code, Cursor, or any future tool) MUST follow this protocol:

1. **Before starting any multi-step task**: read `.nexus/state.md` if it exists.
   - Respect "What's Done" — do not revert recently completed fixes.
   - Check "Blockers" before proceeding.

2. **After completing a significant change**: append a log entry:
   ```
   python nexus/cli/bs_cli.py journal log "<brief description>"
   ```

3. **Starting a new work session**: run:
   ```
   python nexus/cli/bs_cli.py journal session-start --project-dir .
   ```

4. **Ending a work session**: run:
   ```
   python nexus/cli/bs_cli.py journal session-end --project-dir .
   python nexus/cli/bs_cli.py journal export --project-dir .
   ```

5. **State files** (tool-agnostic, plain text):
   - `.nexus/state.md` — human + AI readable ground truth
   - `.nexus/state.json` — machine-readable
   - `.nexus/state-dashboard.html` — visual dashboard (static HTML)

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
