"""
Nexus init -- bootstrap (or maintain) a project with Nexus.

Two modes:

  Fresh init (no .nexus/state.json):
    Wizard (or --template) -> write BOOTSTRAP.md -> session-start -> hooks -> health.

  Upgrade (state.json + bootstrap_tier already exist):
    Reuse the prior tier choice, re-validate git hooks (idempotent), re-run health
    check. NEVER overwrites BOOTSTRAP.md unless --refresh is passed.

The upgrade path is what `setup.sh` / `setup.ps1` invoke after a `pip install
--upgrade` so an existing project gets the new hook templates and a sanity
check without a wizard interruption or a clobbered prompt file.
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


def _write_template(template_src: Path, project_dir: Path, tier: str) -> Path:
    """Write the chosen tier template to <project>/BOOTSTRAP.md with a header.

    Caller is responsible for confirming overwrite if the file already exists.
    """
    if not template_src.exists():
        raise click.ClickException(
            f"Template not found at {template_src}. "
            "If you installed via `pip install git+...`, the package may be missing data files. "
            "Try cloning the repo and running setup.sh from there."
        )

    dest = project_dir / BOOTSTRAP_FILENAME
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
    """Write the chosen tier into .nexus/state.json so future runs reuse it."""
    from nexus.cli.tools.journal import _load_state, _save_state

    state = _load_state(project_dir)
    state["bootstrap_tier"] = selection["tier"]
    state["bootstrap_template"] = selection["template_path"]
    _save_state(project_dir, state)


def _load_existing_tier(project_dir: Path) -> Optional[str]:
    """Read tier from existing state.json. Returns None if file or field missing."""
    sj = project_dir / STATE_JSON_REL
    if not sj.exists():
        return None
    try:
        data = json.loads(sj.read_text(encoding="utf-8"))
        tier = data.get("bootstrap_tier")
        return tier if tier in ("fast", "team", "enterprise") else None
    except (OSError, json.JSONDecodeError):
        return None


def _do_fresh(pd: Path, output_format: str, template: Optional[str]) -> dict[str, Any]:
    """Fresh init: wizard (or --template), write BOOTSTRAP.md, return selection."""
    from nexus.cli.tools import wizard

    if template:
        selection = wizard.apply_tier_explicit(template)
        click.echo(f"\n  Tier (forced via --template): {selection['tier']}")
    else:
        selection = wizard.run_wizard(pd, output_format)

    template_src = Path(selection["template_path"])
    dest = pd / BOOTSTRAP_FILENAME
    if dest.exists():
        if not click.confirm(
            f"\n  {BOOTSTRAP_FILENAME} already exists. Overwrite?",
            default=False,
        ):
            click.echo("  Keeping existing BOOTSTRAP.md.")
        else:
            _write_template(template_src, pd, selection["tier"])
            click.echo(f"\n  [ok] Wrote {BOOTSTRAP_FILENAME} ({selection['tier']} tier)")
    else:
        _write_template(template_src, pd, selection["tier"])
        click.echo(f"\n  [ok] Wrote {BOOTSTRAP_FILENAME} ({selection['tier']} tier)")

    from nexus.cli.tools.journal import _cmd_session_start
    _cmd_session_start(pd, "human")

    _persist_tier(pd, selection)
    return selection


def _do_upgrade(pd: Path, refresh: bool, template: Optional[str]) -> dict[str, Any]:
    """Upgrade: reuse tier (or accept --template override), re-validate hooks.

    NEVER touches BOOTSTRAP.md unless --refresh is passed (or it doesn't exist
    yet, which would be unusual for an upgrade path).
    """
    from nexus.cli.tools import wizard

    if template:
        selection = wizard.apply_tier_explicit(template)
        click.echo(f"\n  Tier override via --template: {selection['tier']}")
    else:
        existing_tier = _load_existing_tier(pd)
        if not existing_tier:
            click.echo(
                "\n  ERROR: --upgrade requires an existing bootstrap_tier in "
                ".nexus/state.json, but none was found.\n"
                "  Either run `nexus init` (no --upgrade) for a fresh setup,\n"
                "  or pass --template <fast|team|enterprise> to skip the wizard."
            )
            raise click.Abort()
        selection = wizard.apply_tier_explicit(existing_tier)
        click.echo(f"\n  Reusing previously chosen tier: {existing_tier}")

    bootstrap_path = pd / BOOTSTRAP_FILENAME
    if refresh or not bootstrap_path.exists():
        template_src = Path(selection["template_path"])
        _write_template(template_src, pd, selection["tier"])
        action = "Refreshed" if refresh and bootstrap_path.exists() else "Wrote"
        click.echo(f"\n  [ok] {action} {BOOTSTRAP_FILENAME} ({selection['tier']} tier)")
    else:
        click.echo(f"\n  [ok] {BOOTSTRAP_FILENAME} preserved (pass --refresh to regenerate)")

    # Re-validate hooks (idempotent — _cmd_setup_hooks skips already-installed ones).
    from nexus.cli.tools.journal import _cmd_setup_hooks, _find_git_root
    if _find_git_root(pd):
        click.echo("\n  Re-validating git hooks...")
        _cmd_setup_hooks(pd, "human")
    else:
        click.echo("\n  (no git repo -- skipping hook validation)")

    _persist_tier(pd, selection)
    return selection


def run_init(
    project_dir: str = ".",
    output_format: str = "human",
    upgrade: bool = False,
    refresh: bool = False,
    template: Optional[str] = None,
) -> None:
    """Bootstrap or upgrade the current project with Nexus."""
    pd = Path(project_dir).resolve()

    if output_format != "human" and template is None and not upgrade:
        emit(make_result(
            "init",
            Status.FAIL,
            message="Non-human format requires --template (the wizard is interactive) or --upgrade.",
        ), OutputFormat(output_format))
        raise click.Abort()

    if refresh and not upgrade and not (pd / STATE_JSON_REL).exists():
        click.echo("\n  --refresh has no effect without --upgrade or an existing project. Ignoring.")
        refresh = False

    state_present = (pd / STATE_JSON_REL).exists()
    is_upgrade = upgrade or state_present

    _print_banner("upgrade" if is_upgrade else "fresh setup")
    _gate_prereqs(output_format)

    if is_upgrade:
        selection = _do_upgrade(pd, refresh=refresh, template=template)
    else:
        selection = _do_fresh(pd, output_format=output_format, template=template)

    click.echo("\n  Running health check...")
    from nexus.cli.tools.health import run_health
    run_health(subcommand="check", output_format="human", project_dir=str(pd))

    # Journal staleness/drift check. On upgrade we offer to auto-refresh;
    # on fresh setups state.json doesn't exist yet so this is a quick "missing"
    # diagnosis that the user can ignore (init will create state via journal usage).
    if is_upgrade:
        # Hook upgrade first: if a downstream project predates Phase 1, its
        # post-commit hook may be a v1 template (no stderr capture, no baked
        # paths). setup-hooks is idempotent — current v2 hooks are skipped,
        # old ones get upgraded in place. Doing this BEFORE the journal
        # freshness check is intentional: broken hooks are often the root
        # cause of any drift that follows.
        from nexus.cli.tools.journal import _hooks_installed, _resolve_git_root, run_journal
        git_root = _resolve_git_root(pd)
        if git_root is not None and not _hooks_installed(git_root):
            click.echo("\n  Upgrading journal git hooks...")
            run_journal(
                subcommand="setup-hooks",
                args=(),
                output_format="human",
                project_dir=str(pd),
            )

        click.echo("\n  Checking journal freshness...")
        from nexus.cli.tools.journal import _diagnose_journal
        diagnosis = _diagnose_journal(pd)
        click.echo(f"    journal status: {diagnosis['status']}")
        for issue in diagnosis["issues"]:
            click.echo(f"      - {issue}")
        refreshed = False
        if diagnosis["status"] in ("drift", "stale", "missing"):
            if output_format == "human":
                if click.confirm(
                    "\n  Auto-refresh the journal now? "
                    "(backfill missing commits, regenerate dashboards)",
                    default=True,
                ):
                    run_journal(
                        subcommand="health",
                        args=("refresh",),
                        output_format="human",
                        project_dir=str(pd),
                    )
                    refreshed = True
                else:
                    click.echo("    Skipped. Run `nexus journal health refresh` later.")
            else:
                click.echo(
                    "    (non-interactive mode — run `nexus journal health refresh` "
                    "to backfill)"
                )

        # Always regenerate the dashboard + state-summary.md, even when status
        # was "ok" or the user declined refresh. Catches the gap where a freshly
        # upgraded project has clean status but no dashboard yet — the cost is
        # one cheap export call, the benefit is users always seeing a current
        # dashboard after any upgrade. Skipped if refresh already ran (it
        # exports as a side effect). JSON output is captured to keep init's
        # human output clean.
        if not refreshed:
            click.echo("\n  Regenerating dashboard + state-summary.md...")
            import contextlib
            import io
            from nexus.cli.tools.journal import _cmd_export
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    _cmd_export(pd, "json")
                click.echo("    [ok] .nexus/state-dashboard.html and .nexus/state-summary.md")
            except Exception as e:
                click.echo(f"    [warn] dashboard regeneration failed: {e}")

    click.echo("\n" + "=" * 60)
    click.echo(f"  Nexus init complete ({'upgrade' if is_upgrade else 'fresh setup'}).")
    click.echo("=" * 60)
    click.echo(f"\n  Next steps:")
    if not is_upgrade or refresh:
        click.echo(f"    1. Open {BOOTSTRAP_FILENAME} and paste it into your AI assistant")
    click.echo(f"    {'2' if (not is_upgrade or refresh) else '1'}. Activate the venv in future sessions:")
    if sys.platform == "win32":
        click.echo(f"         PowerShell:  & .venv\\Scripts\\Activate.ps1")
        click.echo(f"         Git Bash:    . .venv/Scripts/activate")
    else:
        click.echo(f"         . .venv/bin/activate")
    click.echo(f"    {'3' if (not is_upgrade or refresh) else '2'}. Track progress:  nexus journal status\n")

    if output_format != "human":
        emit(make_result(
            "init",
            Status.PASS,
            message=f"Nexus {'upgraded' if is_upgrade else 'initialized'} ({selection['tier']} tier).",
            details={
                "mode": "upgrade" if is_upgrade else "fresh",
                "tier": selection["tier"],
                "template_path": selection["template_path"],
                "bootstrap_path": str(pd / BOOTSTRAP_FILENAME),
                "refresh": refresh,
            },
        ), OutputFormat(output_format))
