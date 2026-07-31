# Nexus CLI Toolkit

Nexus is a provider-neutral project-local CLI for OpenAI Codex, Devin, Claude,
Cursor, GitHub Copilot, and agent extensions hosted by VS Code.

## Onboarding

Use the repository's pinned `v0.3.0` setup script. Download and inspect the
script before running it; do not pipe it into a shell. The installer creates
`<project>/.venv`, installs Nexus there, and invokes that environment's
`nexus` executable.

The tag-based commands are release instructions: until the immutable `v0.3.0`
tag is published, use a locally built wheel through `-Source` / `--source`.

For local or offline validation, both installers accept an explicit package
source:

```powershell
.\setup.ps1 -ProjectDir C:\path\to\project -Source C:\path\to\nexus_bootstrap-0.3.0-py3-none-any.whl -Template team -AcceptDefaults
```

```bash
./setup.sh --project-dir /path/to/project --source /path/to/nexus_bootstrap-0.3.0-py3-none-any.whl --template team --yes
```

PyPI installation is intentionally undocumented until the published package is
independently verified.

## Core commands

| Command | Purpose |
|---|---|
| `nexus init --dry-run` | Preview onboarding, upgrade, collisions, and legacy migration |
| `nexus init --upgrade --yes` | Apply an unattended deterministic upgrade |
| `nexus doctor --consumer all --deep` | Authoritative readiness and ownership check |
| `nexus context audit` | Effective context, duplication, ignore, and observation audit |
| `nexus context map [QUERY]` | Bounded repository inventory or optional Repomix map |
| `nexus context mask` | Deterministic redacted test, lint, or build digest |
| `nexus context ignores` | Audit or apply tool-specific ignore blocks |
| `nexus context route` | Provider-neutral capability recommendation |
| `nexus smoketest --isolated-install` | Test and verify the built wheel in a temporary venv |
| `nexus journal handoff` | Compact four-field cross-agent handoff |
| `nexus health check` | Legacy component and security inventory |

JSON is the default for machine-oriented commands; use `--format human` when
available. Commands use subprocess argument lists and never `shell=True`.

## Installed project surfaces

- `AGENTS.md` is the canonical shared instruction file.
- `.agents/skills/*/SKILL.md` is the canonical editable workflow surface.
- `.claude/skills` is a Nexus-owned byte-equivalent Claude projection.
- `CLAUDE.md`, `.cursor/rules`, `.github/*`, and optional `REVIEW.md` contain
  consumer-specific deltas only.
- `.nexus/install-manifest.json` records ownership and hashes for safe upgrades.

Run the tests with `python -m pytest tests/`.
