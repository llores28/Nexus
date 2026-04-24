---
description: Close the current session, summarize changes, update project state, and export dashboard
---
# Session Handoff

Use this at the end of any significant work session to capture what was done and prep the next session.

## Step 1 — Show current changes
// turbo
```
python nexus/cli/bs_cli.py journal diff --project-dir . --format human
```

## Step 2 — Close the session (interactive)
```
python nexus/cli/bs_cli.py journal session-end --project-dir . --format human
```
This will:
- Auto-detect files changed (via git diff or mtime fallback)
- Prompt for a session summary
- Prompt for "what's next" tasks
- Prompt for any blockers
- Write `.nexus/state.md` and `.nexus/state.json`

## Step 3 — Export dashboard
// turbo
```
python nexus/cli/bs_cli.py journal export --project-dir . --format human
```
Opens `.nexus/state-dashboard.html` — open in browser to review.

## Step 4 — Handoff block
Share this with your next session (or paste into Claude Code / new Cascade chat):

```
Resume: run `python nexus/cli/bs_cli.py journal session-start --project-dir .`
State:  read `.nexus/state.md` for current status, done items, and next tasks.
```
