# Nexus — Intelligent Project Operating System

Nexus is a Python 3.10+ bootstrap toolkit that generates provider-neutral
project instructions, Agent Skills, workflows, and compact cross-agent state.

## Repository map

- `nexus/cli/` — Click/Rich CLI and provider-neutral generators
- `nexus/` — Fast, Team, Enterprise, and universal bootstrap templates
- `.agents/skills/` — canonical just-in-time workflows
- `tests/` — pytest suite
- Target-project `.windsurf/*` — accepted only as read-only legacy migration input

## Working rules

- Search first and read only the exact ranges needed for the current decision.
- Load skill bodies and implementation details just in time.
- Prefer small reversible patches; never use `shell=True`, `eval`, or `exec`.
- Validate paths and URLs at trust boundaries and never expose secrets.
- Verify commands and paths from the repository; mark uncertainty `TODO(verify)`.
- Run targeted tests for local edits and broader gates for cross-cutting changes.
- Before multi-step work, read `.nexus/state-summary.md` if it exists. Missing
  state means uninitialized—not an active session.
- Log significant non-commit work; use Conventional Commits when committing.

## Verified commands

```bash
python nexus/cli/bs_cli.py context audit
python nexus/cli/bs_cli.py context map <query>
python nexus/cli/bs_cli.py context mask --input <path|-> --kind test
python nexus/cli/bs_cli.py smoketest --level quick
python nexus/cli/bs_cli.py debug secrets-scan
python nexus/cli/bs_cli.py journal handoff
python -m pytest tests/
```

`nexus context route --task-class <class>` advises by capability and risk:
mechanical, routine, complex, or high-risk. It does not select providers or
execute models.

<!-- nexus:agents-md:begin -->
<!-- nexus: profile=c126522c7c0e generator=agents_md nexus_version=0.3.0 -->

## Project: Nexus

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

Read `.nexus/state-summary.md` first. It is an at-most-80-line handoff with intent, changes, decisions, and next steps/blockers. Update via:

```bash
nexus journal next add "<task>"      # queue work
nexus journal blocker add "<text>"   # record a blocker
nexus journal intent set "<goal>"     # anchor current intent
nexus journal decision note "<text>"  # record a compact decision
nexus journal handoff                # emit compact state
nexus journal log "<note>"           # append to journal
nexus journal status                # show current state
```

Run `nexus doctor` to check rule drift, journal health, and missing IDE files.
Use `.agents/skills/*/SKILL.md` just in time; do not preload every skill.
<!-- nexus:agents-md:end -->
