"""
Nexus init -- bootstrap the current project.

Flow: prereqs check → wizard (or --template) → copy template → journal session-start
       → git hooks → health check.

Idempotent: re-running with `--upgrade` skips the wizard interview and overwrites
hooks/state safely.
"""

import json
import sys
from pathlib import Path
from typing import Any, Optional

import click

from nexus.cli.utils import OutputFormat, Status, emit, make_result


BOOTSTRAP_FILENAME = "BOOTSTRAP.md"
STATE_JSON_REL = ".nexus/state.json"


def _print_banner(action: str) -> None:
    click.echo("\n" + "#" * 60)
    click.echo(f"#  Nexus init -- {action}")
    click.echo("#" * 60)


def _gate_prereqs(output_format: str) -> None:
    """Run a prereqs check. If python or git is missing, abort with guidance."""
    from nexus.cli.tools.prereqs import check_python, check_git

    py = check_python()
    git = check_git()

    if not py.get("installed") or py.get("status") == "missing":
        click.echo("\n  ERROR: Python 3.10+ is required.")
        click.echo("  Install: https://www.python.org/downloads/")
        raise click.Abort()

    if not git.get("installed"):
        click.echo("\n  ERROR: git is required.")
        click.echo("  Install: https://git-scm.com/downloads")
        raise click.Abort()

    click.echo(f"  [ok] Python {py.get('version', '?')}")
    click.echo(f"  [ok] Git {git.get('version', '?')}")


def _copy_template(template_src: Path, project_dir: Path, tier: str, overwrite: bool) -> Path:
    """Copy the chosen tier template to <project>/BOOTSTRAP.md with a header."""
    dest = project_dir / BOOTSTRAP_FILENAME
    if dest.exists() and not overwrite:
        if not click.confirm(f"\n  {BOOTSTRAP_FILENAME} already exists. Overwrite?", default=False):
            click.echo("  Keeping existing BOOTSTRAP.md.")
            return dest

    if not template_src.exists():
        raise click.ClickException(
            f"Template not found at {template_src}. "
            "If you installed via `pip install git+...`, the package may be missing data files. "
            "Try cloning the repo and running setup.sh from there."
        )

    body = template_src.read_text(encoding="utf-8")
    header = (
        f"# Nexus Bootstrap Prompt -- {tier.title()} tier\n"
        f"#\n"
        f"# Paste the content below into your AI assistant (Cascade, Claude Code,\n"
        f"# Cursor, etc.) to generate this project's operating system.\n"
        f"#\n"
        f"# Source template: {template_src.name}\n"
        f"\n"
        f"---\n\n"
    )
    dest.write_text(header + body, encoding="utf-8")
    return dest


def _persist_tier(project_dir: Path, selection: dict[str, Any]) -> None:
    """Write the chosen tier into .nexus/state.json so `--upgrade` can reuse it."""
    from nexus.cli.tools.journal import _load_state, _save_state

    state = _load_state(project_dir)
    state["bootstrap_tier"] = selection["tier"]
    state["bootstrap_template"] = selection["template_path"]
    _save_state(project_dir, state)


def _load_existing_tier(project_dir: Path) -> Optional[str]:
    """Read tier from existing state.json (used by --upgrade)."""
    sj = project_dir / STATE_JSON_REL
    if not sj.exists():
        return None
    try:
        data = json.loads(sj.read_text(encoding="utf-8"))
        return data.get("bootstrap_tier")
    except (OSError, json.JSONDecodeError):
        return None


def run_init(
    project_dir: str = ".",
    output_format: str = "human",
    upgrade: bool = False,
    template: Optional[str] = None,
) -> None:
    """Bootstrap the current project with Nexus."""
    pd = Path(project_dir).resolve()

    if output_format != "human" and template is None:
        emit(make_result(
            "init",
            Status.FAIL,
            message="Non-human format requires --template (the wizard is interactive).",
        ), OutputFormat(output_format))
        raise click.Abort()

    is_upgrade = upgrade or (pd / STATE_JSON_REL).exists()
    _print_banner("upgrade" if is_upgrade else "fresh setup")

    _gate_prereqs(output_format)

    from nexus.cli.tools import wizard

    if template:
        selection = wizard.apply_tier_explicit(template)
        click.echo(f"\n  Tier (forced via --template): {selection['tier']}")
    elif is_upgrade:
        existing_tier = _load_existing_tier(pd)
        if existing_tier:
            selection = wizard.apply_tier_explicit(existing_tier)
            click.echo(f"\n  Reusing previously chosen tier: {existing_tier}")
        else:
            click.echo("\n  No previous tier found. Running wizard.")
            selection = wizard.run_wizard(pd, output_format)
    else:
        selection = wizard.run_wizard(pd, output_format)

    template_src = Path(selection["template_path"])
    bootstrap_path = _copy_template(template_src, pd, selection["tier"], overwrite=is_upgrade)
    click.echo(f"\n  [ok] Wrote {bootstrap_path.name} ({selection['tier']} tier)")

    from nexus.cli.tools.journal import _cmd_session_start
    _cmd_session_start(pd, "human")

    _persist_tier(pd, selection)

    click.echo("\n  Running health check...")
    from nexus.cli.tools.health import run_health
    run_health(subcommand="check", output_format="human", project_dir=str(pd))

    click.echo("\n" + "=" * 60)
    click.echo("  Nexus init complete.")
    click.echo("=" * 60)
    click.echo(f"\n  Next steps:")
    click.echo(f"    1. Open {bootstrap_path.name} and paste it into your AI assistant")
    click.echo(f"    2. Activate the venv in future sessions:")
    if sys.platform == "win32":
        click.echo(f"         PowerShell:  & .venv\\Scripts\\Activate.ps1")
        click.echo(f"         Git Bash:    . .venv/Scripts/activate")
    else:
        click.echo(f"         . .venv/bin/activate")
    click.echo(f"    3. Track progress:  nexus journal status\n")

    if output_format != "human":
        emit(make_result(
            "init",
            Status.PASS,
            message=f"Nexus initialized ({selection['tier']} tier).",
            details={
                "tier": selection["tier"],
                "template_path": selection["template_path"],
                "bootstrap_path": str(bootstrap_path),
                "upgrade": is_upgrade,
            },
        ), OutputFormat(output_format))
