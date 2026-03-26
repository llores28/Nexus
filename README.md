# Nexus - Intelligent Project Operating System

Nexus creates a complete, AI-powered project operating system that automatically optimizes development workflows, agent behaviors, and model selection based on task complexity.

## What Nexus Does

Nexus transforms any repository into an intelligent development environment by:

### 🧠 Intelligent AI Agent Orchestration
- **Context-aware rules** that activate based on what you're working on
- **Reusable skills** for common development tasks (debug, research, testing)
- **Automated workflows** triggered by slash commands
- **Cross-IDE compatibility** (Windsurf, VS Code Copilot, Claude, Cursor)

### ⚡ Automatic Model Selection
- **Task complexity assessment** → optimal AI model recommendation
- **Cost optimization** through intelligent escalation (free models first)
- **Context caching** maximization by sticking to one model per session
- **5-tier pricing strategy** from Free (SWE-1.5) to Ultra Premium (Claude Opus)

### 🔒 Security-First Development
- **Input validation** and path sanitization
- **Secret detection** and audit trails
- **No destructive operations** by default
- **Evidence-based changes** with source citations

### 🛠️ Complete Development Toolkit
- **CLI tools** for environment setup, debugging, and validation
- **Health monitoring** with 4-tier system validation (components, security, usage, recommendations)
- **Container management** with Docker Desktop integration
- **Automated smoke tests** for project health verification
- **Documentation generation** (Developer Guide, Runbook, Handoff)

## Problems Nexus Solves

| Problem | Nexus Solution |
|---|---|
| **Inconsistent AI behavior** across different IDEs and projects | Unified agent instructions that work across Windsurf, VS Code, Claude, and Cursor |
| **Wasting AI credits** on inappropriate models | Automatic model selection chooses the cheapest capable model for each task |
| **Poor project context** leading to irrelevant AI suggestions | Project-specific rules and agents that understand your codebase |
| **Manual environment setup** and configuration drift | Automated environment validation and container-based development |
| **Security risks** from AI-generated code | Built-in security scanning and safe coding practices |
| **Lost knowledge** when team members leave | Comprehensive documentation and handoff automation |
| **Inconsistent development practices** | Standardized workflows and skills that enforce best practices |

## Quick Start

### 1. Bootstrap Your Project
```bash
# In Windsurf, run the wizard
/bootstrap-wizard

# Or choose directly:
/bootstrap-fast      # For daily/speed-focused development
/bootstrap-team      # For balanced team collaboration
/bootstrap-enterprise # For strict compliance and governance
```

### 2. Install CLI Toolkit
```bash
cd bootstrap/cli
pip install -r requirements.txt

# Check prerequisites
python bs_cli.py prereqs

# Run smoke tests
python bs_cli.py smoketest
```

### 3. Use Nexus Workflows
```bash
# Common slash commands
/nexus-health       # Full health check (100/100 score)
/smoketest          # Verify project health
/debug              # Investigate issues
/research           # Research dependencies/docs
/local-env up       # Start development containers
/create-tool <name> # Scaffold new CLI tools
```

### 4. Monitor System Health
```bash
# Health monitoring commands
python bootstrap/cli/bs_cli.py health check        # Full 4-tier health check
python bootstrap/cli/bs_cli.py health components     # Component inventory
python bootstrap/cli/bs_cli.py health security       # Security validation
python bootstrap/cli/bs_cli.py health usage          # CLI usage analytics
python bootstrap/cli/bs_cli.py health report         # Full report + recommendations
```

## Architecture

```
Nexus/
├── bootstrap/           # Bootstrap templates and model selection
│   ├── 1Fast-ws-Bootstrap.md
│   ├── 2Team-ws-Bootstrap.md
│   ├── 3Enterprise-ws-Bootstrap.md
│   ├── model-selection-reference.md
│   └── cli/             # Python CLI toolkit
├── .windsurf/
│   ├── rules/           # Project-specific AI rules
│   ├── skills/          # Reusable AI skills
│   └── workflows/       # Slash-command workflows
├── AGENTS.md            # Cross-IDE AI instructions
└── docs/                # Generated project documentation
```

## Model Selection Strategy

Nexus automatically selects AI models based on task complexity:

| Complexity | Examples | Recommended Model | Cost |
|---|---|---|---|
| **Simple** | Typos, formatting, boilerplate | SWE-1.5 | Free |
| **Moderate** | Multi-file edits, unit tests | GPT-5 Low | 0.5x |
| **Complex** | Refactoring, API integration | GPT-5 Med / Gemini 3.1 Pro | 1x |
| **Expert** | Architecture, security audit | Claude Sonnet 4.6 / GPT-5 High | 2x |
| **Frontier** | Threat modeling, novel design | Claude Opus 4.6 | 2-3x |

**Escalation Pattern**: Always start with SWE-1.5 (free), escalate only if output quality is insufficient.

## Cross-IDE Support

Nexus works seamlessly across multiple AI-powered IDEs:

- **Windsurf** (primary): Full feature support with rules, skills, and workflows
- **VS Code Copilot**: Project context and coding standards
- **Claude Code**: Project constraints and commands
- **Cursor IDE**: Project context and development guidelines

## Security & Compliance

- ✅ **No secrets in output** - All sensitive data is filtered
- ✅ **Input validation** - Paths and URLs validated before use
- ✅ **Audit trail** - All CLI actions logged to `.cache/bs-cli/audit.jsonl`
- ✅ **Secret scanning** - Automatic detection of leaked credentials
- ✅ **Health validation** - System verifies security posture and configuration
- ✅ **Safe defaults** - No destructive operations without explicit approval

## Token Efficiency

Nexus provides infrastructure for token optimization:

- **Model decision triggers** - Rules load only when relevant
- **Fast Context search** - Find information before reading files
- **Batch tool calls** - Execute multiple operations in parallel
- **Context caching** - Stick to one model per session
- **On-demand references** - Large docs excluded from indexing via `.codeiumignore`

*Note: Actual token usage and model selection happen in Windsurf internals and cannot be directly measured from the CLI.*

## Enterprise Features

For teams requiring additional governance:

- **Change management** and approval workflows
- **Compliance traceability** matrices
- **Security model** documentation
- **Threat modeling** templates
- **Handoff automation** for team transitions

## Contributing

Nexus is designed to be extensible:

1. **Add skills** in `.windsurf/skills/` for new capabilities
2. **Create workflows** in `.windsurf/workflows/` for new processes
3. **Extend CLI tools** in `bootstrap/cli/tools/` for new utilities
4. **Update model selection** in `bootstrap/model-selection-reference.md`

## License

MIT License - see LICENSE file for details.

---

**Nexus**: Where intelligent development meets operational excellence.
