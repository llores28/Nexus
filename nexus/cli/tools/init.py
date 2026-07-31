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


def _generator_targets(consumers: tuple[str, ...]) -> list[str]:
    targets = ["agents_md"]
    if "claude" in consumers:
        targets.append("claude")
    if "cursor" in consumers:
        targets.append("cursor")
    if "copilot" in consumers:
        targets.append("copilot")
    if "devin-review" in consumers:
        targets.append("devin-review")
    return targets


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
        f"# Provide the content below to OpenAI Codex, Devin, Claude, Cursor,\n"
        f"# Copilot, or another coding agent to generate the project operating system.\n"
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


def _ensure_profile_and_generate(
    project_dir: Path,
    tier: str,
    consumers: tuple[str, ...],
) -> dict[str, int]:
    """Write/refresh `.nexus/profile.json` and run all IDE-file generators.

    Idempotent: re-deriving from detection produces a stable profile, and
    generators emit "unchanged" when content already matches. ``from_detection``
    preserves user-authored rules (those with ``nexus_managed=False``) so a
    re-run never silently destroys customization.

    Returns a count summary ``{"created", "updated", "unchanged", "inserted"}``.
    """
    from nexus.cli.profile import from_detection, hash_profile, load, save
    from nexus.cli.generators import run_all
    from nexus.cli.installation import apply_generated_files

    existing = load(project_dir)
    project_name = existing.project_name if existing else project_dir.name
    profile = from_detection(project_dir, tier=tier, project_name=project_name)
    save(project_dir, profile)
    h = hash_profile(profile)

    user_rules = sum(1 for r in profile.rules if not r.nexus_managed)
    click.echo(f"\n  [ok] Wrote .nexus/profile.json (hash: {h})")
    click.echo(
        f"        languages={','.join(profile.languages) or '-'}, "
        f"frameworks={','.join(profile.frameworks) or '-'}"
    )
    click.echo(
        f"        rules: {len(profile.rules)} total ({user_rules} user-authored, preserved across re-detect)"
    )

    planned = run_all(
        profile,
        project_dir,
        targets=_generator_targets(consumers),
        dry_run=True,
    )
    install_actions = apply_generated_files(
        project_dir,
        (generated for generated, _ in planned),
        tier=tier,
        consumers=consumers,
    )
    results = list(zip((generated for generated, _ in planned), install_actions))
    counts = {"created": 0, "updated": 0, "unchanged": 0, "inserted": 0, "preserve": 0}
    changed: list[tuple[Path, str, str]] = []
    for f, install_action in results:
        action = install_action.action
        counts[action] = counts.get(action, 0) + 1
        if action == "unchanged":
            continue
        try:
            rel = f.path.relative_to(project_dir)
        except ValueError:
            rel = f.path
        changed.append((rel, action, f.target))

    if changed:
        click.echo("\n  Generated IDE files:")
        for rel, action, target in changed:
            click.echo(f"    [{action:>9}] {rel}  ({target})")
    else:
        click.echo("\n  IDE files already up to date.")

    from nexus.cli.installation import ensure_gitignore, install_skills, record_managed_files

    gitignore_action = ensure_gitignore(project_dir)
    if gitignore_action.action != "unchanged":
        click.echo(f"\n  [{gitignore_action.action:>9}] .gitignore (Nexus safety block)")

    skill_result = install_skills(
        project_dir,
        consumers=consumers,
        tier=tier,
        dry_run=False,
    )
    changed_skills = [
        item for item in skill_result["actions"] if item["action"] != "unchanged"
    ]
    if changed_skills:
        click.echo("\n  Installed project skills:")
        for item in changed_skills:
            suffix = f" -- {item['detail']}" if item.get("detail") else ""
            click.echo(f"    [{item['action']:>9}] {item['path']}{suffix}")
    record_managed_files(
        project_dir,
        [project_dir / ".gitignore", project_dir / ".nexus" / "profile.json"],
    )
    return counts


def _load_existing_tier(project_dir: Path) -> Optional[str]:
    """Read tier from profile, install manifest, then legacy runtime state."""
    from nexus.cli.installation import load_manifest
    from nexus.cli.profile import load

    profile = load(project_dir)
    if profile and profile.tier in ("fast", "team", "enterprise"):
        return profile.tier
    manifest = load_manifest(project_dir)
    if manifest and manifest.get("tier") in ("fast", "team", "enterprise"):
        return str(manifest["tier"])
    sj = project_dir / STATE_JSON_REL
    if not sj.exists():
        return None
    try:
        data = json.loads(sj.read_text(encoding="utf-8"))
        tier = data.get("bootstrap_tier")
        return tier if tier in ("fast", "team", "enterprise") else None
    except (OSError, json.JSONDecodeError):
        return None


def _do_fresh(
    pd: Path,
    output_format: str,
    template: Optional[str],
    consumers: tuple[str, ...],
    accept_defaults: bool = False,
) -> dict[str, Any]:
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
        # On --accept-defaults preserve the existing file (safer default — never
        # silently overwrite user content in unattended mode).
        if accept_defaults:
            click.echo(f"  Keeping existing {BOOTSTRAP_FILENAME} (--accept-defaults).")
        elif not click.confirm(
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

    from nexus.cli.tools.journal import (
        _cmd_init_agents, _cmd_session_start, _cmd_setup_hooks,
        _find_git_root, _hooks_installed,
    )

    # In unattended mode, install hooks BEFORE session-start so the interactive
    # "Install hooks now? [Y/n]" prompt inside _cmd_session_start is skipped
    # entirely (it only fires when _hooks_installed(...) is False).
    if accept_defaults:
        gr = _find_git_root(pd)
        if gr and not _hooks_installed(gr):
            _cmd_setup_hooks(pd, "human")
    _cmd_session_start(
        pd,
        "human",
        offer_git_init=not accept_defaults,
        offer_hooks=not accept_defaults,
    )

    _persist_tier(pd, selection)
    _ensure_profile_and_generate(pd, selection["tier"], consumers)

    # Install the journal-managed AGENTS.md state block + state-summary.md.
    # Distinct managed-block markers from the profile
    # generators, so they coexist in AGENTS.md without overwriting each other.
    click.echo("\n  Installing journal cross-tool surface...")
    _cmd_init_agents(pd, "human")
    from nexus.cli.installation import record_managed_files
    record_managed_files(pd, [pd / "AGENTS.md"])
    return selection


def _do_upgrade(
    pd: Path,
    refresh: bool,
    template: Optional[str],
    consumers: tuple[str, ...],
    output_format: str,
    accept_defaults: bool = False,
) -> dict[str, Any]:
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
            if accept_defaults or output_format != "human":
                raise click.ClickException(
                    "Upgrade tier is unknown. Pass --template fast, team, or enterprise "
                    "for unattended migration."
                )
            selection = wizard.run_wizard(pd, output_format)
            click.echo(f"\n  Selected migration tier: {selection['tier']}")
        else:
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
    _ensure_profile_and_generate(pd, selection["tier"], consumers)

    from nexus.cli.tools.context import migrate_legacy_skills
    preview = migrate_legacy_skills(pd, apply=False)
    migratable = [item for item in preview["items"] if item["status"] == "would-create"]
    if preview["items"]:
        click.echo("\n  Legacy Windsurf -> open Agent Skills migration preview:")
        for item in preview["items"]:
            click.echo(f"    [{item['status']:>12}] {item['source']} -> {item['target']}")
        apply_migration = accept_defaults or (
            bool(migratable) and click.confirm(
                "\n  Create the non-conflicting .agents/skills entries now?",
                default=True,
            )
        )
        if apply_migration:
            result = migrate_legacy_skills(pd, apply=True)
            from nexus.cli.installation import install_skills
            install_skills(pd, consumers=consumers, tier=selection["tier"])
            click.echo(
                f"    [ok] created {result['created']} skill(s); "
                f"consolidated {result['consolidated']} legacy duplicate(s); "
                f"left {result['collisions']} collision(s) untouched"
            )
            click.echo("    Legacy sources retained; remove them only after validating canonical skills.")
    return selection


def _run_init_dry_run(
    pd: Path,
    *,
    is_upgrade: bool,
    template: Optional[str],
    output_format: str,
    accept_defaults: bool,
    consumers: tuple[str, ...],
) -> str:
    from nexus.cli.generators import run_all
    from nexus.cli.installation import apply_generated_files, ensure_gitignore, install_skills
    from nexus.cli.profile import from_detection, load
    from nexus.cli.tools import wizard
    from nexus.cli.tools.context import migrate_legacy_skills

    tier = template or (_load_existing_tier(pd) if is_upgrade else None)
    if tier is None:
        if accept_defaults or output_format != "human":
            raise click.ClickException(
                "Dry-run needs --template for a new or unclassified unattended project."
            )
        tier = wizard.run_wizard(pd, output_format)["tier"]
    current = load(pd)
    profile = from_detection(
        pd,
        tier=tier,
        project_name=current.project_name if current else pd.name,
    )
    generated = run_all(
        profile,
        pd,
        targets=_generator_targets(consumers),
        dry_run=True,
    )
    generated_actions = apply_generated_files(
        pd,
        (item for item, _ in generated),
        tier=tier,
        consumers=consumers,
        dry_run=True,
    )
    skills = install_skills(
        pd,
        consumers=consumers,
        tier=tier,
        dry_run=True,
    )
    click.echo(f"\n  Dry-run plan: tier={tier}, consumers={','.join(consumers)}")
    ignore_action = ensure_gitignore(pd, dry_run=True)
    click.echo(f"    [{ignore_action.action:>9}] {ignore_action.path}")
    for item, action in zip((item for item, _ in generated), generated_actions):
        suffix = f" -- {action.detail}" if action.detail else ""
        click.echo(f"    [{action.action:>9}] {item.path.relative_to(pd)}{suffix}")
    for item in skills["actions"]:
        suffix = f" -- {item['detail']}" if item.get("detail") else ""
        click.echo(f"    [{item['action']:>9}] {item['path']}{suffix}")
    legacy = migrate_legacy_skills(pd, apply=False)
    for item in legacy.get("items", []):
        click.echo(f"    [{item['status']:>9}] {item['source']} -> {item['target']}")
    legacy_rules = pd / ".windsurf" / "rules"
    if legacy_rules.is_dir():
        click.echo("    [   review] .windsurf/rules/* -> manual AGENTS.md/profile candidates")
    click.echo("\n  No files were written.")
    return tier


def run_init(
    project_dir: str = ".",
    output_format: str = "human",
    upgrade: bool = False,
    refresh: bool = False,
    template: Optional[str] = None,
    accept_defaults: bool = False,
    dry_run: bool = False,
    consumers: str = "all",
) -> None:
    """Bootstrap or upgrade the current project with Nexus."""
    pd = Path(project_dir).resolve()
    from nexus.cli.installation import MANIFEST_REL, parse_consumers

    try:
        selected_consumers = parse_consumers(consumers)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if output_format != "human" and template is None and not upgrade:
        emit(make_result(
            "init",
            Status.FAIL,
            message="Non-human format requires --template (the wizard is interactive) or --upgrade.",
        ), OutputFormat(output_format))
        raise click.Abort()

    if refresh and not upgrade and not _load_existing_tier(pd):
        click.echo("\n  --refresh has no effect without --upgrade or an existing project. Ignoring.")
        refresh = False

    has_nexus_artifacts = any(
        path.exists()
        for path in (
            pd / ".nexus/profile.json",
            pd / MANIFEST_REL,
            pd / STATE_JSON_REL,
            pd / ".windsurf",
        )
    ) or "<!-- nexus:" in (
        (pd / "AGENTS.md").read_text(encoding="utf-8", errors="replace")
        if (pd / "AGENTS.md").is_file() else ""
    )
    is_upgrade = upgrade or has_nexus_artifacts

    if not is_upgrade and accept_defaults and template is None:
        raise click.ClickException(
            "Unattended fresh setup requires --template fast, team, or enterprise."
        )

    _print_banner("upgrade" if is_upgrade else "fresh setup")
    _gate_prereqs(output_format)

    if dry_run:
        _run_init_dry_run(
            pd,
            is_upgrade=is_upgrade,
            template=template,
            output_format=output_format,
            accept_defaults=accept_defaults,
            consumers=selected_consumers,
        )
        return

    if is_upgrade:
        click.echo("\n  Upgrade plan (preview before applying):")
        preview_tier = _run_init_dry_run(
            pd,
            is_upgrade=True,
            template=template,
            output_format=output_format,
            accept_defaults=accept_defaults,
            consumers=selected_consumers,
        )
        if template is None and _load_existing_tier(pd) is None:
            template = preview_tier

    if is_upgrade:
        selection = _do_upgrade(pd, refresh=refresh, template=template,
                                consumers=selected_consumers,
                                output_format=output_format,
                                accept_defaults=accept_defaults)
    else:
        selection = _do_fresh(pd, output_format=output_format, template=template,
                              consumers=selected_consumers,
                              accept_defaults=accept_defaults)

    click.echo("\n  Running health check...")
    from nexus.cli.tools.health import run_health
    run_health(subcommand="check", output_format="human", project_dir=str(pd))
    from nexus.cli.tools.doctor import diagnose
    readiness = diagnose(pd, deep=True, consumer="all")
    if readiness["status"] == "fail":
        raise click.ClickException(
            "Nexus was installed, but required post-install diagnostics failed. "
            "Run `nexus doctor --consumer all --deep` for details."
        )

    # Journal staleness/drift check. On upgrade we offer to auto-refresh;
    # on fresh setups state.json doesn't exist yet so this is a quick "missing"
    # diagnosis that the user can ignore (init will create state via journal usage).
    if is_upgrade:
        # NOTE: hook validation/upgrade already ran inside `_do_upgrade` (which
        # always calls _cmd_setup_hooks when a git repo exists). Setup-hooks is
        # idempotent — current v2 hooks are skipped, outdated ones are upgraded
        # in place — so a second call here would just produce duplicate output.
        from nexus.cli.tools.journal import run_journal

        click.echo("\n  Checking journal freshness...")
        from nexus.cli.tools.journal import _diagnose_journal
        diagnosis = _diagnose_journal(pd)
        click.echo(f"    journal status: {diagnosis['status']}")
        for issue in diagnosis["issues"]:
            click.echo(f"      - {issue}")
        refreshed = False
        if diagnosis["status"] in ("drift", "stale", "missing"):
            if output_format == "human":
                do_refresh = accept_defaults or click.confirm(
                    "\n  Auto-refresh the journal now? "
                    "(backfill missing commits, regenerate dashboards)",
                    default=True,
                )
                if do_refresh:
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
    click.echo("\n  What was set up:")
    click.echo("    - .nexus/profile.json (single source of truth — edit to customize rules)")
    click.echo("    - AGENTS.md (canonical shared instructions)")
    click.echo("    - .agents/skills/*/SKILL.md (canonical just-in-time workflows)")
    if "claude" in selected_consumers:
        click.echo("    - CLAUDE.md + .claude/skills/* (Claude-native projection)")
    if "cursor" in selected_consumers:
        click.echo("    - .cursor/rules/*.mdc (Cursor-only deltas)")
    if "copilot" in selected_consumers:
        click.echo("    - .github/copilot-instructions.md + .github/instructions/ (Copilot deltas)")
    click.echo(f"    - {BOOTSTRAP_FILENAME} (optional narrative prompt for richer AI customization)")
    click.echo("\n  Next steps:")
    click.echo("    1. Review the generated AGENTS.md and provider adapters.")
    click.echo("    2. Run `nexus doctor --consumer all --deep` to verify discovery.")
    click.echo("    3. Add custom rules: edit .nexus/profile.json (rules with nexus_managed=False")
    click.echo("       are preserved across re-runs), then `nexus generate`.")
    click.echo("    4. Track progress: `nexus journal status`.")
    if sys.platform == "win32":
        click.echo("\n  Activate venv in future sessions:")
        click.echo("       PowerShell:  & .venv\\Scripts\\Activate.ps1")
        click.echo("       Git Bash:    . .venv/Scripts/activate")
    else:
        click.echo("\n  Activate venv in future sessions:  . .venv/bin/activate")
    click.echo("")

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
