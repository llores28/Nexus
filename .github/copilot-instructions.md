# GitHub Copilot Instructions — ws-bootstrap-master

This file provides project-specific instructions to GitHub Copilot in VS Code.
For Windsurf (Cascade), see `.windsurf/rules/` and `AGENTS.md`.

## Project Context

This is a reusable bootstrap toolkit that generates project-specific AI IDE operating systems.
- **Stack**: Python 3.10+, Click, Rich, httpx, beautifulsoup4
- **Entry point**: `bootstrap/cli/bs_cli.py`
- **Templates**: `bootstrap/1Fast-ws-Bootstrap.md`, `2Team-ws-Bootstrap.md`, `3Enterprise-ws-Bootstrap.md`

## Coding Standards

- Python: PEP 8, type hints, docstrings for public functions.
- No `shell=True` in subprocess calls.
- No `eval()` or `exec()`.
- All file paths validated via `bootstrap/cli/security.py:validate_path()`.
- All URLs validated via `bootstrap/cli/security.py:validate_url()`.
- Structured output via `bootstrap/cli/utils.py:emit()`.

## Security

- Never hardcode secrets or API keys.
- Never log secret values.
- Validate all user inputs (paths, URLs, package names).
- Run `python bootstrap/cli/bs_cli.py debug secrets-scan` before commits.

## Testing

- Run quick verification: `python bootstrap/cli/bs_cli.py smoketest --level quick`
- Check prerequisites: `python bootstrap/cli/bs_cli.py prereqs`
- CLI emits JSON by default (`--format json`), human output via `--format human`.

## File Organization

```
bootstrap/          — Templates and CLI toolkit
bootstrap/cli/      — Python CLI tools
.windsurf/rules/    — Windsurf rule files
.windsurf/skills/   — Skill definitions
.windsurf/workflows/— Workflow definitions
.github/            — GitHub Copilot instructions
```
