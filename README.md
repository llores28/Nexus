# Nexus — Intelligent Project Operating System

Nexus generates provider-neutral project context from a single source of truth. It auto-detects your stack, then projects `.nexus/profile.json` into canonical **AGENTS.md** and **`.agents/skills`**, plus thin native adapters for Claude, Cursor, GitHub Copilot, Devin Review, and VS Code-hosted agents.

Drift detection (`nexus doctor`) validates the install manifest, provider discovery, skill projections, package provenance, and generated stamps so incompatible surfaces cannot silently pass readiness checks.

---

## Getting Started

Keep this self-contained distribution at `<project-root>/nexus`. Run its setup
script either from the project root or from inside that `nexus` directory. When
launched inside `nexus` without an explicit project directory, the installer
targets the containing project root. Nexus-managed tracking and agent surfaces
are always written to that target root, never into the installer directory.

> **Release status:** onboarding is pinned to the immutable `v0.3.0` GitHub
> release. PyPI is not an installation source for this release; local and
> offline installs can pass a verified wheel path with `-Source` / `--source`.

### Recommended — install from the project-local `nexus` folder

**Windows PowerShell:**
```powershell
Get-Content .\nexus\setup.ps1                    # inspect before execution
Unblock-File .\nexus\setup.ps1
.\nexus\setup.ps1 -Template team -AcceptDefaults
```

**macOS / Linux / Git Bash:**
```bash
less nexus/setup.sh                              # inspect before execution
bash nexus/setup.sh --template team --yes
```

The installer creates or reuses `<project-root>/.venv`, installs Nexus
non-editably from `<project-root>/nexus`, previews or applies the requested
changes, and invokes that venv's own executable. `-ProjectDir` / `--project-dir`
remains available and always overrides automatic parent selection.

For an existing Nexus project, run the same command again. The installer detects
the profile, install manifest, managed `AGENTS.md`, legacy state, or legacy
`.windsurf` inputs and selects collision-safe upgrade mode. Add `-DryRun`
(PowerShell) or `--dry-run` (shell) to preview every planned action first; use
`-Unattended` or `--unattended` in IDE terminals and automation.

---

### Windows — one-liner (PowerShell)

> ⚠️ **AMSI / Antivirus notice**: Windows Defender and most AV products block the `irm … | iex`
> pattern on principle — it is the canonical malware delivery cradle. If you see
> `ScriptContainedMaliciousContent`, that is expected behaviour. Use the **save → inspect → run**
> path below instead.

```powershell
# Download to disk, inspect, then run — AMSI does NOT flag local file execution
irm https://raw.githubusercontent.com/llores28/Nexus/v0.3.0/setup.ps1 -OutFile setup-nexus.ps1
Unblock-File setup-nexus.ps1        # remove Mark-of-the-Web
.\setup-nexus.ps1 -ProjectDir . -Template team -AcceptDefaults
```

> **Windows users: use PowerShell or Git Bash — not `bash` from a cmd/PowerShell prompt.**
> On Windows, typing `bash` in cmd or PowerShell invokes the WSL shim (`C:\Windows\System32\bash.exe`).
> If no WSL distro is installed you will get:
> `WSL ERROR: execvpe(/bin/bash) failed: No such file or directory`

---

### macOS / Linux / Git Bash (Windows)

Do not pipe the script into `bash`; the interactive wizard needs standard input.
Download it first using the pinned command above.

> On Windows, run this inside **Git Bash** (comes with [Git for Windows](https://git-scm.com/download/win)), not cmd or PowerShell.

The script:
1. Creates a project-local `.venv`
2. Installs (or upgrades) Nexus into it
3. Runs `nexus init` — auto-detects your stack and runs a 7-question wizard to pick your tier (Fast / Team / Enterprise)
4. Installs canonical `.agents/skills`, Claude's `.claude/skills` projection, a tracked install manifest, provider adapters, journal hooks, and truthful diagnostics

### Verify it worked
```bash
nexus doctor --consumer all --deep   # manifests, skills, adapters, projections, drift
nexus journal status      # current project state
```

`nexus doctor` is the v0.3 health authority for rule drift. The legacy `nexus health check` remains available for component, security, and audit-trail checks.

Consumer verification after onboarding:

- Codex, Devin, Cursor, and Copilot should discover root `AGENTS.md` and
  `.agents/skills` without another Nexus ruleset.
- In Claude Code, approve the `@AGENTS.md` import when prompted. Restart the
  active session if `.claude/skills` was created after that session started.
- In VS Code, run **Chat: Open Customizations** and confirm the current release
  discovers Agent Skills; VS Code is a host and receives no duplicated ruleset.

### Power-user flags
```bash
nexus init --template enterprise   # skip wizard, force a tier
nexus init --upgrade               # re-run init on an existing project
nexus init --upgrade --dry-run     # preview writes, collisions, and migrations
nexus init --consumers codex,claude,cursor
nexus init --template team --yes   # unattended fresh setup requires an explicit tier
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

# if installed with the project installer, rerun the pinned v0.3.0 installer
# with the same -ProjectDir/--project-dir
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

- Reuses the tier from `.nexus/profile.json`, then the install manifest, then legacy state.
- Synthesizes `.nexus/profile.json` from auto-detection and the stored tier.
- Re-validates / installs git hooks (idempotent).
- Synchronizes canonical skills, Claude's native projection, and thin provider adapters without overwriting collisions.
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
nexus init --upgrade --dry-run              # inspect first
git diff                                # review what changed
nexus doctor --consumer all --deep      # confirm discovery and ownership
```

If you previously had `.cursorrules` (legacy single-file format), `nexus doctor`
reports it as a warning. It is superseded by `.cursor/rules/00-core.mdc`; remove
it explicitly only after confirming Cursor discovers the new files.

---

## How It Works

### Profile-driven generation (v0.3)

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
<!-- nexus: profile=62237f7d2e08 generator=cursor.00-core nexus_version=0.3.0 -->
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

Then run `nexus generate`. Shared rules are emitted once into `AGENTS.md`;
provider adapters receive only rules explicitly targeted to that provider.

| Field | Effect |
|---|---|
| `applies_to` | Globs that scope the canonical rule. Provider-specific targeted rules may also produce scoped adapter files. |
| `targets` | `null` means canonical `AGENTS.md` only. Use `["cursor"]`, `["copilot"]`, or `["claude"]` only for a genuine provider delta. |
| `tier_min` | Rule only emits at this tier or higher (`fast`, `team`, `enterprise`). |
| `severity` | `info`, `warn`, or `must`. Annotates the rule in human-facing output. |

---

## CLI Commands

All tools emit structured JSON by default; pass `--format human` for terminal output, `--format yaml` for YAML.

**Entry point**: `python nexus/cli/bs_cli.py <command>` (or just `nexus <command>` after the venv is activated).

Every CLI invocation is audit-logged to `.cache/bs-cli/audit.jsonl`.

| Command | Subcommands | What It Does |
|---|---|---|
| `init` | — | Bootstrap or upgrade a project. Supports `--dry-run`, `--consumers`, tier reuse, collision-safe skills, and `--yes`/`--accept-defaults`. |
| **`profile`** | `detect`, `show`, `set` | Manage `.nexus/profile.json`. `detect` re-derives from current project state; `set tier <fast\|team\|enterprise>` switches tier. |
| **`generate`** | — | Regenerate IDE files from the profile. `--target a,b` restricts to specific generators (`agents_md`, `claude`, `cursor`, `copilot`); `--dry-run` previews; `--force` overrides hand-edits to managed blocks. |
| **`doctor`** | — | Authoritative readiness check for package provenance, install manifest, skills, Claude projection, provider adapters, ignores, journal, and stack drift. Supports `--consumer` and `--deep`. |
| `journal` | `status`, `log`, `diff`, `next`, `blocker`, `decision`, `health`, `blame`, `export`, `export-summary`, `setup-hooks`, `init-agents`, `session-start`, `session-end` | Cross-session project state with auto-rolling sessions, daily rotation, drift detection, MADR ADRs, and cross-tool surface. |
| `health` | `check`, `components`, `security`, `usage`, `report` | Legacy 4-tier health monitor (file inventory, security posture, audit trail). |
| `prereqs` | — | Checks prerequisites (Python, Git, Docker, Node, extensions). `--guide` outputs setup instructions. |
| `smoketest` | — | Auto-detects project type and runs non-mutating environment checks, lint, typecheck, and tests. Python dependency checks use the project `.venv`; `--isolated-install` verifies a wheel in a temporary venv. |
| `debug` | `logs`, `trace`, `deps`, `env`, `ports`, `secrets-scan` | Log scanning, error tracing, dependency audit, env validation, port checking, secret detection. |
| `research` | `docs`, `deps`, `changelog`, `compare` | Search docs, check dependency info, review changelogs, compare packages. |
| `scrape` | `page`, `api`, `links`, `docs` | Web scraping for external docs and APIs. |
| `scaffold` | — | Generates a project-owned CLI at `tools/nexus/<name>.py`; supports `--project-dir` and preserves collisions. |
| `local-env` | `init`, `build`, `up`, `down`, `logs`, `status`, `validate` | Docker container management and validation. |
| `supply-chain` | `scan`, `ioc`, `audit`, `advisories` | Detect bundled npm compromise indicators and system IOCs, with explicit coverage status. |
| `context` | `audit`, `map`, `mask`, `ignores`, `route` | Inspect, bound, compress, scope, and route coding-agent context. |

**Stack**: Python 3.10+, Click 8.1.7, Rich 13.9.4, PyYAML 6.0.2, httpx 0.27.2, beautifulsoup4 4.12.3.

---

## Bootstrap Templates (3 tiers)

Templates influence which seed rules are composed into the profile and which provider-neutral prompt scaffold lands in `BOOTSTRAP.md`.

| Template | File | Use Case |
|---|---|---|
| **Fast** | `nexus/1Fast-Bootstrap.md` | Solo/daily development — speed over process |
| **Team** | `nexus/2Team-Bootstrap.md` | Team collaboration — balanced process |
| **Enterprise** | `nexus/3Enterprise-Bootstrap.md` | Compliance/governance — strict controls |

Higher tiers add additional seed rules (e.g. enterprise adds `pr-required`, `adr-for-decisions`, `audit-log`).

Repository-authoring references (not installed as loose target-project files):

- `nexus/Bootstrap-Project-Intake.md` — project intake questionnaire
- `nexus/PRD-Template.md` — PRD generation template
- `nexus/wizard-reference.md` — wizard logic reference

The packaged `bootstrap-prd` skill carries its own
`references/PROJECT-INTAKE.md` and `assets/PRD-TEMPLATE.md`, so it remains
self-contained after wheel installation.

---

## Cross-Agent and IDE Support

Nexus generates these files from `.nexus/profile.json`:

| File | Consumer | Mode | Contents |
|---|---|---|---|
| `AGENTS.md` | OpenAI Codex, Devin, Cursor, Copilot | upsert | Canonical shared constraints, stack, and journal pointers |
| `.agents/skills/*/SKILL.md` | Codex, Devin, Cursor, Copilot/VS Code | manifest-owned files | Canonical reusable workflows loaded just in time |
| `CLAUDE.md` | Claude Code and its VS Code extension | upsert | `@AGENTS.md` import plus Claude-only deltas |
| `.claude/skills/*/SKILL.md` | Claude Code | synchronized projection | Byte-equivalent projection of canonical project skills |
| `.cursor/rules/*.mdc` | Cursor | overwrite | Cursor-only scoped deltas |
| `.cursorignore` | Cursor | managed block | Context-heavy generated/runtime exclusions |
| `.github/copilot-instructions.md` | GitHub Copilot and VS Code | upsert | Thin adapter plus Copilot-only deltas |
| `.github/instructions/*.instructions.md` | GitHub Copilot | overwrite | Copilot-only path-scoped deltas |
| `REVIEW.md` | Devin Review, optional | user-owned | Review-only guidance not duplicated from `AGENTS.md` |

**Mode semantics:**

- **upsert** — preserves user content outside the managed block (`<!-- nexus:<id>:begin --> ... <!-- nexus:<id>:end -->`). Edit freely above/below; the block is regenerated on `nexus generate`.
- **overwrite** — file is fully owned by Nexus. Hand-editing the body triggers a `nexus doctor` warning; re-run `nexus generate` to refresh.

### Legacy migration surface

`nexus init --upgrade --dry-run` previews legacy `.windsurf/rules`,
`.windsurf/skills`, and `.windsurf/workflows` inputs. Skills and reusable
workflows migrate collision-safely; rules remain manual AGENTS/profile review
candidates. Nexus never changes the legacy source files.

---

## Project Journal System (`journal` command)

Persistent cross-session state tracking for Codex, Devin, Claude, Cursor, Copilot, and other agents.

**How it works:**

| Subcommand | What It Does |
|---|---|
| `status` | Displays current `.nexus/state.md` in the terminal |
| `log "<msg>"` | Appends a one-line event; auto-rolls the session if stale (idle ≥4h, new UTC date, or branch changed). Also writes to `.nexus/journal/YYYY-MM/DD.md` (append-only daily archive) |
| `diff` | Shows files changed since session start (git or mtime fallback) |
| `next` | `add <task>` / `done <idx\|substr>` / `list` / `clear` — non-interactive task queue CRUD |
| `blocker` | `add <text>` / `clear` / `list` — non-interactive blocker CRUD |
| `intent` | `set "<goal>"` / `show` / `clear` — anchors the active objective |
| `decision` | `add "<title>"` creates an ADR; `note "<text>"` records a compact decision |
| `handoff` | Emits the stable four-field state compaction payload |
| `health` | Diagnoses drift: missing/stale/commit-drift/PRD-drift. Pass `refresh` to backfill missing commits and regenerate dashboards |
| `blame <file>` | Cross-references a file across git log, state.done, and daily journal archive |
| `export` | Regenerates `state-summary.md` (AI-optimized) + `state-dashboard.html` (self-contained dark-mode dashboard with git-derived heatmap) |
| `export-summary` | Regenerates only `state-summary.md` (cheap, no HTML) |
| `setup-hooks [--force]` | Installs/upgrades git `post-commit` + `pre-push` hooks (versioned; `--force` overwrites Nexus-installed hooks) |
| `init-agents` | Idempotently installs the compact journal pointer in canonical `AGENTS.md` |
| `session-start` / `session-end` | **Optional** — sessions auto-roll. Use these only for explicit interactive session lifecycle |

**State files written per project:**

| File | Purpose | AI-readable? |
|---|---|---|
| `.nexus/state.md` | Full human and AI journal | Read on demand |
| `.nexus/state-summary.md` | Four-field snapshot (≤80 lines) | Read first |
| `.nexus/state.json` | Machine-readable source for dashboard | Excluded from indexing |
| `.nexus/state-dashboard.html` | Static self-contained dashboard | Open in browser |

**Automatic tracking (after one-time setup):**
- **Sessions auto-roll** when stale (idle ≥4h, new UTC date, or branch changed) — `session-start` and `session-end` are optional
- **On every `git commit`**: `post-commit` hook auto-logs the commit message; the journal CLI auto-rolls the session if stale and regenerates `state-summary.md` + `state-dashboard.html`
- **On every `git push`**: `pre-push` hook regenerates the dashboard
- **On `nexus init --upgrade`**: runs `journal health` and offers to backfill any commits not yet in the journal
- **After significant non-commit work**: agents call `journal log`; commits remain hook-managed

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
| **Components** | `.nexus/profile.json`, canonical `AGENTS.md`, `.agents/skills`, and thin provider adapters | File existence, valid frontmatter, size limits |
| **Security** | `.gitignore`, secrets scan, dependencies, and optional legacy `.codeiumignore` input | Pattern coverage, secret detection, dependency importability, and explicit scan coverage |
| **Usage** | CLI audit trail | Tool usage counts, error rates, duration trends, last activity |
| **Recommendations** | Actionable fixes | Sorted by severity (critical/high/medium/low) with specific commands |

**Health score**: 0–100 weighted composite. Informational legacy-migration notes do not reduce the score; medium/high issues do.

---

## Supply Chain Security (`supply-chain` command)

Checks a bundled, offline npm compromise registry and system-level indicators of
compromise (IOCs). It inventories Python manifests but does not claim Python
advisory coverage; Python-only projects return a coverage warning and should use
Dependabot or an independently installed Python advisory scanner. A project
with no supported lockfile or scan target returns INFO/WARN, never a false clean
PASS.

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

- **Canonical instructions** — shared rules live once in `AGENTS.md`; adapters contain only provider deltas.
- **Just-in-time skills** — `.agents/skills` metadata supports discovery without preloading every workflow.
- **Repository maps** — `nexus context map` emits a token-bounded inventory or optional Repomix result.
- **Observation masking** — `nexus context mask` keeps failure signatures and redacts secrets without retaining full logs.
- **Scoped ignores** — `nexus context ignores` manages idempotent tool-specific blocks without excluding source, tests, manifests, or lockfiles.
- **Structured state** — `state-summary.md` and `journal handoff` use the four-field compact schema.
- **Capability routing** — `nexus context route` advises by task risk without volatile provider pricing.

See [`docs/context-efficiency-report.md`](docs/context-efficiency-report.md) for the measured v0.3 before/after instruction footprint.

---

## Quick Start (manual)

If the setup script isn't available or you want to do it by hand.

### 1. Install CLI dependencies
```bash
python -m pip install ./nexus
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
project-root/
├── .git/                              # host project's source-control metadata
├── .gitignore                         # host project's tracked ignore policy
├── nexus/
│   ├── README.md                     # installer and CLI documentation
│   ├── pyproject.toml                # self-contained package metadata
│   ├── setup.ps1 / setup.sh          # project-local installers
│   ├── 1Fast-Bootstrap.md            # Fast bootstrap template
│   ├── 2Team-Bootstrap.md            # Team bootstrap template
│   ├── 3Enterprise-Bootstrap.md      # Enterprise bootstrap template
│   ├── Bootstrap-Project-Intake.md    # Project intake questionnaire
│   ├── PRD-Template.md                # PRD generation template
│   ├── wizard-reference.md            # Source-only wizard reference
│   ├── bundles/default/skills/        # Wheel-shipped Agent Skill bundle
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
├── .nexus/                            # profile, manifest, journal, compact state
├── .agents/skills/                    # canonical installed Agent Skills
├── AGENTS.md                          # canonical shared project instructions
├── CLAUDE.md / .claude/skills/        # optional Claude projection
├── .cursor/rules/                     # optional Cursor-only deltas
└── .github/*                          # host CI plus optional Copilot deltas
```

The `nexus/` directory is immutable installer/package input. Provider adapters,
canonical project skills, profiles, manifests, journal state, the project
virtual environment, and Git hooks belong to the containing project root.
Installation tests enforce this boundary and reject duplicate nested package
trees such as `nexus/nexus/`.

Legacy inputs may exist in a user's project during an upgrade, but Nexus does
not ship, generate, modify, or track them:

```
.windsurf/                             # Read-only legacy migration inputs
├── skills/                            # SKILL.md definitions
└── workflows/                         # Slash-command workflows
.codeiumignore                         # Optional legacy ignore input
```

### Source and release boundary

- Git tracks implementation, tests, documentation, contributor guidance, and
  source-repository CI. It does not track generated target-project surfaces.
- Wheels contain Python packages, four runtime bootstrap templates, and every
  skill `SKILL.md`, script, reference, and asset required after installation.
- Generated Agent Skills, provider adapters, profiles, manifests, runtime
  journal state, dashboards, caches, build outputs, local IDE settings,
  workspaces, and legacy Windsurf/Codeium inputs are ignored in this checkout.
- Ignore rules affect untracked files only. The repository tests also inspect
  the Git index so generated target surfaces cannot hide behind `.gitignore`.

---

## Extending Nexus

- **Add a custom rule**: edit `.nexus/profile.json`, append a rule with `nexus_managed: false`, then run `nexus generate`. It survives every future `profile detect` / `init --upgrade`.
- **Add a project tool**: `nexus scaffold <name> --project-dir .` — writes a collision-safe `tools/nexus/<name>.py` with the security framework imports and a runnable Click entry point.
- **Switch tier**: `nexus profile set tier team` — re-derives seed rules; user rules preserved.
- **Track project state**: `nexus journal setup-hooks` is automatic on `init`. After that, every commit auto-logs.
- **Record a decision**: `nexus journal decision add "<title>"` writes a MADR-minimal ADR to `docs/decisions/`.
- **Check freshness**: `nexus doctor` (drift), `nexus journal health` (commit drift).

---

## License

MIT License — see LICENSE file for details.
