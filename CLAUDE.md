# Claude Code Instructions — ws-bootstrap-master

This file provides project-specific instructions to Claude Code and VS Code with Claude.
For Windsurf, see `.windsurf/rules/` and `AGENTS.md`. For GitHub Copilot, see `.github/copilot-instructions.md`.

## Project

Reusable bootstrap toolkit generating project-specific AI IDE operating systems (rules, agents, skills, workflows, docs).

## Stack
- Python 3.10+, Click, Rich, httpx, beautifulsoup4
- Entry: `bootstrap/cli/bs_cli.py`
- Templates: `bootstrap/{1Fast,2Team,3Enterprise}-ws-Bootstrap.md`

## Constraints
- No secrets in output/commits/logs
- No invented commands — verify from repo files
- No shell=True, eval(), exec()
- Validate paths via `bootstrap/cli/security.py:validate_path()`
- Validate URLs via `bootstrap/cli/security.py:validate_url()`
- Structured output via `bootstrap/cli/utils.py:emit()`
- Mark uncertainty as `TODO(verify)`

## Commands
```bash
python bootstrap/cli/bs_cli.py prereqs           # Check prerequisites
python bootstrap/cli/bs_cli.py smoketest --level quick  # Quick smoke test
python bootstrap/cli/bs_cli.py debug secrets-scan # Scan for leaked secrets
python bootstrap/cli/bs_cli.py research docs <q>  # Search docs
python bootstrap/cli/bs_cli.py scaffold <name>    # Create new CLI tool
```

## Key Directories
- `bootstrap/` — Templates + CLI toolkit
- `bootstrap/cli/tools/` — Individual CLI tool implementations
- `.windsurf/` — Windsurf-specific rules, skills, workflows
- `.github/` — GitHub Copilot instructions
