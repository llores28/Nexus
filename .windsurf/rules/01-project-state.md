---
trigger: always_on
---
# Project State Awareness

## Before Making Code Changes

1. If `.nexus/state.md` exists in the project, **read it first**.
   - Do NOT revert or remove recently logged fixes listed under "What's Done".
   - Check "Blockers" — do not proceed past a blocker without flagging it.

2. After completing any significant change (new feature, bug fix, refactor, security fix), log it:
   ```
   python nexus/cli/bs_cli.py journal log "<brief description of what changed>"
   ```

3. At the start of a new multi-step task (3+ edits), run:
   ```
   python nexus/cli/bs_cli.py journal session-start --project-dir .
   ```

4. When declaring a task "done", run:
   ```
   python nexus/cli/bs_cli.py journal session-end --project-dir .
   ```

## Regression Prevention

- Before editing any file, check if it appears in recent "What's Done" entries in `.nexus/state.md`.
- If a file was recently fixed, read it carefully before editing to avoid re-introducing the bug.
- Prefer targeted `edit` / `multi_edit` over full rewrites when a file has recent logged fixes.

## State File Locations

| File | Purpose |
|------|---------|
| `.nexus/state.md` | Human + AI readable ground truth (read this) |
| `.nexus/state.json` | Machine-readable state (used by dashboard) |
| `.nexus/state-dashboard.html` | Visual dashboard (run `journal export` to refresh) |
