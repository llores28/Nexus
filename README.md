# Nexus — Intelligent Project Operating System

Nexus generates project-specific AI dev configurations across IDEs from a single source of truth. It auto-detects your stack, then projects a typed `.nexus/profile.json` onto **AGENTS.md**, **CLAUDE.md**, **`.cursor/rules/*.mdc`**, and **`.github/copilot-instructions.md`** + per-language instructions — keeping all four IDEs in sync as your codebase evolves.

Drift detection (`nexus doctor`) flags any file whose embedded profile-hash stamp diverges from the current profile, so multi-IDE rule drift — the #1 pain point in 2026 multi-tool teams — never silently piles up.

---

## Getting Started

Run from the directory of the project you want to bootstrap.

### Recommended — clone first (all platforms, most reliable)

```bash
git clone https://github.com/llores28/Nexus.git
cd Nexus
```

Then run the setup script for your platform:

**Windows PowerShell:**
```powershell
.\setup.ps1
```

**macOS / Linux / Git Bash:**
```bash
./setup.sh
```

---

### Windows — one-liner (PowerShell)

> ⚠️ **AMSI / Antivirus notice**: Windows Defender and most AV products block the `irm … | iex`
> pattern on principle — it is the canonical malware delivery cradle. If you see
> `ScriptContainedMaliciousContent`, that is expected behaviour. Use the **save → inspect → run**
> path below instead.

```powershell
# Download to disk, inspect, then run — AMSI does NOT flag local file execution
irm https://raw.githubusercontent.com/llores28/Nexus/main/setup.ps1 -OutFile setup-nexus.ps1
Unblock-File setup-nexus.ps1        # remove Mark-of-the-Web
.\setup-nexus.ps1                   # runs normally; safe to delete after
```

> **Windows users: use PowerShell or Git Bash — not `bash` from a cmd/PowerShell prompt.**
> On Windows, typing `bash` in cmd or PowerShell invokes the WSL shim (`C:\Windows\System32\bash.exe`).
> If no WSL distro is installed you will get:
> `WSL ERROR: execvpe(/bin/bash) failed: No such file or directory`

---

### macOS / Linux / Git Bash (Windows)

```bash
curl -sSL https://raw.githubusercontent.com/llores28/Nexus/main/setup.sh | bash
```

> On Windows, run this inside **Git Bash** (comes with [Git for Windows](https://git-scm.com/download/win)), not cmd or PowerShell.

The script:
1. Creates a project-local `.venv`
2. Installs (or upgrades) Nexus into it
3. Runs `nexus init` — auto-detects your stack and runs a 7-question wizard to pick your tier (Fast / Team / Enterprise)
4. Writes `.nexus/profile.json` and generates IDE files (AGENTS.md, CLAUDE.md, .cursor/rules/, .github/copilot-instructions.md), initializes git + journal hooks, runs a health check

### Verify it worked
```bash
nexus doctor              # all hashes current, all expected files present
nexus journal status      # current project state
```

`nexus doctor` is the v0.2 health authority for rule drift. The legacy `nexus health check` still works (component/security/audit-trail tier) and is fine to run alongside.

### Power-user flags
```bash
nexus init --template enterprise   # skip wizard, force a tier
nexus init --upgrade               # re-run init on an existing project
nexus init --accept-defaults       # auto-confirm all prompts (CI / unattended)
nexus profile detect               # refresh profile from current project state
nexus generate                     # regenerate IDE files from current profile
nexus generate --target cursor     # only refresh one IDE family
nexus doctor --deep                # also re-run stack detection vs stored profile
```

---

## Upgrading from an Older Nexus

For projects that already have older Nexus state (`.nexus/state.json` exists, possibly without `profile.json`).

**1. Update the Nexus CLI itself**

```bash
# if you cloned the repo:
cd /path/to/Nexus && git pull

# if you pip-installed:
pip install -U nexus-bootstrap
```

**2. From inside your project, run the upgrade**

```bash
cd /path/to/your-project
nexus init --upgrade                    # interactive — prompts for hook install + journal refresh
# or
nexus init --upgrade --accept-defaults  # CI / unattended
```

**3. Verify**

```bash
nexus doctor
```

### What the upgrade does

- Reuses the tier from existing `.nexus/state.json` — no wizard.
- Synthesizes `.nexus/profile.json` from auto-detection + the stored tier (one-time migration on first v0.2 run).
- Re-validates / installs git hooks (idempotent).
- Runs all v0.2 generators: `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/00-core.mdc` + per-framework, `.github/copilot-instructions.md` + `.github/instructions/<lang>.instructions.md`.
- Refreshes `state-dashboard.html` and `state-summary.md`.

### What's preserved (won't be clobbered)

- **AGENTS.md / CLAUDE.md content outside the `<!-- nexus:*:begin -->` markers** — your authored sections survive.
- **User-authored rules in `.nexus/profile.json`** with `nexus_managed: false` — preserved across re-detect. Seed (Nexus-managed) rules are replaced wholesale on each detect; user rules are kept by ID.
- **`BOOTSTRAP.md`** — only regenerated if you pass `--refresh`.
- **Journal state, ADRs, daily archives.**

### Recommended pre-flight

```bash
git commit -am "snapshot before nexus upgrade"
nexus init --upgrade
git diff                                # review what changed
nexus doctor                            # confirm all hashes current
```

If you previously had `.cursorrules` (legacy single-file format), `nexus doctor` won't complain — but the file is now superseded by `.cursor/rules/00-core.mdc`. You can delete `.cursorrules` once you've confirmed Cursor picks up the new files.

---

## How It Works

### Profile-driven generation (v0.2)

```
                ┌─────────────────────────┐
                │  .nexus/profile.json    │  ← single source of truth
                │  - tier                 │
                │  - languages, frameworks│
                │  - rules[]              │  ← seed rules + your custom rules
                │  - test_runner, ci, ... │
                └────────────┬────────────┘
                             │
        ┌──────────┬─────────┼─────────┬───────────┐
        ▼          ▼         ▼         ▼           ▼
  AGENTS.md   CLAUDE.md  .cursor/   .github/    .github/
                          rules/    copilot-   instructions/
                          00-core   instructions <lang>.instructions
                          .mdc      .md         .md
                          (+ per-fw)            (per-language, applyTo glob)
```

Each generated file embeds a 12-char `sha256(profile)` stamp:

```html
<!-- nexus: profile=62237f7d2e08 generator=cursor.00-core nexus_version=0.2.0 -->
```

`nexus doctor` reads these stamps in O(1) and reports drift the moment your profile changes or someone hand-edits a managed file.

### Customizing rules

You add your own rules by editing `.nexus/profile.json` and appending to the `rules` array. Set `nexus_managed: false` and they'll be preserved across every re-detect:

```json
{
  "id": "team-no-print",
  "text": "Never use print() in library code; use logging.",
  "severity": "must",
  "applies_to": ["**/*.py"],
  "targets": null,
  "tier_min": "fast",
  "nexus_managed": false
}
```

Then run `nexus generate` to project the new rule onto every IDE.

| Field | Effect |
|---|---|
| `applies_to` | Globs that scope this rule to specific files. Empty = whole repo (lands in `.cursor/rules/00-core.mdc`, `copilot-instructions.md`). With globs → lands in `10-<framework>.mdc` and `<lang>.instructions.md`. |
| `targets` | `null` means emit to all IDEs. Or restrict to e.g. `["cursor", "copilot"]`. |
| `tier_min` | Rule only emits at this tier or higher (`fast`, `team`, `enterprise`). |
| `severity` | `info`, `warn`, or `must`. Annotates the rule in human-facing output. |

---

## CLI Commands

All tools emit structured JSON by default; pass `--format human` for terminal output, `--format yaml` for YAML.

**Entry point**: `python nexus/cli/bs_cli.py <command>` (or just `nexus <command>` after the venv is activated).

Every CLI invocation is audit-logged to `.cache/bs-cli/audit.jsonl`.

| Command | Subcommands | What It Does |
|---|---|---|
| `init` | — | Bootstrap or upgrade a project. `--upgrade` reuses tier; `--template <fast\|team\|enterprise>` skips the wizard; `--accept-defaults` auto-confirms all prompts. |
| **`profile`** | `detect`, `show`, `set` | Manage `.nexus/profile.json`. `detect` re-derives from current project state; `set tier <fast\|team\|enterprise>` switches tier. |
| **`generate`** | — | Regenerate IDE files from the profile. `--target a,b` restricts to specific generators (`agents_md`, `claude`, `cursor`, `copilot`); `--dry-run` previews; `--force` overrides hand-edits to managed blocks. |
| **`doctor`** | — | Drift detection. Verifies every generated file's stamp matches the current profile hash, the CLI version aligns, and all expected files are present. `--deep` re-runs stack detection. |
| `journal` | `status`, `log`, `diff`, `next`, `blocker`, `decision`, `health`, `blame`, `export`, `export-summary`, `setup-hooks`, `init-agents`, `session-start`, `session-end` | Cross-session project state with auto-rolling sessions, daily rotation, drift detection, MADR ADRs, and cross-tool surface. |
| `health` | `check`, `components`, `security`, `usage`, `report` | Legacy 4-tier health monitor (file inventory, security posture, audit trail). |
| `prereqs` | — | Checks prerequisites (Python, Git, Docker, Node, extensions). `--guide` outputs setup instructions. |
| `smoketest` | — | Auto-detects project type (Node/Python/Go), runs deps → lint → typecheck → test. `--level full` adds build + server health check. |
| `debug` | `logs`, `trace`, `deps`, `env`, `ports`, `secrets-scan` | Log scanning, error tracing, dependency audit, env validation, port checking, secret detection. |
| `research` | `docs`, `deps`, `changelog`, `compare` | Search docs, check dependency info, review changelogs, compare packages. |
| `scrape` | `page`, `api`, `links`, `docs` | Web scraping for external docs and APIs. |
| `scaffold` | — | Generates a new CLI tool from template with security framework integration. |
| `local-env` | `init`, `build`, `up`, `down`, `logs`, `status`, `validate` | Docker container management and validation. |
| `supply-chain` | `scan`, `ioc`, `audit`, `advisories` | Detect compromised npm packages and malicious IOCs. |

**Stack**: Python 3.10+, Click 8.1.7, Rich 13.9.4, PyYAML 6.0.2, httpx 0.27.2, beautifulsoup4 4.12.3.

---

## Bootstrap Templates (3 tiers)

Templates that influence which seed rules get composed into your profile and which Cascade prompt scaffold lands in `BOOTSTRAP.md` (the latter is now optional — useful only if you want narrative AI-driven customization beyond what the structured generators emit).

| Template | File | Use Case |
|---|---|---|
| **Fast** | `nexus/1Fast-ws-Bootstrap.md` | Solo/daily development — speed over process |
| **Team** | `nexus/2Team-ws-Bootstrap.md` | Team collaboration — balanced process |
| **Enterprise** | `nexus/3Enterprise-ws-Bootstrap.md` | Compliance/governance — strict controls |

Higher tiers add additional seed rules (e.g. enterprise adds `pr-required`, `adr-for-decisions`, `audit-log`).

Supporting files:
- `nexus/Bootstrap-Project-Intake.md` — project intake questionnaire
- `nexus/PRD-Template.md` — PRD generation template
- `nexus/wizard-reference.md` — wizard logic reference

---

## Cross-IDE Support

Nexus generates these files from `.nexus/profile.json`:

| File | IDE | Mode | Contents |
|---|---|---|---|
| `AGENTS.md` | Linux Foundation cross-tool standard (Cursor, Windsurf, Copilot, Claude, Codex) | upsert | Project context, tier, stack, conventions, journal pointers |
| `CLAUDE.md` | Claude Code | upsert | Stack-specific constraints + journal pointers |
| `.cursor/rules/00-core.mdc` | Cursor | overwrite | Whole-repo rules with `alwaysApply: true` |
| `.cursor/rules/10-<framework>.mdc` | Cursor | overwrite | Per-framework scoped rules with `globs:` |
| `.github/copilot-instructions.md` | VS Code Copilot | overwrite | Repo-wide conventions |
| `.github/instructions/<lang>.instructions.md` | VS Code Copilot | overwrite | Per-language with `applyTo:` frontmatter |

**Mode semantics:**

- **upsert** — preserves user content outside the managed block (`<!-- nexus:<id>:begin --> ... <!-- nexus:<id>:end -->`). Edit freely above/below; the block is regenerated on `nexus generate`.
- **overwrite** — file is fully owned by Nexus. Hand-editing the body triggers a `nexus doctor` warning; re-run `nexus generate` to refresh.

### Optional Cascade Surface (`.windsurf/*`)

The Nexus repo itself ships a Windsurf rule/skill/workflow surface for development inside Windsurf. Bootstrapped projects can opt in by populating these directories — `nexus doctor` treats them as informational and does not penalize their absence. Native Windsurf generators are tracked for v0.3.

---

## Project Journal System (`journal` command)

Persistent cross-session project state tracking — tool-agnostic (works with Cascade, Claude Code, Cursor, or any AI agent).

**How it works:**

| Subcommand | What It Does |
|---|---|
| `status` | Displays current `.nexus/state.md` in the terminal |
| `log "<msg>"` | Appends a one-line event; auto-rolls the session if stale (idle ≥4h, new UTC date, or branch changed). Also writes to `.nexus/journal/YYYY-MM/DD.md` (append-only daily archive) |
| `diff` | Shows files changed since session start (git or mtime fallback) |
| `next` | `add <task>` / `done <idx\|substr>` / `list` / `clear` — non-interactive task queue CRUD |
| `blocker` | `add <text>` / `clear` / `list` — non-interactive blocker CRUD |
| `decision` | `add "<title>"` creates a MADR-minimal ADR at `docs/decisions/NNNN-slug.md`; `list` enumerates existing ADRs |
| `health` | Diagnoses drift: missing/stale/commit-drift/PRD-drift. Pass `refresh` to backfill missing commits and regenerate dashboards |
| `blame <file>` | Cross-references a file across git log, state.done, and daily journal archive |
| `export` | Regenerates `state-summary.md` (AI-optimized) + `state-dashboard.html` (self-contained dark-mode dashboard with git-derived heatmap) |
| `export-summary` | Regenerates only `state-summary.md` (cheap, no HTML) |
| `setup-hooks [--force]` | Installs/upgrades git `post-commit` + `pre-push` hooks (versioned; `--force` overwrites Nexus-installed hooks) |
| `init-agents` | Idempotently installs `AGENTS.md` Nexus journal block + `.cursor/rules/state.mdc` for cross-tool agents |
| `session-start` / `session-end` | **Optional** — sessions auto-roll. Use these only for explicit interactive session lifecycle |

**State files written per project:**

| File | Purpose | AI-readable? |
|---|---|---|
| `.nexus/state.md` | Human + AI ground truth: done, next, blockers, session log | ✅ Indexed by Windsurf, read by Claude Code |
| `.nexus/state-summary.md` | AI-optimized snapshot (≤200 lines) — read this first | ✅ Pointed to by AGENTS.md / CLAUDE.md |
| `.nexus/state.json` | Machine-readable source for dashboard | Excluded from indexing |
| `.nexus/state-dashboard.html` | Static self-contained dashboard | Open in browser |

**Automatic tracking (after one-time setup):**
- **Sessions auto-roll** when stale (idle ≥4h, new UTC date, or branch changed) — `session-start` and `session-end` are optional
- **On every `git commit`**: `post-commit` hook auto-logs the commit message; the journal CLI auto-rolls the session if stale and regenerates `state-summary.md` + `state-dashboard.html`
- **On every `git push`**: `pre-push` hook regenerates the dashboard
- **On `nexus init --upgrade`**: runs `journal health` and offers to backfill any commits not yet in the journal
- **After AI agent edits**: AGENTS.md and CLAUDE.md instruct Cascade / Claude Code / Cursor to call `journal log` after significant non-commit work

**Daily use (all non-interactive, all idempotent):**
```bash
nexus journal status                     # current state
nexus journal next add "<task>"          # queue work
nexus journal blocker add "<text>"       # record a blocker
nexus journal decision add "<title>"     # MADR ADR in docs/decisions/
nexus journal health [refresh]           # check / fix drift vs git + PRD
nexus journal blame <file>               # cross-ref file across journal + git
```

---

## Health Monitoring (`health` command)

Validates Nexus components and project security posture. Distinct from `nexus doctor` (which checks profile-driven file drift).

**4-tier architecture:**

| Tier | What It Checks | Details |
|---|---|---|
| **Components** | `.nexus/profile.json`, cross-IDE files (AGENTS.md, CLAUDE.md, `.cursor/rules/00-core.mdc`, copilot-instructions.md), optional Windsurf surface | File existence, valid frontmatter, size limits (<12KB) |
| **Security** | `.gitignore`, `.codeiumignore`, secrets scan, dependencies | Pattern coverage, secret detection, importability of CLI packages |
| **Usage** | CLI audit trail | Tool usage counts, error rates, duration trends, last activity |
| **Recommendations** | Actionable fixes | Sorted by severity (critical/high/medium/low) with specific commands |

**Health score**: 0–100 weighted composite. `info`-severity items (e.g. "Windsurf surface absent — optional") don't dock the score; `medium`/`high` issues do. Realistic scores for a clean v0.2 project depend on whether `.gitignore` and `.codeiumignore` are present — both are user-owned and Nexus does not generate them.

---

## Supply Chain Security (`supply-chain` command)

Detects compromised npm packages and system-level indicators of compromise (IOCs).

**Subcommands:**
- `scan` — scan `package.json` / lockfiles for known-malicious packages and vulnerable versions
- `ioc` — check system paths and environment for RAT/backdoor IOCs
- `audit` — full audit combining scan + IOC check with remediation guidance
- `advisories` — display current known-malicious package block list

**Known threats in block list:** `axios@1.14.1`, `axios@0.30.4` (RAT via `plain-crypto-js`), `@shadanai/openclaw`, `@qqbrowser/openclaw-qbot`.

---

## Security Framework (`nexus/cli/security.py`)

Built into every CLI tool:

- **Path sanitization** — `validate_path()` prevents directory traversal
- **URL validation** — `validate_url()` with SSRF protection
- **Package name validation** — `validate_package_name()` blocks injection
- **Command safety** — argv-list-only subprocess calls (no `shell=True`)
- **Secret detection** — regex-based scanning for API keys, tokens, passwords (with placeholder filter for `${VAR}` and `your-key-here` patterns)
- **Audit logging** — every CLI invocation logged to `.cache/bs-cli/audit.jsonl` (auto-rotated at 5 MB)

---

## Token Efficiency Infrastructure

Multiple layers reduce unnecessary token consumption:

- **Rule scope** — per-language and per-framework rules emit only to the relevant IDE files (e.g. python rules only land in `.cursor/rules/10-fastapi.mdc`, not in 00-core.mdc)
- **`.codeiumignore`** — excludes large reference files from Windsurf indexing
- **Structured CLI output** — JSON by default for machine consumption, minimizing verbose text
- **`state-summary.md`** — AI-optimized ≤200-line snapshot pointed to by AGENTS.md/CLAUDE.md, so agents read one file instead of the full journal

---

## Quick Start (manual)

If the setup script isn't available or you want to do it by hand.

### 1. Install CLI dependencies
```bash
pip install -e .
```

### 2. Check prerequisites
```bash
python nexus/cli/bs_cli.py prereqs --format human
```

### 3. Bootstrap your project
```bash
cd /path/to/your-project
python /path/to/Nexus/nexus/cli/bs_cli.py init
# or, after activating the .venv:
nexus init
```

### 4. Verify
```bash
nexus doctor               # all generated-file hashes current
nexus journal status        # project state dashboard
```

### 5. Customize
- Edit `.nexus/profile.json` — append rules with `nexus_managed: false`, then `nexus generate`.
- Switch tier: `nexus profile set tier team` (re-derives seed rules; user rules preserved).

---

## Project Structure

```
Nexus/
├── nexus/
│   ├── 1Fast-ws-Bootstrap.md          # Fast bootstrap template
│   ├── 2Team-ws-Bootstrap.md          # Team bootstrap template
│   ├── 3Enterprise-ws-Bootstrap.md    # Enterprise bootstrap template
│   ├── Bootstrap-Project-Intake.md    # Project intake questionnaire
│   ├── PRD-Template.md                # PRD generation template
│   ├── wizard-reference.md            # Wizard logic (excluded from indexing)
│   └── cli/
│       ├── bs_cli.py                  # CLI entry point
│       ├── profile.py                 # Profile dataclass + from_detection
│       ├── profile_seeds.py           # Seed rule library (core, tier, language, framework)
│       ├── security.py                # Security framework
│       ├── utils.py                   # Shared utilities
│       ├── generators/
│       │   ├── __init__.py            # GeneratedFile, run_all, managed-block helpers
│       │   ├── agents_md.py           # AGENTS.md generator
│       │   ├── claude_md.py           # CLAUDE.md generator
│       │   ├── cursor_rules.py        # .cursor/rules/*.mdc generator
│       │   └── copilot.py             # .github/copilot-instructions.md + instructions/
│       └── tools/
│           ├── prereqs.py             # Prerequisite checks
│           ├── smoketest.py           # Smoke test runner
│           ├── debug.py               # Debug investigation
│           ├── research.py            # Dependency research
│           ├── scrape.py              # Web scraping
│           ├── scaffold.py            # Tool scaffolding
│           ├── local_env.py           # Container management
│           ├── health.py              # Health monitoring (4-tier)
│           ├── doctor.py              # Profile drift / version / missing-files check
│           ├── profile_cmd.py         # `nexus profile` subcommand
│           ├── generate_cmd.py        # `nexus generate` subcommand
│           ├── init.py                # `nexus init` (fresh + upgrade)
│           ├── wizard.py              # Tier wizard (with detection preamble)
│           ├── journal.py             # Project journal
│           ├── journal_dashboard.py   # Static HTML dashboard generator
│           └── supply_chain.py        # Supply chain security scanner
├── .nexus/                            # Per-project state (auto-created)
│   ├── profile.json                   # Single source of truth for cross-IDE generation
│   ├── state.md                       # Human + AI readable project state
│   ├── state-summary.md               # AI-optimized ≤200-line snapshot
│   ├── state.json                     # Machine-readable state
│   └── state-dashboard.html           # Generated static dashboard
├── AGENTS.md                          # Cross-tool conventions (managed block + user content)
├── CLAUDE.md                          # Claude Code instructions (managed block + user content)
├── .cursor/rules/
│   ├── 00-core.mdc                    # Cursor whole-repo rules (alwaysApply: true)
│   └── 10-<framework>.mdc             # Per-framework scoped rules (globs:)
├── .github/
│   ├── copilot-instructions.md        # Copilot repo-wide
│   └── instructions/
│       └── <lang>.instructions.md     # Copilot per-language (applyTo:)
├── BOOTSTRAP.md                       # Optional narrative AI prompt (not regenerated by default)
├── docs/decisions/                    # MADR-minimal ADRs (`nexus journal decision add`)
├── .codeiumignore                     # Excludes large files + state JSON from indexing
└── .gitignore                         # Sensitive file exclusions
```

Optional v0.3 surface (intentionally absent from generators today):

```
.windsurf/
├── rules/                             # Activation-triggered Windsurf rules
├── skills/                            # SKILL.md definitions
└── workflows/                         # Slash-command workflows
```

---

## Extending Nexus

- **Add a custom rule**: edit `.nexus/profile.json`, append a rule with `nexus_managed: false`, then run `nexus generate`. It survives every future `profile detect` / `init --upgrade`.
- **Add a CLI tool**: `python nexus/cli/bs_cli.py scaffold <name>` — inherits the security framework. Wire it into `bs_cli.py` manually (auto-registration is on the v0.3 list).
- **Switch tier**: `nexus profile set tier team` — re-derives seed rules; user rules preserved.
- **Track project state**: `nexus journal setup-hooks` is automatic on `init`. After that, every commit auto-logs.
- **Record a decision**: `nexus journal decision add "<title>"` writes a MADR-minimal ADR to `docs/decisions/`.
- **Check freshness**: `nexus doctor` (drift), `nexus journal health` (commit drift).

---

## License

MIT License — see LICENSE file for details.
