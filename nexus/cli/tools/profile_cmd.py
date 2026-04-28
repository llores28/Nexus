"""``nexus profile {detect, show, set}`` -- manage ``.nexus/profile.json``.

- ``detect``: auto-derive a profile from project files (package.json, pyproject.toml,
  go.mod, .github/workflows, etc.). Preserves the existing tier if a profile already
  exists; otherwise defaults to ``fast``.
- ``show``: print the current profile as JSON, plus its hash.
- ``set <field> <value>``: change ``tier`` (the only field worth a CLI verb today;
  edit ``.nexus/profile.json`` directly for everything else).
"""

import json
import sys
from pathlib import Path

import click

from nexus.cli.profile import (
    Profile,
    from_detection,
    hash_profile,
    load,
    save,
)
from nexus.cli.utils import OutputFormat, Status, emit, make_result


def _print_human_summary(profile: Profile) -> None:
    click.echo(f"        tier:             {profile.tier}")
    click.echo(f"        project_name:     {profile.project_name}")
    click.echo(f"        languages:        {', '.join(profile.languages) or '-'}")
    click.echo(f"        frameworks:       {', '.join(profile.frameworks) or '-'}")
    click.echo(f"        package_managers: {', '.join(profile.package_managers) or '-'}")
    click.echo(f"        test_runner:      {profile.test_runner or '-'}")
    click.echo(f"        ci:               {profile.ci or '-'}")
    click.echo(f"        deployment:       {profile.deployment or '-'}")
    click.echo(f"        rules:            {len(profile.rules)}")


def run_profile(
    *,
    subcommand: str,
    args: tuple[str, ...],
    output_format: str,
    project_dir: str,
) -> None:
    pd = Path(project_dir).resolve()
    fmt = OutputFormat(output_format)

    if subcommand == "detect":
        existing = load(pd)
        tier = existing.tier if existing else "fast"
        profile = from_detection(pd, tier=tier)
        save(pd, profile)
        h = hash_profile(profile)
        if fmt == OutputFormat.HUMAN:
            click.echo(f"\n  [ok] Wrote .nexus/profile.json (hash: {h})")
            _print_human_summary(profile)
            return
        emit(make_result(
            "profile.detect",
            Status.PASS,
            message="Profile written",
            details={"hash": h, "profile": profile.to_dict()},
        ), fmt)
        return

    if subcommand == "show":
        profile = load(pd)
        if profile is None:
            if fmt == OutputFormat.HUMAN:
                click.echo("\n  No profile found. Run `nexus profile detect` to create one.")
            else:
                emit(make_result(
                    "profile.show",
                    Status.WARN,
                    message="No profile found",
                ), fmt)
            sys.exit(1)
        h = hash_profile(profile)
        if fmt == OutputFormat.HUMAN:
            click.echo(json.dumps(profile.to_dict(), indent=2))
            click.echo(f"\n  hash: {h}")
            return
        emit(make_result(
            "profile.show",
            Status.PASS,
            details={"hash": h, "profile": profile.to_dict()},
        ), fmt)
        return

    if subcommand == "set":
        if len(args) != 2:
            raise click.UsageError(
                "Usage: nexus profile set <field> <value>  (e.g. `set tier team`)"
            )
        field, value = args
        profile = load(pd)
        if profile is None:
            raise click.UsageError(
                "No profile yet. Run `nexus profile detect` first."
            )
        if field == "tier":
            if value not in ("fast", "team", "enterprise"):
                raise click.UsageError(
                    f"tier must be one of fast/team/enterprise, got: {value}"
                )
            # Re-derive rules from the new tier so seed rules update accordingly.
            new_profile = from_detection(pd, tier=value, project_name=profile.project_name)
            save(pd, new_profile)
            h = hash_profile(new_profile)
            if fmt == OutputFormat.HUMAN:
                click.echo(f"\n  [ok] tier={value}, profile re-derived (hash: {h})")
                _print_human_summary(new_profile)
                return
            emit(make_result(
                "profile.set",
                Status.PASS,
                details={"hash": h, "profile": new_profile.to_dict()},
            ), fmt)
            return
        raise click.UsageError(
            f"Unsupported field: {field!r}. "
            "Edit .nexus/profile.json directly for advanced changes."
        )

    raise click.UsageError(f"Unknown subcommand: {subcommand}")
