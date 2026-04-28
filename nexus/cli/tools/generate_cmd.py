"""``nexus generate`` -- regenerate IDE files from ``.nexus/profile.json``."""

from pathlib import Path
from typing import Optional

import click

from nexus.cli.generators import ALL_TARGETS, run_all
from nexus.cli.profile import hash_profile, load
from nexus.cli.utils import OutputFormat, Status, emit, make_result


def run_generate(
    *,
    output_format: str,
    project_dir: str,
    targets: Optional[str],
    dry_run: bool,
    force: bool,
) -> None:
    pd = Path(project_dir).resolve()
    fmt = OutputFormat(output_format)

    profile = load(pd)
    if profile is None:
        msg = "No profile found. Run `nexus profile detect` first."
        if fmt == OutputFormat.HUMAN:
            click.echo(f"\n  {msg}")
        else:
            emit(make_result("generate", Status.FAIL, message=msg), fmt)
        raise click.Abort()

    target_list: Optional[list[str]] = None
    if targets:
        requested = [t.strip() for t in targets.split(",") if t.strip()]
        valid = set(ALL_TARGETS)
        bad = [t for t in requested if t not in valid]
        if bad:
            raise click.UsageError(
                f"Unknown target(s): {bad}. Valid: {sorted(valid)}"
            )
        target_list = requested

    results = run_all(profile, pd, targets=target_list, dry_run=dry_run, force=force)
    h = hash_profile(profile)

    if fmt == OutputFormat.HUMAN:
        click.echo(f"\n  Profile hash: {h}")
        click.echo(f"  Targets:      {', '.join(target_list) if target_list else 'all'}")
        click.echo(f"  Mode:         {'dry-run' if dry_run else 'write'}")
        click.echo("")
        for f, action in results:
            try:
                rel = f.path.relative_to(pd)
            except ValueError:
                rel = f.path
            click.echo(f"    [{action:>9}] {rel}  ({f.target})")
        click.echo("")
        return

    emit(make_result(
        "generate",
        Status.PASS,
        message=f"{len(results)} files",
        details={
            "profile_hash": h,
            "files": [
                {
                    "path": str(f.path),
                    "action": action,
                    "target": f.target,
                    "block_id": f.block_id,
                    "mode": f.mode,
                }
                for f, action in results
            ],
        },
    ), fmt)
