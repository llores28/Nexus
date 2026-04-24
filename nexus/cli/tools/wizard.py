"""
Bootstrap Wizard -- interactive tier selection (Fast / Team / Enterprise).

Lightweight Python port of nexus/wizard-reference.md. Asks 7 high-signal
questions and applies the same deterministic selection algorithm. The full
Cascade workflow (.windsurf/workflows/bootstrap-wizard.md) covers branch
follow-ups for Windsurf users; this module is the CLI equivalent.
"""

from pathlib import Path
from typing import Any

import click

from nexus.cli.utils import OutputFormat, Status, emit, make_result


TEMPLATES = {
    "fast": "1Fast-ws-Bootstrap.md",
    "team": "2Team-ws-Bootstrap.md",
    "enterprise": "3Enterprise-ws-Bootstrap.md",
}


def _template_path(tier: str) -> Path:
    """Resolve a tier name to the absolute path of its bootstrap template."""
    nexus_root = Path(__file__).resolve().parent.parent.parent
    return nexus_root / TEMPLATES[tier]


def _ask_choice(prompt: str, choices: list[tuple[str, str]], default_key: str) -> str:
    """Prompt the user with labeled choices. Returns the selected key."""
    click.echo(f"\n  {prompt}")
    for key, label in choices:
        marker = "*" if key == default_key else " "
        click.echo(f"    [{marker}] {key:<14} -- {label}")
    keys = [k for k, _ in choices]
    while True:
        ans = click.prompt(f"  Choose [{'/'.join(keys)}]", default=default_key, show_default=False).strip().lower()
        if ans in keys:
            return ans
        click.echo(f"  Invalid choice. Pick one of: {', '.join(keys)}")


def _interview() -> dict[str, str]:
    """Ask the 7 high-signal questions. Returns a dict of answers."""
    click.echo("\n" + "=" * 60)
    click.echo("  Nexus Bootstrap Wizard")
    click.echo("  7 quick questions to recommend the right tier.")
    click.echo("=" * 60)

    answers: dict[str, str] = {}

    answers["project_stage"] = _ask_choice(
        "1. What stage is the project in?",
        [
            ("prototype", "Throwaway, experimenting, no real users"),
            ("pre-prod", "Building toward launch, not yet live"),
            ("production", "Live, serving real users"),
        ],
        default_key="prototype",
    )

    answers["customer_impact"] = _ask_choice(
        "2. Who uses (or will use) this?",
        [
            ("internal", "Just me / internal team"),
            ("external", "External customers / public users"),
        ],
        default_key="internal",
    )

    answers["data_sensitivity"] = _ask_choice(
        "3. What kind of data does it handle?",
        [
            ("none", "No personal data, no secrets"),
            ("sensitive", "PII / PHI / PCI / financial data"),
        ],
        default_key="none",
    )

    answers["compliance"] = _ask_choice(
        "4. Any regulatory / compliance requirements?",
        [
            ("none", "None"),
            ("soc2", "SOC 2"),
            ("hipaa", "HIPAA"),
            ("pci", "PCI"),
            ("other", "Other (GDPR, ISO 27001, etc.)"),
        ],
        default_key="none",
    )

    answers["availability"] = _ask_choice(
        "5. Uptime / SLA expectations?",
        [
            ("best-effort", "Best-effort, downtime is fine"),
            ("99.9", "99.9% (about 8h downtime/year)"),
            ("99.95+", "99.95%+ (mission-critical)"),
        ],
        default_key="best-effort",
    )

    answers["oncall"] = _ask_choice(
        "6. Is anyone on-call for incidents?",
        [
            ("no", "No formal on-call"),
            ("yes", "Yes, formal on-call rotation"),
        ],
        default_key="no",
    )

    answers["speed_vs_control"] = _ask_choice(
        "7. Trade-off: delivery speed vs governance?",
        [
            ("speed", "Speed -- ship fast, iterate"),
            ("balanced", "Balanced -- some process, but pragmatic"),
            ("strict", "Strict -- formal approvals, audit, controls"),
        ],
        default_key="balanced",
    )

    return answers


def _compute_flags(a: dict[str, str]) -> dict[str, bool]:
    """Compute decision flags from interview answers (mirrors wizard-reference.md §Compute Decision Flags)."""
    return {
        "regulated": a["compliance"] != "none",
        "sensitive_data": a["data_sensitivity"] == "sensitive",
        "prod_risk": (
            a["project_stage"] == "production"
            or a["customer_impact"] == "external"
            or a["oncall"] == "yes"
        ),
        "in_production": a["project_stage"] == "production",
        "high_availability": a["availability"] in ("99.9", "99.95+"),
        "high_governance": a["speed_vs_control"] == "strict",
        "speed_focused": a["speed_vs_control"] == "speed",
        "external": a["customer_impact"] == "external",
        "early_stage": a["project_stage"] in ("prototype", "pre-prod"),
        "oncall": a["oncall"] == "yes",
    }


def _select_tier(flags: dict[str, bool]) -> tuple[str, str, list[tuple[str, bool, str]]]:
    """Apply the selection algorithm. Returns (tier, confidence, reasoning_rows)."""
    enterprise_triggers = [
        ("regulated",
         flags["regulated"],
         "Compliance requirements (SOC2/HIPAA/PCI/etc.) demand formal controls."),
        ("sensitive_data + prod_risk",
         flags["sensitive_data"] and flags["prod_risk"],
         "Sensitive data in a production-risk context -- needs audit + access controls."),
        ("high_governance",
         flags["high_governance"],
         "Strict governance/approvals selected -- Enterprise tier is built for this."),
        ("high_availability + (production or on-call)",
         flags["high_availability"] and (flags["in_production"] or flags["oncall"]),
         "High SLA in actual production / on-call context -- needs DR, runbooks, change controls."),
    ]

    fast_conditions = [
        ("not regulated", not flags["regulated"]),
        ("no sensitive data", not flags["sensitive_data"]),
        ("early stage", flags["early_stage"]),
        ("internal users only", not flags["external"]),
        ("no on-call", not flags["prod_risk"] or (flags["early_stage"] and not flags["external"])),
        ("speed-focused", flags["speed_focused"]),
        ("no high SLA", not flags["high_availability"]),
    ]

    triggered = [(name, why) for (name, hit, why) in enterprise_triggers if hit]
    if triggered:
        confidence = "High" if len(triggered) >= 2 else "Medium"
        rows = [(name, True, why) for (name, why) in triggered]
        return "enterprise", confidence, rows

    if all(cond for (_, cond) in fast_conditions):
        rows = [(name, True, "All conservative flags clear -- safe to ship fast.") for (name, _) in fast_conditions]
        return "fast", "High", rows[:3]

    rows = []
    for name, hit, why in enterprise_triggers:
        rows.append((name, hit, why))
    confidence = "Medium" if flags["external"] or flags["prod_risk"] else "Low"
    return "team", confidence, rows[:3]


def _print_recommendation(tier: str, confidence: str, rows: list[tuple[str, bool, str]]) -> None:
    """Print the wizard's recommendation in a human-friendly format."""
    tier_label = {"fast": "Fast", "team": "Team", "enterprise": "Enterprise"}[tier]
    click.echo("\n" + "=" * 60)
    click.echo(f"  Recommended tier: {tier_label}")
    click.echo(f"  Confidence: {confidence}")
    click.echo("=" * 60)
    click.echo("\n  Reasoning:")
    for name, hit, why in rows:
        marker = "+" if hit else "-"
        click.echo(f"    [{marker}] {name}")
        click.echo(f"        {why}")


def apply_tier_explicit(tier: str) -> dict[str, Any]:
    """Skip the interview -- used by `nexus init --template <tier>`."""
    if tier not in TEMPLATES:
        raise click.BadParameter(f"Unknown tier: {tier}. Choose from: {', '.join(TEMPLATES)}")
    return {
        "tier": tier,
        "template_path": str(_template_path(tier)),
        "confidence": "User-forced",
        "reasoning": [(f"--template {tier}", True, "Explicit selection via flag.")],
        "answers": {},
    }


def run_wizard(project_dir: Path, output_format: str) -> dict[str, Any]:
    """Run the interactive wizard. Returns selection dict (tier, template_path, ...)."""
    if output_format != "human":
        emit(make_result(
            "wizard",
            Status.FAIL,
            message="Wizard requires --format human (interactive). Pass --template to skip the interview.",
        ), OutputFormat(output_format))
        raise click.Abort()

    answers = _interview()
    flags = _compute_flags(answers)
    tier, confidence, rows = _select_tier(flags)

    _print_recommendation(tier, confidence, rows)

    apply = click.confirm("\n  Apply this recommendation?", default=True)
    if not apply:
        forced = _ask_choice(
            "Pick a tier manually:",
            [("fast", "Fast"), ("team", "Team"), ("enterprise", "Enterprise")],
            default_key="team",
        )
        tier = forced
        confidence = "User-forced"
        rows = [(f"forced to {forced}", True, "User overrode the recommendation.")]

    return {
        "tier": tier,
        "template_path": str(_template_path(tier)),
        "confidence": confidence,
        "reasoning": rows,
        "answers": answers,
    }
