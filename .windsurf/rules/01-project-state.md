---
trigger: always_on
---
# Project State Awareness

## Before Making Code Changes

1. If `.nexus/state-summary.md` exists, **read it first** (AI-optimized
   snapshot, ≤200 lines). Fall back to `.nexus/state.md` for the full journal.
   - Respect "Recent Work" — do not revert recently completed fixes.
   - Check "Blockers" — do not proceed past a blocker without flagging it.
   - Check "Active Now" / "What's Next" — these are user-curated priorities;
     don't silently expand scope past them.

2. After completing any significant change (new feature, bug fix, refactor,
   security fix), log it. The post-commit hook auto-logs every commit, so
   explicit logging is only needed for non-commit work (research, decisions):
   ```
   python nexus/cli/bs_cli.py journal log "<brief description of what changed>"
   ```

3. **Sessions auto-roll** — manual session lifecycle is optional. The journal
   automatically opens a new session when the previous one is stale (idle ≥4h,
   new UTC date, or branch changed). You do not need to run `session-start` or
   `session-end` for routine work.

4. For non-trivial design decisions (architecture, library choice, security
   trade-off), create a MADR ADR:
   ```
   python nexus/cli/bs_cli.py journal decision add "<title>"
   ```
   This writes a stub at `docs/decisions/NNNN-slug.md` for you to fill in.

5. To queue work or record blockers (non-interactive):
   ```
   python nexus/cli/bs_cli.py journal next add "<task>"
   python nexus/cli/bs_cli.py journal next done "<idx|substr>"
   python nexus/cli/bs_cli.py journal blocker add "<text>"
   ```

## Regression Prevention

- Before editing any file, check if it appears in recent "Recent Work"
  entries in `.nexus/state-summary.md`, or run:
  ```
  python nexus/cli/bs_cli.py journal blame <file>
  ```
  to see commits, journal entries, and daily mentions for the file.
- If a file was recently fixed, read it carefully before editing to avoid
  re-introducing the bug.
- Prefer targeted `edit` / `multi_edit` over full rewrites when a file has
  recent logged fixes.

## If the Journal Looks Stale

Run a drift check (compares state.json against git commits and PRD timestamp):

```
python nexus/cli/bs_cli.py journal health
python nexus/cli/bs_cli.py journal health refresh   # auto-fix drift
```

`refresh` backfills any commits not reflected in `done`, regenerates the
dashboard + state-summary.md, and re-opens the session if it was closed.
`nexus init --upgrade` runs this automatically.

## State File Locations

| File | Purpose |
|------|---------|
| `.nexus/state-summary.md` | AI-optimized snapshot (read this first) |
| `.nexus/state.md` | Full journal grouped by Conventional Commits type |
| `.nexus/state.json` | Machine-readable state (rolling buffer of last 100 done) |
| `.nexus/journal/YYYY-MM/DD.md` | Append-only daily archive (system of record) |
| `.nexus/state-dashboard.html` | Visual dashboard (run `journal export` to refresh) |
| `docs/decisions/NNNN-slug.md` | MADR ADRs (committed by default) |
