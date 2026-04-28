"""``nexus doctor`` -- unified drift / health check.

Cheap by default (no filesystem walk) -- reads each generated file's
embedded profile-hash stamp and compares to the current profile hash.

Pass ``--deep`` to re-run stack detection and diff against the stored
profile (catches "profile says next, repo now uses nuxt" style drift).
"""

from pathlib import Path

import click

from nexus.cli.generators import run_all
from nexus.cli.profile import (
    NEXUS_VERSION,
    from_detection,
    hash_profile,
    load,
)
from nexus.cli.utils import OutputFormat, Status, emit, make_result


def _read_stamp_hash(path: Path) -> str | None:
    """Return the 12-char profile hash embedded in the file, or None if missing."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    needle = "<!-- nexus: profile="
    idx = text.find(needle)
    if idx < 0:
        return None
    start = idx + len(needle)
    return text[start : start + 12] or None


def _check_file(path: Path, expected_hash: str) -> tuple[str, str]:
    """Return ('ok'|'drift'|'missing'|'unstamped', detail) for one managed file."""
    if not path.exists():
        return ("missing", "file not present")
    found = _read_stamp_hash(path)
    if found is None:
        return ("unstamped", "no profile stamp -- file was hand-rolled or pre-Nexus")
    if found != expected_hash:
        return ("drift", f"stamp={found}, expected={expected_hash}")
    return ("ok", "stamp current")


def run_doctor(
    *,
    output_format: str,
    project_dir: str,
    deep: bool,
) -> None:
    pd = Path(project_dir).resolve()
    fmt = OutputFormat(output_format)

    profile = load(pd)
    if profile is None:
        msg = "No .nexus/profile.json -- run `nexus profile detect`."
        if fmt == OutputFormat.HUMAN:
            click.echo(f"\n  {msg}\n")
        else:
            emit(make_result(
                "doctor",
                Status.FAIL,
                message=msg,
                items=[{"check": "profile-present", "status": "fail"}],
            ), fmt)
        raise click.Abort()

    items: list[dict] = [{"check": "profile-present", "status": "ok"}]
    overall = Status.PASS

    if profile.nexus_version != NEXUS_VERSION:
        items.append({
            "check": "version-match",
            "status": "warn",
            "detail": (
                f"profile.nexus_version={profile.nexus_version}, "
                f"cli={NEXUS_VERSION} -- run `nexus profile detect`"
            ),
        })
        overall = Status.WARN
    else:
        items.append({"check": "version-match", "status": "ok"})

    expected = hash_profile(profile)
    planned = run_all(profile, pd, dry_run=True)
    drift_count = 0
    missing_count = 0
    for f, _ in planned:
        st, detail = _check_file(f.path, expected)
        try:
            rel = str(f.path.relative_to(pd))
        except ValueError:
            rel = str(f.path)
        items.append({
            "check": f"hash:{f.target}:{f.block_id}",
            "status": "ok" if st == "ok" else "warn",
            "path": rel,
            "detail": detail,
        })
        if st == "drift":
            drift_count += 1
            overall = Status.WARN
        elif st == "missing":
            missing_count += 1
            overall = Status.WARN
        elif st == "unstamped":
            overall = Status.WARN

    if deep:
        fresh = from_detection(
            pd,
            tier=profile.tier,
            project_name=profile.project_name,
        )
        diffs = []
        for field_name in (
            "languages", "frameworks", "package_managers",
            "test_runner", "ci", "deployment",
        ):
            old = getattr(profile, field_name)
            new = getattr(fresh, field_name)
            if old != new:
                diffs.append({"field": field_name, "stored": list(old) if isinstance(old, tuple) else old,
                              "detected": list(new) if isinstance(new, tuple) else new})
        if diffs:
            items.append({"check": "stack-drift", "status": "warn", "diffs": diffs})
            overall = Status.WARN
        else:
            items.append({"check": "stack-drift", "status": "ok"})

    # Journal health -- best-effort delegation
    try:
        from nexus.cli.tools.journal import _diagnose_journal
        diag = _diagnose_journal(pd)
        diag_status = diag.get("status", "unknown")
        st = "ok" if diag_status == "ok" else "warn"
        items.append({
            "check": "journal-health",
            "status": st,
            "detail": diag_status,
        })
        if st == "warn" and overall == Status.PASS:
            overall = Status.WARN
    except Exception as e:  # pragma: no cover -- defensive
        items.append({
            "check": "journal-health",
            "status": "skip",
            "detail": f"unavailable ({type(e).__name__})",
        })

    summary_bits: list[str] = []
    if drift_count:
        summary_bits.append(f"{drift_count} drifted")
    if missing_count:
        summary_bits.append(f"{missing_count} missing")
    msg = ", ".join(summary_bits) if summary_bits else "all clean"

    if fmt == OutputFormat.HUMAN:
        click.echo(f"\n  Doctor -- {msg}")
        click.echo(f"  Profile hash: {expected}")
        click.echo("")
        marks = {"ok": "+", "warn": "!", "fail": "x", "skip": "-"}
        for it in items:
            mark = marks.get(it.get("status", ""), "?")
            line = f"    [{mark}] {it['check']}"
            if it.get("path"):
                line += f"  {it['path']}"
            if it.get("detail"):
                line += f"  -- {it['detail']}"
            click.echo(line)
            for d in it.get("diffs", []):
                click.echo(f"        {d['field']}: stored={d['stored']!r} detected={d['detected']!r}")
        click.echo("")
        if drift_count or missing_count:
            click.echo(
                "  Tip: `nexus generate` regenerates from profile; "
                "`nexus generate --force` overrides hand-edits.\n"
            )
        return

    emit(make_result(
        "doctor",
        overall,
        message=msg,
        items=items,
        details={
            "profile_hash": expected,
            "drift_count": drift_count,
            "missing_count": missing_count,
        },
    ), fmt)
