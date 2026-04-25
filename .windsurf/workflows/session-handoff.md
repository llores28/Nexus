---
description: Close the current session, summarize changes, update project state, and export dashboard
---
# Session Handoff

Use this at the end of any significant work session to capture what was done
and prep the next session.

> **Note:** sessions auto-roll on every `journal log` when stale (idle ≥4h,
> new UTC date, or branch changed), and the post-commit hook keeps the journal
> current automatically. This workflow is **optional** — most users never run
> it explicitly. Use it when you want an interactive summary + curated `next`
> list, or before stepping away for a few days.

## Step 1 — Show current changes
// turbo
```
python nexus/cli/bs_cli.py journal diff --project-dir . --format human
```

## Step 2 — Verify journal is in sync with git
// turbo
```
python nexus/cli/bs_cli.py journal health --format human
```
If status is `drift` or `stale`, run:
```
python nexus/cli/bs_cli.py journal health refresh --format human
```
This backfills missing commits and regenerates the dashboard + summary.

## Step 3 — Close the session (optional, interactive)
```
python nexus/cli/bs_cli.py journal session-end --project-dir . --format human
```
This will:
- Auto-detect files changed (via git diff or mtime fallback)
- Prompt for a session summary
- Prompt for "what's next" tasks
- Prompt for any blockers
- Write `.nexus/state.md` and `.nexus/state.json`
- Null `session_start_time` so the next `journal log` opens a fresh session

If you'd rather not run an interactive prompt, you can manage `next` and
`blockers` non-interactively:
```
python nexus/cli/bs_cli.py journal next add "<task>"
python nexus/cli/bs_cli.py journal blocker add "<text>"
```

## Step 4 — Export dashboard
// turbo
```
python nexus/cli/bs_cli.py journal export --project-dir . --format human
```
Regenerates `.nexus/state-summary.md` (AI-optimized snapshot) and
`.nexus/state-dashboard.html`. The pre-push git hook also does this
automatically.

## Step 5 — Handoff block
Share this with your next session (or paste into Claude Code / new Cascade chat):

```
State: read `.nexus/state-summary.md` for the AI-optimized snapshot.
       (Falls back to `.nexus/state.md` for the full journal.)
Next:  the journal will auto-open a fresh session on the first `journal log`
       call — no manual session-start needed.
```
