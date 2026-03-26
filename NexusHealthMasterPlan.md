# Nexus Health Master Plan

**Version**: 1.0.0
**Date**: March 26, 2026
**Status**: Implementation Ready
**Consolidates**: `Nexus Health Audit and Tracking Plan.md` + `NexusUpgradePlan.md`

---

## Executive Summary

This master plan consolidates and corrects two earlier plans into one actionable, grounded implementation. Both source plans contained valuable ideas but also significant issues — aspirational metrics that can't actually be measured, and references to files that don't exist. This plan strips those away and delivers a working Nexus health monitoring system.

---

## Critical Audit Findings

### Issues Found in "Health Audit and Tracking Plan"

| Proposed Feature | Status | Reason |
|---|---|---|
| Rule activation logging | **NOT FEASIBLE** | Windsurf manages rule loading internally; no CLI hook available |
| Model selection tracking | **NOT FEASIBLE** | Model decisions happen in Windsurf UI, not observable from CLI |
| Token usage monitoring | **NOT FEASIBLE** | Windsurf doesn't expose token counts via any API |
| Memory/context window usage | **NOT FEASIBLE** | Internal to the AI model, no external access |
| Performance metrics (rule loading time) | **NOT FEASIBLE** | Internal to Windsurf engine |
| CLI audit trail analysis | **FEASIBLE** | `.cache/bs-cli/audit.jsonl` already exists and is parseable |
| Component integrity checks | **FEASIBLE** | Can validate all Nexus files exist and are well-formed |

**Conclusion**: 5 of 7 proposed tracking categories require access to Windsurf internals that don't exist. The plan needs to be rebuilt around what we CAN measure.

### Issues Found in "Nexus Upgrade Plan"

| Referenced File | Status | Reason |
|---|---|---|
| `standalone_dashboard.py` | **DOES NOT EXIST** | Never created in the repository |
| `robust_dashboard.py` | **DOES NOT EXIST** | Never created in the repository |
| `minimal_dashboard.py` | **DOES NOT EXIST** | Never created in the repository |
| `realtime_nexus_dashboard.py` | **DOES NOT EXIST** | Never created in the repository |
| `health_dashboard.py` | **DOES NOT EXIST** | Never created in the repository |
| `realtime_dashboard_with_controls.html` | **DOES NOT EXIST** | Never created in the repository |
| `dashboard-test-controls-guide.md` | **DOES NOT EXIST** | Never created in the repository |

**Additional issues**:
- `psutil` is NOT in `requirements.txt` — all psutil-related fixes reference phantom code
- `websockets` is NOT in `requirements.txt` — WebSocket server code doesn't exist
- Bug fixes (1.1–1.4) describe fixes for code that was never written

**Conclusion**: The upgrade plan documents a vision, not actual changes. The bug fixes and dashboard files need to be built from scratch.

---

## What CAN Be Measured (Grounded Architecture)

### Tier 1: Component Inventory & Integrity (CLI-measurable)
These checks validate that all Nexus components exist and are properly configured.

| Check | What It Validates | How |
|---|---|---|
| **Rules exist** | All expected `.windsurf/rules/*.md` files present | File existence check |
| **Rules well-formed** | Valid frontmatter, activation triggers, size limits (<12KB) | Parse and validate |
| **Skills exist** | All expected `.windsurf/skills/*/SKILL.md` files present | File existence check |
| **Skills well-formed** | Valid YAML frontmatter with `name` and `description` | Parse and validate |
| **Workflows exist** | All expected `.windsurf/workflows/*.md` files present | File existence check |
| **Workflows well-formed** | Valid YAML frontmatter with `description` | Parse and validate |
| **Cross-IDE files** | AGENTS.md, CLAUDE.md, .cursorrules, .github/copilot-instructions.md | File existence check |
| **Cross-IDE consistency** | All cross-IDE files reference the same project name | Content comparison |
| **Bootstrap templates** | All templates reference model-selection-reference.md | Content grep |

### Tier 2: Security & Configuration Health (CLI-measurable)
| Check | What It Validates | How |
|---|---|---|
| **.gitignore coverage** | Sensitive patterns excluded (.env, secrets, keys) | Pattern matching |
| **.codeiumignore completeness** | Large reference files excluded from indexing | File check |
| **Secrets scan** | No leaked credentials in config files | Existing `secrets-scan` tool |
| **Dependency health** | requirements.txt packages are importable | Import check |

### Tier 3: Usage Analytics (from existing audit trail)
| Check | What It Validates | How |
|---|---|---|
| **CLI usage patterns** | Which tools are used most/least | Parse audit.jsonl |
| **Error rate** | Percentage of CLI invocations that fail | Parse audit.jsonl |
| **Tool duration trends** | Performance changes over time | Parse audit.jsonl |
| **Last activity** | When Nexus tools were last used | Parse audit.jsonl |

### Tier 4: Self-Healing Recommendations
Based on findings from Tiers 1-3, generate actionable recommendations:
- Missing components → suggest creation commands
- Oversized rules → suggest splitting
- Unused tools → suggest removal or activation
- High error rates → suggest investigation

---

## Implementation Design

### New CLI Command: `bs_cli.py health`

```
python bs_cli.py health check          # Full health check (all tiers)
python bs_cli.py health components     # Tier 1: Component inventory only
python bs_cli.py health security       # Tier 2: Security posture only
python bs_cli.py health usage          # Tier 3: Audit trail analysis only
python bs_cli.py health report         # Full report with recommendations
```

### Output Schema (Structured JSON)

```json
{
  "tool": "health",
  "status": "warn",
  "timestamp": "2026-03-26T12:00:00Z",
  "summary": {
    "total_checks": 24,
    "passed": 20,
    "warnings": 3,
    "failed": 1,
    "score": 83
  },
  "components": {
    "rules": { "status": "pass", "found": 5, "expected": 5, "issues": [] },
    "skills": { "status": "warn", "found": 6, "expected": 7, "issues": ["Missing: webscrape"] },
    "workflows": { "status": "pass", "found": 8, "expected": 8, "issues": [] },
    "cross_ide": { "status": "pass", "found": 4, "expected": 4, "issues": [] }
  },
  "security": {
    "gitignore": { "status": "pass", "patterns_checked": 5 },
    "codeiumignore": { "status": "pass", "exclusions": 3 },
    "secrets": { "status": "pass", "files_scanned": 12 }
  },
  "usage": {
    "total_invocations": 47,
    "error_rate": 0.04,
    "most_used": "smoketest",
    "last_activity": "2026-03-26T11:45:00Z"
  },
  "recommendations": [
    { "severity": "medium", "message": "Missing skill: webscrape", "action": "Run /migrate-toolkit" }
  ]
}
```

### Integration Points
- **New file**: `bootstrap/cli/tools/health.py` — Health check implementation
- **Modified file**: `bootstrap/cli/bs_cli.py` — Register `health` command
- **New skill**: `.windsurf/skills/nexus-health/SKILL.md`
- **New workflow**: `.windsurf/workflows/nexus-health.md` — `/nexus-health` slash command

### Dependencies
- No new dependencies required (uses existing click, rich, pathlib, json)
- Reuses existing security.py functions (scan_text_for_secrets, validate_path)
- Reuses existing utils.py functions (emit, make_result, OutputFormat)

---

## Implementation Phases

### Phase 1: Core Health Tool (Immediate)
1. Create `bootstrap/cli/tools/health.py` with all 4 tiers
2. Register `health` command in `bs_cli.py`
3. Add health check skill and workflow

### Phase 2: Self-Healing (Future)
1. Auto-fix common issues (create missing files from templates)
2. Generate migration scripts for incomplete upgrades
3. Diff current state vs. expected Nexus baseline

### Phase 3: Trend Tracking (Future)
1. Store health check results in `.cache/nexus/health_history.jsonl`
2. Compare current vs. previous health scores
3. Alert on degradation trends

---

## Files to Create

| File | Purpose |
|---|---|
| `bootstrap/cli/tools/health.py` | Core health check implementation |
| `.windsurf/skills/nexus-health/SKILL.md` | Skill definition for health checks |
| `.windsurf/workflows/nexus-health.md` | Workflow for `/nexus-health` command |

## Files to Modify

| File | Change |
|---|---|
| `bootstrap/cli/bs_cli.py` | Add `health` command registration |

---

## Validation Metrics (Realistic)

| Metric | Target | How Measured |
|---|---|---|
| Component completeness | 100% of expected files present | File existence checks |
| Rule health | All rules <12KB with valid triggers | File size + content parse |
| Cross-IDE consistency | All 4 files present and consistent | Content comparison |
| Security posture | No secrets in config, .gitignore complete | Secrets scan + pattern check |
| CLI reliability | <10% error rate | Audit trail analysis |
| Health score | >80% on full check | Weighted composite score |

---

*This plan replaces both `Nexus Health Audit and Tracking Plan.md` and `NexusUpgradePlan.md` with a grounded, implementable solution.*
