# Nexus — Intelligent Project Operating System

Nexus is a Python 3.10+ bootstrap toolkit that generates provider-neutral
project instructions, Agent Skills, workflows, and compact cross-agent state.

## Repository map

- `cli/` — Click/Rich CLI and provider-neutral generators
- repository root — Fast, Team, Enterprise, and universal bootstrap templates
- `bundles/default/skills/` — distributable Agent Skills source
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
python cli/bs_cli.py context audit
python cli/bs_cli.py context map <query>
python cli/bs_cli.py context mask --input <path|-> --kind test
python cli/bs_cli.py smoketest --level quick
python cli/bs_cli.py debug secrets-scan
python cli/bs_cli.py journal handoff
python -m pytest tests/
```

`nexus context route --task-class <class>` advises by capability and risk:
mechanical, routine, complex, or high-risk. It does not select providers or
execute models.

The source checkout is not itself a Nexus-installed target. Installation,
projection, ownership, and upgrade behavior is exercised in temporary test
repositories. Run `nexus doctor` inside an initialized target project, not
against this source checkout.
