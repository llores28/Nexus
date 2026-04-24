# Nexus — Intelligent Project Operating System

Nexus is a reusable bootstrap toolkit that generates project-specific AI-powered operating systems for any repository. It produces rules, agents, skills, workflows, and documentation that make AI assistants work smarter across Windsurf, VS Code Copilot, Claude Code, and Cursor.

---

## Getting Started (one command)

Run from the directory of the project you want to bootstrap.

### Bash / Git Bash
```bash
curl -sSL https://raw.githubusercontent.com/llores28/Nexus/main/setup.sh | bash
```

### PowerShell
```powershell
irm https://raw.githubusercontent.com/llores28/Nexus/main/setup.ps1 | iex
```

### Or clone first
```bash
git clone https://github.com/llores28/Nexus.git && cd Nexus && ./setup.sh
```

The script:
1. Creates a project-local `.venv`
2. Installs (or upgrades) Nexus into it
3. Runs `nexus init` — a guided wizard recommends the right tier (Fast / Team / Enterprise) based on 7 questions about your project
4. Drops `BOOTSTRAP.md` (your AI prompt), initializes git + journal hooks, runs a health check

Re-run the same command anytime to upgrade — `.venv` and existing tier choice are auto-detected.

### Verify it worked
```bash
nexus health check       # should report 100/100
nexus journal status      # shows the project state dashboard
```

### Power-user flags
```bash
nexus init --template enterprise   # skip wizard, force a tier
nexus init --upgrade               # re-run init on an existing project
```

---

## What's In the Box

### Bootstrap Templates (3 tiers)
Prompt templates that generate a complete Nexus operating system for your project:

| Template | File | Use Case |
|---|---|---|
| **Fast** | `nexus/1Fast-ws-Bootstrap.md` | Solo/daily development — speed over process |
| **Team** | `nexus/2Team-ws-Bootstrap.md` | Team collaboration — balanced process |
| **Enterprise** | `nexus/3Enterprise-ws-Bootstrap.md` | Compliance/governance — strict controls |

Each template generates: rules, agents, skills, workflows, cross-IDE files, and documentation. A `/bootstrap-wizard` workflow guides template selection.

Supporting files:
- `nexus/Bootstrap-Project-Intake.md` — project intake questionnaire
- `nexus/PRD-Template.md` — PRD generation template
- `nexus/wizard-reference.md` — wizard logic reference

### Rules System (`.windsurf/rules/`)
Markdown files with YAML frontmatter that control AI behavior. Each rule has an activation trigger:

| Trigger | Behavior | Example |
|---|---|---|
| `always_on` | Loaded every conversation | `00-token-efficiency.md` — quota conservation |
| `model_decision` | AI decides when relevant | Security rules, testing rules |
| `glob` | Loaded when matching files are touched | Component-specific rules |

**Current rules**: 2
- `00-token-efficiency.md` — always-on, token-saving discipline and quota conservation
- `01-project-state.md` — always-on, read `.nexus/state.md` before edits to prevent regressions

Bootstrapped projects generate 4–8 additional rules depending on template tier.

### Skills System (`.windsurf/skills/`)
Reusable skill definitions that Cascade invokes when tasks match. Each skill has a `SKILL.md` with YAML frontmatter (`name`, `description`) and step-by-step instructions.

**8 skills installed:**

| Skill | Purpose |
|---|---|
| `prereqs-check` | Check and guide setup for prerequisites (Docker, extensions, Python, Git, Node) |
| `smoketest` | Run tiered smoke tests to verify project health |
| `debug-investigate` | Systematic debugging using CLI tools |
| `research-investigate` | Research dependencies, docs, and APIs |
| `webscrape` | Fetch and extract content from external URLs |
| `create-cli-tool` | Scaffold a new CLI tool from template |
| `local-env` | Local container validation via Docker Desktop |
| `nexus-health` | Validate all Nexus components work cohesively |

### Workflows System (`.windsurf/workflows/`)
Slash-command workflows that execute multi-step processes. Each workflow is a markdown file with a `description` in YAML frontmatter.

**12 workflows installed:**

| Slash Command | Workflow | Purpose |
|---|---|---|
| `/bootstrap-wizard` | `bootstrap-wizard.md` | Guided template selection |
| `/bootstrap-prd` | `bootstrap-prd.md` | Generate project PRD |
| `/nexus-health` | `nexus-health.md` | Run full health check |
| `/smoketest` | `smoketest.md` | Project health verification |
| `/debug-investigate` | `debug-investigate.md` | Guided debugging session |
| `/research` | `research.md` | Structured research session |
| `/scrape-docs` | `scrape-docs.md` | Fetch external documentation |
| `/local-env` | `local-env.md` | Container validation |
| `/create-tool` | `create-tool.md` | Scaffold new CLI tool |
| `/prereqs-check` | `prereqs-check.md` | Check prerequisites |
| `/migrate-toolkit` | `migrate-toolkit.md` | Migrate existing project to Nexus |
| `/session-handoff` | `session-handoff.md` | Close session, capture changes, export dashboard |

### CLI Toolkit (`nexus/cli/`)
Python command-line tools that provide automation for development tasks. All tools emit structured JSON by default, with `--format human` for terminal output and `--format yaml` for YAML.

**Stack**: Python 3.10+, Click 8.1.7, Rich 13.9.4, PyYAML 6.0.2, httpx 0.27.2, beautifulsoup4 4.12.3

**Entry point**: `python nexus/cli/bs_cli.py <command>`

Every CLI invocation is audit-logged to `.cache/bs-cli/audit.jsonl` via the security framework.

#### Commands

| Command | Subcommands | What It Does |
|---|---|---|
| `prereqs` | — | Checks prerequisites (Python, Git, Docker, Node, extensions). `--guide` outputs setup instructions. |
| `smoketest` | — | Auto-detects project type (Node/Python/Go), runs deps → lint → typecheck → test. `--level full` adds build + server health check. |
| `debug` | `logs`, `trace`, `deps`, `env`, `ports`, `secrets-scan` | Log scanning, error tracing, dependency audit, env var validation, port checking, secret detection. |
| `research` | `docs`, `deps`, `changelog`, `compare` | Search documentation, check dependency info, review changelogs, compare packages. |
| `scrape` | `page`, `api`, `links`, `docs` | Web scraping for external docs, APIs, and link extraction. |
| `scaffold` | — | Generates a new CLI tool from template with security framework integration. |
| `local-env` | `init`, `build`, `up`, `down`, `logs`, `status`, `validate` | Docker container management and validation. |
| `health` | `check`, `components`, `security`, `usage`, `report` | 4-tier Nexus health monitoring (see below). |
| `journal` | `session-start`, `session-end`, `log`, `status`, `diff`, `export`, `setup-hooks` | Cross-session project state tracking, git diff detection, HTML dashboard export, and git hook installation. |
| `supply-chain` | `scan`, `ioc`, `audit`, `advisories` | Detect compromised npm packages (axios backdoor), scan for malicious IOCs, and review security advisories. |

### Project Journal System (`journal` command)
Persistent cross-session project state tracking — tool-agnostic (works with Cascade, Claude Code, Cursor, or any AI agent).

**How it works:**

| Subcommand | What It Does |
|---|---|
| `session-start` | Stamps a new session, shows last state summary, offers `git init` if no repo found |
| `session-end` | Auto-detects changed files (git diff or mtime fallback), prompts for summary + next tasks |
| `log "<msg>"` | Appends a one-line event — Cascade calls this automatically after significant changes |
| `status` | Displays current `.nexus/state.md` in the terminal |
| `diff` | Shows files changed since session start |
| `export` | Generates `.nexus/state-dashboard.html` — self-contained dark-mode HTML dashboard |
| `setup-hooks` | Installs git `post-commit` (auto-log) + `pre-push` (auto-export) hooks |

**State files written per project:**

| File | Purpose | AI-readable? |
|---|---|---|
| `.nexus/state.md` | Human + AI ground truth: done, next, blockers, session log | ✅ Indexed by Windsurf, read by Claude Code |
| `.nexus/state.json` | Machine-readable source for dashboard | Excluded from indexing |
| `.nexus/state-dashboard.html` | Static self-contained dashboard | Open in browser |

**Automatic tracking (after one-time setup):**
- **On workspace open**: `.vscode/tasks.json` runs `session-start` silently via `runOn: folderOpen`
- **On every `git commit`**: `post-commit` hook auto-logs the commit message to `.nexus/state.md`
- **On every `git push`**: `pre-push` hook regenerates the dashboard
- **After Cascade edits**: `01-project-state.md` rule instructs Cascade to call `journal log` after significant changes

**One-time setup:**
```bash
python nexus/cli/bs_cli.py journal session-start --project-dir .
python nexus/cli/bs_cli.py journal setup-hooks --project-dir .
```

### Health Monitoring System (`health` command)
Validates that all Nexus components are properly configured and working together.

**4-tier architecture:**

| Tier | What It Checks | Details |
|---|---|---|
| **Components** | Rules, skills, workflows, cross-IDE files, templates | File existence, valid frontmatter, size limits (<12KB), activation triggers |
| **Security** | .gitignore, .codeiumignore, secrets, dependencies | Pattern coverage, secret detection, importability of CLI packages |
| **Usage** | CLI audit trail | Tool usage counts, error rates, duration trends, last activity |
| **Recommendations** | Actionable fixes | Sorted by severity (critical/high/medium/low) with specific commands |

**Health score**: 0–100 weighted composite. Target: >80 = healthy configuration.

### Cross-IDE Support
Nexus generates configuration files for 4 AI-powered IDEs:

| File | IDE | Contents |
|---|---|---|
| `AGENTS.md` | Windsurf + VS Code Copilot | Project overview, constraints, commands, model cost reference, cross-agent state contract |
| `.windsurf/rules/` | Windsurf | Activation-triggered behavioral rules |
| `.github/copilot-instructions.md` | VS Code Copilot | Project context, coding standards, commands |
| `CLAUDE.md` | Claude Code | Project constraints and commands |
| `.cursorrules` | Cursor | Project context and development guidelines |
| `.vscode/tasks.json` | VS Code / Windsurf | Auto-run `session-start` on workspace open; manual tasks for handoff, export, hooks |

**Cross-Agent State Contract** (`AGENTS.md`): All AI agents (Cascade, Claude Code, Cursor) are instructed to read `.nexus/state.md` before starting work and to call `journal log` after completing significant changes — ensuring consistent project tracking regardless of which tool is active.

### Supply Chain Security (`supply-chain` command)
Detects compromised npm packages and system-level indicators of compromise (IOCs).

**Subcommands:**
- `scan` — scan `package.json` / lockfiles for known-malicious packages and vulnerable versions
- `ioc` — check system paths and environment for RAT/backdoor IOCs
- `audit` — full audit combining scan + IOC check with remediation guidance
- `advisories` — display current known-malicious package block list

**Known threats in block list:** `axios@1.14.1`, `axios@0.30.4` (RAT via `plain-crypto-js`), `@shadanai/openclaw`, `@qqbrowser/openclaw-qbot`

Triggered automatically by `.windsurf/rules/supply-chain-security.md` (glob on `package.json`, lockfiles).

### Security Framework (`nexus/cli/security.py`)
Built into every CLI tool:

- **Path sanitization** — `validate_path()` prevents directory traversal
- **URL validation** — `validate_url()` with SSRF protection
- **Package name validation** — `validate_package_name()` blocks injection
- **Command safety** — `safe_command_args()` prevents shell injection
- **Secret detection** — regex-based scanning for API keys, tokens, passwords
- **Audit logging** — every CLI invocation logged to `.cache/bs-cli/audit.jsonl`

### Token Efficiency Infrastructure
Multiple layers reduce unnecessary token consumption:

- **Rule activation triggers** — non-critical rules load only when relevant (`model_decision`, `glob`)
- **`.codeiumignore`** — excludes large reference files from Windsurf indexing (e.g. wizard-reference.md)
- **Always-on discipline** — the token-efficiency rule enforces concise responses, batch tool calls, and Fast Context search before file reads
- **Structured CLI output** — JSON by default for machine consumption, minimizing verbose text

**What's measurable**: The health tool validates that token-saving infrastructure exists and is configured correctly.

**What's not measurable**: Actual token counts and savings happen inside Windsurf internals with no API access.

---

## Quick Start

### 1. Install CLI Dependencies
```bash
pip install -r nexus/cli/requirements.txt
```

### 2. Check Prerequisites
```bash
python nexus/cli/bs_cli.py prereqs --format human
```

### 3. Bootstrap Your Project
```bash
# In Windsurf, run the wizard
/bootstrap-wizard

# Or choose a tier directly:
# Fast (solo) | Team (balanced) | Enterprise (governance)
```

### 4. Verify Health
```bash
python nexus/cli/bs_cli.py health check --format human
# Target: 100/100 score
```

### 5. Initialize Project Journal
```bash
python nexus/cli/bs_cli.py journal session-start --project-dir .
python nexus/cli/bs_cli.py journal setup-hooks --project-dir .
```
VS Code/Windsurf will prompt **"Allow automatic tasks?"** — click **Allow** once to enable auto session-start on workspace open.

### 6. Use Workflows
```bash
/nexus-health       # Validate system health
/smoketest          # Verify project health
/debug-investigate  # Investigate issues
/research           # Research dependencies/docs
/local-env          # Container management
/create-tool        # Scaffold new CLI tools
/session-handoff    # Close session, capture changes, export dashboard
```

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
│       ├── bs_cli.py                  # CLI entry point (12 commands)
│       ├── security.py                # Security framework
│       ├── utils.py                   # Shared utilities
│       ├── requirements.txt           # Python dependencies
│       └── tools/
│           ├── prereqs.py             # Prerequisite checks
│           ├── smoketest.py           # Smoke test runner
│           ├── debug.py               # Debug investigation
│           ├── research.py            # Dependency research
│           ├── scrape.py              # Web scraping
│           ├── scaffold.py            # Tool scaffolding
│           ├── local_env.py           # Container management
│           ├── health.py              # Health monitoring (4-tier)
│           ├── journal.py             # Project journal (session tracking, git diff, hooks)
│           ├── journal_dashboard.py   # Static HTML dashboard generator
│           └── supply_chain.py        # Supply chain security scanner
├── .nexus/                            # Per-project state (auto-created)
│   ├── state.md                       # Human + AI readable project state
│   ├── state.json                     # Machine-readable state
│   └── state-dashboard.html           # Generated static dashboard
├── .vscode/
│   └── tasks.json                     # Auto session-start + manual journal tasks
├── .windsurf/
│   ├── rules/
│   │   ├── 00-token-efficiency.md     # Always-on: token saving discipline
│   │   ├── 01-project-state.md        # Always-on: read state before edits (regression guard)
│   │   └── supply-chain-security.md   # Glob: npm dependency security checks
│   ├── skills/                        # 8 skill definitions
│   └── workflows/                     # 12 slash-command workflows
├── AGENTS.md                          # Windsurf + Copilot + cross-agent state contract
├── CLAUDE.md                          # Claude Code instructions
├── .cursorrules                       # Cursor IDE instructions
├── .github/copilot-instructions.md    # VS Code Copilot instructions
├── .codeiumignore                     # Excludes large files + state JSON from indexing
└── .gitignore                         # Sensitive file exclusions
```

---

## Extending Nexus

- **Add a skill**: Create `.windsurf/skills/<name>/SKILL.md` with YAML frontmatter
- **Add a workflow**: Create `.windsurf/workflows/<name>.md` with `description` in frontmatter
- **Add a CLI tool**: Run `python nexus/cli/bs_cli.py scaffold <name>` — inherits security framework
- **Add a rule**: Create `.windsurf/rules/<name>.md` with activation trigger in frontmatter
- **Track project state**: Run `journal session-start` + `journal setup-hooks` in any project bootstrapped from Nexus

---

## License

MIT License — see LICENSE file for details.
