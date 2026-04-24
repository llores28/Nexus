"""
Project Journal Tool — cross-session project state tracking.

Subcommands:
  session-start   — start a new session, show last state, offer git init if missing
  session-end     — summarize changes (diff-based), prompt for next steps, write state
  log             — append a one-line event (non-interactive, Cascade-friendly)
  status          — display current .nexus/state.md
  export          — generate .nexus/state-dashboard.html
  diff            — show auto-detected file changes since session start
"""

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from nexus.cli.utils import (
    OutputFormat, Status, emit, make_result, find_project_root,
)


# --- Constants ---

NEXUS_DIR = ".nexus"
STATE_JSON = ".nexus/state.json"
STATE_MD = ".nexus/state.md"
DASHBOARD_HTML = ".nexus/state-dashboard.html"
DIFFS_DIR = ".cache/bs-cli/diffs"

MAX_DONE_ITEMS = 20
MAX_SESSION_LOG = 50


# --- Git Helpers ---

def _find_git_root(start: Path) -> Optional[Path]:
    """Walk up from start to find a .git directory."""
    current = start.resolve()
    for parent in [current] + list(current.parents):
        if (parent / ".git").is_dir():
            return parent
    return None


def _git_run(args: list[str], cwd: Path, timeout: int = 10) -> tuple[int, str, str]:
    """Run a git command safely. Returns (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return 1, "", str(e)


def _git_diff_summary(git_root: Path) -> dict[str, Any]:
    """Get a summary of unstaged + staged changes."""
    rc, stdout, _ = _git_run(["diff", "--stat", "HEAD"], git_root)
    if rc != 0:
        rc2, stdout2, _ = _git_run(["diff", "--stat"], git_root)
        stdout = stdout2 if rc2 == 0 else ""

    rc3, files_out, _ = _git_run(["diff", "--name-only", "HEAD"], git_root)
    if rc3 != 0:
        rc4, files_out, _ = _git_run(["diff", "--name-only"], git_root)
        if rc4 != 0:
            files_out = ""

    changed_files = [f for f in files_out.splitlines() if f.strip()]

    additions = deletions = 0
    for line in stdout.splitlines():
        for part in line.split(","):
            part = part.strip()
            if "insertion" in part:
                try:
                    additions = int(part.split()[0])
                except (ValueError, IndexError):
                    pass
            elif "deletion" in part:
                try:
                    deletions = int(part.split()[0])
                except (ValueError, IndexError):
                    pass

    return {
        "changed_files": changed_files,
        "file_count": len(changed_files),
        "additions": additions,
        "deletions": deletions,
        "summary": stdout[:500] if stdout else "",
    }


def _git_log_recent(git_root: Path, n: int = 10) -> list[dict]:
    """Return last N commits as list of dicts."""
    rc, stdout, _ = _git_run(
        ["log", f"-{n}", "--pretty=format:%H|%as|%s"],
        git_root,
    )
    if rc != 0 or not stdout:
        return []
    commits = []
    for line in stdout.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            commits.append({"hash": parts[0][:8], "date": parts[1], "message": parts[2]})
    return commits


def _git_status_short(git_root: Path) -> str:
    """Return short git status string."""
    rc, stdout, _ = _git_run(["status", "--short"], git_root)
    return stdout if rc == 0 else ""


def _offer_git_init(project_dir: Path) -> Optional[Path]:
    """Prompt user to init git repo. Returns git_root if initialized, else None."""
    import click
    if click.confirm(
        f"\n  No git repo detected in '{project_dir}'.\n  Initialize one now?",
        default=False,
    ):
        rc, stdout, stderr = _git_run(["init"], project_dir)
        if rc == 0:
            _git_run(["add", "."], project_dir)
            _git_run(["commit", "-m", "chore: initial commit (nexus journal init)"], project_dir)
            click.echo("  Git repo initialized with initial commit.")
            return project_dir
        else:
            click.echo(f"  Git init failed: {stderr}")
    return None


# --- Mtime Baseline (fallback when no git) ---

def _snapshot_mtimes(project_dir: Path) -> dict[str, float]:
    """Record modification times of source files for diff fallback."""
    mtimes: dict[str, float] = {}
    skip_dirs = {".git", "node_modules", "__pycache__", ".cache", ".nexus", ".venv", "venv"}
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            fp = Path(root) / f
            try:
                rel = str(fp.relative_to(project_dir))
                mtimes[rel] = fp.stat().st_mtime
            except (OSError, ValueError):
                pass
    return mtimes


def _diff_mtimes(baseline: dict[str, float], project_dir: Path) -> list[str]:
    """Return list of files changed since baseline was recorded."""
    changed = []
    skip_dirs = {".git", "node_modules", "__pycache__", ".cache", ".nexus", ".venv", "venv"}
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            fp = Path(root) / f
            try:
                rel = str(fp.relative_to(project_dir))
                mtime = fp.stat().st_mtime
                old_mtime = baseline.get(rel)
                if old_mtime is None or mtime > old_mtime + 0.5:
                    changed.append(rel)
            except (OSError, ValueError):
                pass
    return sorted(changed)


# --- State Read / Write ---

def _load_state(project_dir: Path) -> dict[str, Any]:
    """Load .nexus/state.json, returning defaults if missing."""
    state_path = project_dir / STATE_JSON
    defaults: dict[str, Any] = {
        "version": 1,
        "project": project_dir.name,
        "status": "IN PROGRESS",
        "session_number": 0,
        "session_start_time": None,
        "baseline_mtimes": {},
        "done": [],
        "next": [],
        "blockers": [],
        "session_log": [],
        "last_updated": None,
        "bootstrap_tier": None,
        "bootstrap_template": None,
    }
    if not state_path.exists():
        return defaults
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        for k, v in defaults.items():
            data.setdefault(k, v)
        return data
    except (json.JSONDecodeError, OSError):
        return defaults


def _save_state(project_dir: Path, state: dict[str, Any]) -> None:
    """Write state to .nexus/state.json and regenerate state.md."""
    nexus_dir = project_dir / NEXUS_DIR
    nexus_dir.mkdir(parents=True, exist_ok=True)

    state["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    json_path = project_dir / STATE_JSON
    json_path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")

    md_path = project_dir / STATE_MD
    md_path.write_text(_render_state_md(state), encoding="utf-8")


def _render_state_md(state: dict[str, Any]) -> str:
    """Render state dict as human/AI-readable Markdown."""
    lines = [
        "# Project State",
        f"_Last updated: {state.get('last_updated', 'unknown')} · "
        f"Session {state.get('session_number', 0)} · nexus-journal v0.1_",
        "",
        f"## Status: {state.get('status', 'UNKNOWN')}",
        "",
        "## What's Done (recent)",
    ]

    done = state.get("done", [])
    if done:
        for item in done[-MAX_DONE_ITEMS:]:
            lines.append(f"- {item}")
    else:
        lines.append("_Nothing logged yet._")

    lines += ["", "## What's Next"]
    next_items = state.get("next", [])
    if next_items:
        for item in next_items:
            lines.append(f"- [ ] {item}")
    else:
        lines.append("_Not set._")

    lines += ["", "## Blockers"]
    blockers = state.get("blockers", [])
    if blockers:
        for b in blockers:
            lines.append(f"- {b}")
    else:
        lines.append("_None_")

    session_log = state.get("session_log", [])
    if session_log:
        lines += ["", "## Session Log"]
        lines.append("| # | Date | Summary | Changed Files |")
        lines.append("|---|------|---------|---------------|")
        for entry in reversed(session_log[-MAX_SESSION_LOG:]):
            n = entry.get("session", "?")
            date = entry.get("date", "?")
            summary = entry.get("summary", "")[:60]
            fc = entry.get("file_count", 0)
            lines.append(f"| {n} | {date} | {summary} | {fc} |")

    return "\n".join(lines) + "\n"


# --- Diff snapshot helpers ---

def _save_diff_snapshot(project_dir: Path, session_n: int, diff_text: str) -> None:
    """Save a git diff snapshot to .cache/bs-cli/diffs/."""
    diffs_dir = project_dir / DIFFS_DIR
    diffs_dir.mkdir(parents=True, exist_ok=True)
    snap_path = diffs_dir / f"session-{session_n}.diff"
    try:
        snap_path.write_text(diff_text, encoding="utf-8")
    except OSError:
        pass


# --- Subcommand implementations ---

def _hooks_installed(git_root: Path) -> bool:
    """Return True if Nexus journal hooks are present in .git/hooks/."""
    hooks_dir = git_root / ".git" / "hooks"
    for name in ("post-commit", "pre-push"):
        hp = hooks_dir / name
        if not hp.exists():
            return False
        try:
            content = hp.read_text(encoding="utf-8")
        except OSError:
            return False
        if "nexus" not in content.lower() and "bs_cli" not in content.lower():
            return False
    return True


def _cmd_session_start(project_dir: Path, output_format: str) -> None:
    """Start a new session."""
    import click

    state = _load_state(project_dir)
    git_root = _find_git_root(project_dir)

    if git_root is None:
        git_root = _offer_git_init(project_dir)

    session_n = state["session_number"] + 1
    state["session_number"] = session_n
    state["session_start_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if git_root:
        rc, diff_text, _ = _git_run(["diff", "HEAD"], git_root)
        if rc != 0:
            rc2, diff_text, _ = _git_run(["diff"], git_root)
        _save_diff_snapshot(project_dir, session_n, diff_text or "")
        state["baseline_mtimes"] = {}
    else:
        state["baseline_mtimes"] = _snapshot_mtimes(project_dir)

    _save_state(project_dir, state)

    # Offer to install git hooks if a git repo exists but hooks are missing.
    # Human format only — non-interactive callers (json/yaml) skip the prompt.
    if git_root and output_format == "human" and not _hooks_installed(git_root):
        if click.confirm(
            "\n  Auto-tracking hooks not installed. Install them now?\n"
            "  (post-commit logs every commit; pre-push regenerates the dashboard)",
            default=True,
        ):
            _cmd_setup_hooks(project_dir, output_format)

    done_recent = state["done"][-5:] if state["done"] else []
    next_items = state["next"]

    msg_lines = [
        f"Session {session_n} started.",
        "",
        "Recent done:" if done_recent else "No previous done items.",
    ]
    for d in done_recent:
        msg_lines.append(f"  {d}")
    if next_items:
        msg_lines.append("What's next:")
        for n in next_items:
            msg_lines.append(f"  [ ] {n}")

    msg = "\n".join(msg_lines)

    if output_format == "human":
        click.echo(f"\n{'='*50}")
        click.echo(msg)
        click.echo(f"{'='*50}\n")
    else:
        emit(make_result(
            "journal-session-start",
            Status.PASS,
            message=f"Session {session_n} started.",
            details={
                "session": session_n,
                "git_root": str(git_root) if git_root else None,
                "recent_done": done_recent,
                "next": next_items,
            },
        ), OutputFormat(output_format))


def _cmd_session_end(project_dir: Path, output_format: str) -> None:
    """End session: detect changes, prompt for summary and next steps."""
    import click

    state = _load_state(project_dir)
    session_n = state.get("session_number", 1)
    git_root = _find_git_root(project_dir)

    if git_root:
        diff_info = _git_diff_summary(git_root)
        changed_files = diff_info["changed_files"]
        file_count = diff_info["file_count"]
        change_desc = (
            f"{file_count} file(s) changed (+{diff_info['additions']}/-{diff_info['deletions']})"
            if file_count else "No git changes detected."
        )
        commits = _git_log_recent(git_root, n=5)
    else:
        baseline = state.get("baseline_mtimes", {})
        changed_files = _diff_mtimes(baseline, project_dir)
        file_count = len(changed_files)
        change_desc = (
            f"{file_count} file(s) changed (mtime-based, approximate)"
            if file_count else "No file changes detected (mtime-based)."
        )
        commits = []

    click.echo(f"\n  Auto-detected changes: {change_desc}")
    if changed_files:
        for f in changed_files[:10]:
            click.echo(f"    - {f}")
        if len(changed_files) > 10:
            click.echo(f"    ... and {len(changed_files) - 10} more")

    summary = click.prompt("\n  Session summary (what was done)", default="").strip()
    if not summary:
        summary = change_desc

    next_raw = click.prompt("  What's next? (comma-separated tasks, or Enter to keep current)", default="").strip()
    blockers_raw = click.prompt("  Any blockers? (or Enter for none)", default="").strip()

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    date_short = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if summary:
        done_entry = f"[{date_short} S{session_n}] {summary}"
        state["done"].append(done_entry)

    if next_raw:
        state["next"] = [t.strip() for t in next_raw.split(",") if t.strip()]

    if blockers_raw:
        state["blockers"] = [b.strip() for b in blockers_raw.split(",") if b.strip()]
    elif not blockers_raw and state.get("blockers"):
        clear = click.confirm("  Clear existing blockers?", default=False)
        if clear:
            state["blockers"] = []

    session_entry = {
        "session": session_n,
        "date": date_short,
        "summary": summary[:80],
        "file_count": file_count,
        "changed_files": changed_files[:20],
        "commits": commits,
        "end_time": timestamp,
    }
    state["session_log"].append(session_entry)
    state["baseline_mtimes"] = {}

    _save_state(project_dir, state)

    click.echo(f"\n  Session {session_n} closed. State written to {STATE_MD}")
    click.echo(f"  Run 'journal export' to refresh the dashboard.\n")

    emit(make_result(
        "journal-session-end",
        Status.PASS,
        message=f"Session {session_n} closed.",
        details={
            "session": session_n,
            "summary": summary,
            "file_count": file_count,
            "changed_files": changed_files[:10],
        },
    ), OutputFormat(output_format)) if output_format != "human" else None


def _cmd_log(project_dir: Path, message: str, output_format: str) -> None:
    """Append a one-line log entry (non-interactive)."""
    state = _load_state(project_dir)

    # Auto-bootstrap session 1 if no session has been started yet.
    # Without this, hook-driven logs accumulate under S0 and the dashboard
    # shows session_start_time=null forever.
    if state.get("session_number", 0) < 1:
        state["session_number"] = 1
        state["session_start_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        git_root = _find_git_root(project_dir)
        if not git_root:
            state["baseline_mtimes"] = _snapshot_mtimes(project_dir)

    session_n = state["session_number"]
    date_short = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry = f"[{date_short} S{session_n}] {message.strip()}"
    state["done"].append(entry)
    _save_state(project_dir, state)

    emit(make_result(
        "journal-log",
        Status.PASS,
        message=f"Logged: {entry}",
    ), OutputFormat(output_format))


def _cmd_status(project_dir: Path, output_format: str) -> None:
    """Display current project state."""
    import click

    state = _load_state(project_dir)
    md_path = project_dir / STATE_MD

    if output_format == "human":
        if md_path.exists():
            click.echo(md_path.read_text(encoding="utf-8"))
        else:
            click.echo("  No .nexus/state.md found. Run 'journal session-start' to initialize.")
    else:
        emit(make_result(
            "journal-status",
            Status.INFO,
            message=f"Project: {state.get('project', '?')} | Status: {state.get('status', '?')} | Session: {state.get('session_number', 0)}",
            details={
                "status": state.get("status"),
                "session": state.get("session_number"),
                "last_updated": state.get("last_updated"),
                "done_count": len(state.get("done", [])),
                "next_count": len(state.get("next", [])),
                "blockers": state.get("blockers", []),
                "recent_done": state.get("done", [])[-5:],
                "next": state.get("next", []),
            },
        ), OutputFormat(output_format))


def _cmd_diff(project_dir: Path, output_format: str) -> None:
    """Show file changes since session start."""
    import click

    state = _load_state(project_dir)
    git_root = _find_git_root(project_dir)

    if git_root:
        diff_info = _git_diff_summary(git_root)
        changed = diff_info["changed_files"]
        desc = f"{diff_info['file_count']} file(s) changed (+{diff_info['additions']}/-{diff_info['deletions']} lines)"
        source = "git"
    else:
        baseline = state.get("baseline_mtimes", {})
        if not baseline:
            click.echo("  No baseline recorded. Run 'journal session-start' first.")
            return
        changed = _diff_mtimes(baseline, project_dir)
        desc = f"{len(changed)} file(s) changed (mtime-based, approximate)"
        source = "mtime"

    if output_format == "human":
        click.echo(f"\n  {desc} [{source}]")
        for f in changed:
            click.echo(f"    - {f}")
        click.echo()
    else:
        emit(make_result(
            "journal-diff",
            Status.INFO,
            message=desc,
            details={"source": source, "changed_files": changed, "file_count": len(changed)},
        ), OutputFormat(output_format))


def _cmd_export(project_dir: Path, output_format: str) -> None:
    """Generate .nexus/state-dashboard.html."""
    from nexus.cli.tools.journal_dashboard import generate_dashboard

    state = _load_state(project_dir)
    git_root = _find_git_root(project_dir)

    git_commits = _git_log_recent(git_root, n=10) if git_root else []
    git_status = _git_status_short(git_root) if git_root else None

    audit_entries = _load_audit_log(project_dir)

    html_path = project_dir / DASHBOARD_HTML
    generate_dashboard(
        state=state,
        git_commits=git_commits,
        git_status=git_status,
        audit_entries=audit_entries,
        output_path=html_path,
    )

    emit(make_result(
        "journal-export",
        Status.PASS,
        message=f"Dashboard exported to {DASHBOARD_HTML}",
        details={"path": str(html_path)},
    ), OutputFormat(output_format))


def _load_audit_log(project_dir: Path, last_n: int = 20) -> list[dict]:
    """Load last N entries from audit.jsonl."""
    audit_path = project_dir / ".cache" / "bs-cli" / "audit.jsonl"
    if not audit_path.exists():
        return []
    try:
        lines = audit_path.read_text(encoding="utf-8").splitlines()
        entries = []
        for line in lines[-last_n:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return entries
    except OSError:
        return []


# --- Git hook templates ---

_POST_COMMIT_HOOK = """\
#!/bin/sh
# Nexus journal — auto-log on every git commit
NEXUS_ROOT="$(git rev-parse --show-toplevel)"
python "$NEXUS_ROOT/nexus/cli/bs_cli.py" journal log "git commit: $(git log -1 --pretty=%s)" \\
  --project-dir "$NEXUS_ROOT" --format json > /dev/null 2>&1 || true
"""

_PRE_PUSH_HOOK = """\
#!/bin/sh
# Nexus journal — export dashboard before every push
NEXUS_ROOT="$(git rev-parse --show-toplevel)"
python "$NEXUS_ROOT/nexus/cli/bs_cli.py" journal export \\
  --project-dir "$NEXUS_ROOT" --format json > /dev/null 2>&1 || true
"""


def _cmd_setup_hooks(project_dir: Path, output_format: str) -> None:
    """Install git hooks for automatic journal tracking."""
    import click
    import stat

    git_root = _find_git_root(project_dir)
    if git_root is None:
        emit(make_result(
            "journal-setup-hooks",
            Status.FAIL,
            message="No git repo found. Run 'journal session-start' first to init one.",
        ), OutputFormat(output_format))
        return

    hooks_dir = git_root / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    installed = []
    skipped = []

    hooks = {
        "post-commit": _POST_COMMIT_HOOK,
        "pre-push": _PRE_PUSH_HOOK,
    }

    for hook_name, hook_content in hooks.items():
        hook_path = hooks_dir / hook_name
        if hook_path.exists():
            existing = hook_path.read_text(encoding="utf-8")
            if "nexus" in existing.lower() or "bs_cli" in existing.lower():
                skipped.append(f"{hook_name} (already installed)")
                continue
            if output_format == "human":
                overwrite = click.confirm(
                    f"  Hook '{hook_name}' already exists (not by Nexus). Overwrite?",
                    default=False,
                )
                if not overwrite:
                    skipped.append(f"{hook_name} (kept existing)")
                    continue

        hook_path.write_text(hook_content, encoding="utf-8")
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        installed.append(hook_name)

    msg_parts = []
    if installed:
        msg_parts.append(f"Installed: {', '.join(installed)}")
    if skipped:
        msg_parts.append(f"Skipped: {', '.join(skipped)}")

    message = " | ".join(msg_parts) if msg_parts else "Nothing to do."

    if output_format == "human":
        click.echo(f"\n  Git hooks path: {hooks_dir}")
        for h in installed:
            click.echo(f"  [ok] {h}")
        for s in skipped:
            click.echo(f"  - {s}")
        click.echo()
        click.echo("  post-commit : auto-logs commit message to .nexus/state.md")
        click.echo("  pre-push    : regenerates state-dashboard.html before push")
        click.echo()

    emit(make_result(
        "journal-setup-hooks",
        Status.PASS if installed else Status.WARN,
        message=message,
        details={"hooks_dir": str(hooks_dir), "installed": installed, "skipped": skipped},
    ), OutputFormat(output_format)) if output_format != "human" else None


# --- CLI dispatcher ---

def run_journal(subcommand: str, args: tuple, output_format: str, project_dir: str) -> None:
    """Dispatch journal subcommands."""
    pd = Path(project_dir).resolve()

    if subcommand == "session-start":
        _cmd_session_start(pd, output_format)
    elif subcommand == "session-end":
        _cmd_session_end(pd, output_format)
    elif subcommand == "log":
        msg = " ".join(args) if args else ""
        if not msg:
            emit(make_result("journal-log", Status.FAIL, message="Usage: journal log '<message>'"), OutputFormat(output_format))
            return
        _cmd_log(pd, msg, output_format)
    elif subcommand == "status":
        _cmd_status(pd, output_format)
    elif subcommand == "diff":
        _cmd_diff(pd, output_format)
    elif subcommand == "export":
        _cmd_export(pd, output_format)
    elif subcommand == "setup-hooks":
        _cmd_setup_hooks(pd, output_format)
    else:
        emit(make_result(
            "journal",
            Status.FAIL,
            message=f"Unknown subcommand: {subcommand}",
        ), OutputFormat(output_format))
