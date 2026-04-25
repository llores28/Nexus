"""
Project Journal Tool — cross-session project state tracking.

Subcommands:
  session-start   — start a new session, show last state, offer git init if missing
  session-end     — summarize changes (diff-based), prompt for next steps, write state
  log             — append a one-line event (non-interactive, Cascade-friendly)
                    Auto-rolls the session if it is stale (idle >4h, new UTC date,
                    or branch changed) so session_log stays populated even when
                    callers never invoke session-end.
  status          — display current .nexus/state.md
  export          — generate .nexus/state-dashboard.html (file heatmap derived
                    from `git log --name-only` since session start)
  diff            — show auto-detected file changes since session start
  next            — manage the next-tasks list (add|done|list|clear)
  blocker         — manage the blockers list (add|clear|list)
  setup-hooks     — install/upgrade git hooks; pass --force to overwrite Nexus hooks
"""

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from nexus.cli.utils import (
    OutputFormat, Status, emit, make_result, find_project_root, _safe_echo,
)


# --- Constants ---

NEXUS_DIR = ".nexus"
STATE_JSON = ".nexus/state.json"
STATE_MD = ".nexus/state.md"
STATE_SUMMARY_MD = ".nexus/state-summary.md"
DASHBOARD_HTML = ".nexus/state-dashboard.html"
DAILY_JOURNAL_DIR = ".nexus/journal"  # append-only system of record (Phase 3)
DECISIONS_DIR = "docs/decisions"  # MADR-style ADRs (committed by default)
DIFFS_DIR = ".cache/bs-cli/diffs"
HOOK_LOG = ".cache/bs-cli/hook.log"

# Cross-tool integration files (managed by `journal init-agents`)
AGENTS_MD = "AGENTS.md"
CURSOR_RULE = ".cursor/rules/state.mdc"
NEXUS_AGENTS_BEGIN = "<!-- nexus:state:begin -->"
NEXUS_AGENTS_END = "<!-- nexus:state:end -->"

MAX_DONE_ITEMS = 20  # rendered cap in state.md
MAX_SESSION_LOG = 50
MAX_SUMMARY_DONE = 15  # entries shown in state-summary.md
MAX_DONE_KEEP = 100  # storage cap on state.json["done"] (daily files are the system of record)
SESSION_IDLE_HOURS = 4.0  # auto-roll session after this much idle time
HOOK_VERSION = 2  # bump when hook templates change incompatibly

# Conventional Commits — order shown in rendered state.md
CC_TYPE_ORDER = [
    "feat", "fix", "perf", "refactor", "docs", "test",
    "chore", "ci", "build", "style", "revert", "other",
]
CC_TYPE_LABEL = {
    "feat": "Features", "fix": "Fixes", "perf": "Performance",
    "refactor": "Refactoring", "docs": "Docs", "test": "Tests",
    "chore": "Chores", "ci": "CI", "build": "Build", "style": "Style",
    "revert": "Reverts", "other": "Other",
}
_CC_PATTERN = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(\([^)]+\))?(!)?:\s*(.+)$",
    re.IGNORECASE,
)


# --- Git Helpers ---

def _find_git_root(start: Path) -> Optional[Path]:
    """Walk up from start to find a .git directory."""
    current = start.resolve()
    for parent in [current] + list(current.parents):
        if (parent / ".git").is_dir():
            return parent
    return None


def _resolve_git_root(project_dir: Path) -> Optional[Path]:
    """Find the most relevant git root for project_dir.

    Strategy (handles nested repos where workspace root ≠ git root):
    1. Walk upward from project_dir — covers the common case.
    2. If not found, scan one level of subdirectories for a .git directory.
       This catches projects like TextBlast/ that live inside a non-git workspace.
    3. Return the upward result when both are found (it is always the correct
       repo for project_dir itself).
    """
    upward = _find_git_root(project_dir)
    if upward is not None:
        return upward
    # Scan immediate subdirectories for a nested git repo
    try:
        for sub in sorted(project_dir.iterdir()):
            if sub.is_dir() and (sub / ".git").is_dir():
                return sub
    except (OSError, PermissionError):
        pass
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


def _git_current_branch(git_root: Path) -> Optional[str]:
    """Return current branch name (or None on detached HEAD / failure)."""
    rc, out, _ = _git_run(["rev-parse", "--abbrev-ref", "HEAD"], git_root)
    if rc != 0 or not out or out == "HEAD":
        return None
    return out


def _git_files_since(git_root: Path, since_iso: str) -> list[str]:
    """Return distinct file paths touched by commits since the given ISO timestamp."""
    rc, out, _ = _git_run(
        ["log", f"--since={since_iso}", "--name-only", "--pretty=format:"],
        git_root,
    )
    if rc != 0 or not out:
        return []
    return sorted({line.strip() for line in out.splitlines() if line.strip()})


def _git_commits_since(git_root: Path, since_iso: str, n: int = 20) -> list[dict]:
    """Return up to N commits since since_iso as list of {hash, date, message} dicts."""
    rc, out, _ = _git_run(
        ["log", f"--since={since_iso}", f"-{n}", "--pretty=format:%H|%as|%s"],
        git_root,
    )
    if rc != 0 or not out:
        return []
    commits = []
    for line in out.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            commits.append({"hash": parts[0][:8], "date": parts[1], "message": parts[2]})
    return commits


def _git_file_churn(git_root: Path, since_iso: Optional[str] = None,
                    max_commits: int = 100) -> dict[str, int]:
    """Return {file_path: commit_count} for files touched in the window.

    Falls back to last `max_commits` commits if since_iso is None.
    Used to drive the dashboard heatmap directly from git history rather than
    the (potentially stale) session_log.
    """
    if since_iso:
        args = ["log", f"--since={since_iso}", "--name-only", "--pretty=format:%n"]
    else:
        args = ["log", f"-{max_commits}", "--name-only", "--pretty=format:%n"]
    rc, out, _ = _git_run(args, git_root)
    if rc != 0 or not out:
        return {}
    counts: dict[str, int] = {}
    for line in out.splitlines():
        f = line.strip()
        if f:
            counts[f] = counts.get(f, 0) + 1
    return counts


# --- Conventional Commits parsing ---

def _parse_conventional_commit(subject: str) -> Optional[dict]:
    """Parse a Conventional Commits subject. Returns {type, scope, breaking, summary} or None.

    Tolerates the `git commit: ` prefix that the post-commit hook prepends.
    """
    s = subject.strip()
    low = s.lower()
    if low.startswith("git commit:"):
        s = s[len("git commit:"):].strip()
    m = _CC_PATTERN.match(s)
    if not m:
        return None
    return {
        "type": m.group(1).lower(),
        "scope": m.group(2)[1:-1] if m.group(2) else None,
        "breaking": bool(m.group(3)),
        "summary": m.group(4).strip(),
    }


def _classify_done_item(item: str) -> str:
    """Return Conventional Commit type for a done-list item, or 'other'."""
    payload = item.split("] ", 1)[-1] if "] " in item else item
    parsed = _parse_conventional_commit(payload)
    return parsed["type"] if parsed else "other"


def _group_done_by_type(items: list[str]) -> list[tuple[str, list[str]]]:
    """Group done items by Conventional Commit type, in display order.

    Returns list of (label, items) for non-empty groups only.
    """
    groups: dict[str, list[str]] = {t: [] for t in CC_TYPE_ORDER}
    for item in items:
        groups[_classify_done_item(item)].append(item)
    return [(CC_TYPE_LABEL[t], groups[t]) for t in CC_TYPE_ORDER if groups[t]]


# --- Session lifecycle helpers ---

def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 string (with or without trailing Z) to a tz-aware datetime."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _should_roll_session(state: dict, git_root: Optional[Path]) -> tuple[bool, str]:
    """Decide whether the current session is stale and should auto-close.

    Triggers (any one):
      - >= SESSION_IDLE_HOURS since session start
      - UTC date has changed since session start
      - branch changed since session start (when git is available)

    Returns (should_roll, reason). Reason is empty when not rolling.
    """
    start_dt = _parse_iso(state.get("session_start_time"))
    if start_dt is None:
        return False, ""
    now = datetime.now(timezone.utc)
    hours_idle = (now - start_dt).total_seconds() / 3600.0
    if hours_idle >= SESSION_IDLE_HOURS:
        return True, f"idle {hours_idle:.1f}h"
    if now.date() != start_dt.date():
        return True, f"new date ({now.strftime('%Y-%m-%d')})"
    if git_root:
        current = _git_current_branch(git_root)
        recorded = state.get("session_branch")
        if recorded and current and current != recorded:
            return True, f"branch {recorded}->{current}"
    return False, ""


def _close_session(state: dict, git_root: Optional[Path], reason: str) -> None:
    """Close the current session non-interactively by appending a session_log entry.

    Pulls activity (commits + touched files) from git when available, so the
    session_log stays populated even when callers never run session-end.
    """
    session_n = state.get("session_number", 0)
    if session_n < 1:
        return

    start_iso = state.get("session_start_time")
    if git_root and start_iso:
        files = _git_files_since(git_root, start_iso)
        commits = _git_commits_since(git_root, start_iso, n=20)
    else:
        files, commits = [], []

    if commits:
        head = "; ".join(c.get("message", "")[:40] for c in commits[:3])
        summary = f"{len(commits)} commit(s): {head}"
    else:
        summary = f"auto-closed ({reason})"

    end_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state.setdefault("session_log", []).append({
        "session": session_n,
        "date": end_iso[:10],
        "summary": summary[:120],
        "file_count": len(files),
        "changed_files": files[:30],
        "commits": commits[:10],
        "branch": state.get("session_branch"),
        "end_time": end_iso,
        "auto_closed": True,
        "close_reason": reason,
    })


def _open_session(state: dict, git_root: Optional[Path], project_dir: Path) -> None:
    """Open a new session non-interactively. Bumps counter, stamps start time + branch."""
    state["session_number"] = state.get("session_number", 0) + 1
    state["session_start_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state["session_branch"] = _git_current_branch(git_root) if git_root else None
    if not git_root:
        state["baseline_mtimes"] = _snapshot_mtimes(project_dir)
    else:
        state["baseline_mtimes"] = {}


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


# --- Daily journal (append-only system of record) ---

def _append_daily_journal(project_dir: Path, message: str, branch: Optional[str],
                          session_n: int, when: Optional[datetime] = None) -> Optional[Path]:
    """Append an entry to .nexus/journal/YYYY-MM/DD.md.

    The daily file is the system of record — state.json["done"] is a rolling
    buffer (MAX_DONE_KEEP), but daily files are append-only and never trimmed.
    Returns the path written to (or None on failure).
    """
    now = when or datetime.now(timezone.utc)
    daily_dir = project_dir / DAILY_JOURNAL_DIR / now.strftime("%Y-%m")
    try:
        daily_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    daily_path = daily_dir / f"{now.strftime('%d')}.md"

    branch_tag = f"[{branch}] " if branch else ""
    line = f"- `{now.strftime('%H:%M:%S')}` S{session_n} {branch_tag}{message.strip()}\n"

    try:
        if not daily_path.exists():
            daily_path.write_text(
                f"# {now.strftime('%Y-%m-%d')}\n\n_Append-only journal · entries from `nexus journal` CLI._\n\n",
                encoding="utf-8",
            )
        with daily_path.open("a", encoding="utf-8") as f:
            f.write(line)
        return daily_path
    except OSError:
        return None


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
        "session_branch": None,
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
    """Write state to .nexus/state.json and regenerate state.md.

    Trims state.done to the last MAX_DONE_KEEP entries — older entries are
    preserved permanently in the daily journal files (.nexus/journal/YYYY-MM/DD.md),
    so this trim is non-destructive as long as `_append_daily_journal` ran.
    """
    nexus_dir = project_dir / NEXUS_DIR
    nexus_dir.mkdir(parents=True, exist_ok=True)

    state["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    done = state.get("done", [])
    if len(done) > MAX_DONE_KEEP:
        state["done"] = done[-MAX_DONE_KEEP:]

    json_path = project_dir / STATE_JSON
    json_path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")

    md_path = project_dir / STATE_MD
    md_path.write_text(_render_state_md(state), encoding="utf-8")


def _render_state_md(state: dict[str, Any]) -> str:
    """Render state dict as human/AI-readable Markdown."""
    branch = state.get("session_branch")
    branch_suffix = f" · branch={branch}" if branch else ""
    lines = [
        "# Project State",
        f"_Last updated: {state.get('last_updated', 'unknown')} · "
        f"Session {state.get('session_number', 0)}{branch_suffix} · nexus-journal v0.2_",
        "",
        f"## Status: {state.get('status', 'UNKNOWN')}",
        "",
        f"## What's Done (last {MAX_DONE_ITEMS})",
    ]

    done = state.get("done", [])
    if done:
        grouped = _group_done_by_type(done[-MAX_DONE_ITEMS:])
        for label, items in grouped:
            lines.append("")
            lines.append(f"### {label} ({len(items)})")
            for item in items:
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

_HOOK_VERSION_TAG = f"nexus-journal-hook v{HOOK_VERSION}"


def _hooks_installed(git_root: Path) -> bool:
    """Return True if current-version Nexus journal hooks are present.

    'Current version' is defined by the _HOOK_VERSION_TAG marker. Older Nexus
    hooks (no version tag) are reported as NOT installed so callers know an
    upgrade is needed.
    """
    hooks_dir = git_root / ".git" / "hooks"
    for name in ("post-commit", "pre-push"):
        hp = hooks_dir / name
        if not hp.exists():
            return False
        try:
            content = hp.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False
        if _HOOK_VERSION_TAG not in content:
            return False
    return True


def _hook_status(hook_path: Path) -> str:
    """Classify a hook file: 'missing', 'current', 'outdated', or 'foreign'.

    Falls back to a permissive read (errors='replace') if utf-8 decoding fails
    so a foreign hook authored in cp1252/latin-1 still classifies as 'foreign'
    or 'outdated' rather than crashing the installer.
    """
    if not hook_path.exists():
        return "missing"
    try:
        content = hook_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        try:
            content = hook_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "foreign"
    if _HOOK_VERSION_TAG in content:
        return "current"
    if "nexus" in content.lower() or "bs_cli" in content.lower():
        return "outdated"
    return "foreign"


def _cmd_session_start(project_dir: Path, output_format: str) -> None:
    """Start a new session."""
    import click

    state = _load_state(project_dir)
    git_root = _resolve_git_root(project_dir)

    if git_root is None:
        git_root = _offer_git_init(project_dir)

    # If a previous session is still open and stale, close it first so the
    # session_log gets an entry rather than orphaning the old session.
    should_roll, reason = _should_roll_session(state, git_root)
    if should_roll:
        _close_session(state, git_root, reason)

    _open_session(state, git_root, project_dir)
    session_n = state["session_number"]

    if git_root:
        rc, diff_text, _ = _git_run(["diff", "HEAD"], git_root)
        if rc != 0:
            rc2, diff_text, _ = _git_run(["diff"], git_root)
        _save_diff_snapshot(project_dir, session_n, diff_text or "")

    _save_state(project_dir, state)

    # Offer to install git hooks if a git repo exists but hooks are missing.
    # Human format only — non-interactive callers (json/yaml) skip the prompt.
    if git_root and output_format == "human" and not _hooks_installed(git_root) and git_root == _find_git_root(project_dir):
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
    git_root = _resolve_git_root(project_dir)
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
    # Mark the session as closed so the next `journal log` opens a fresh
    # session rather than tagging entries with this (now-finalized) session.
    state["session_start_time"] = None

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


def _cmd_log(project_dir: Path, message: str, output_format: str, auto_export: bool = True) -> None:
    """Append a one-line log entry (non-interactive).

    Auto-rolls the session before logging when stale (idle, new day, or branch
    changed). This is the key fix for callers that never invoke session-end —
    without it, every commit accumulates under one frozen session forever.
    """
    state = _load_state(project_dir)
    git_root = _resolve_git_root(project_dir)

    if state.get("session_number", 0) < 1 or state.get("session_start_time") is None:
        # First-ever log, or the previous session was explicitly closed by
        # `journal session-end`. Either way, open a fresh session.
        _open_session(state, git_root, project_dir)
        rolled_reason = None
    else:
        should_roll, reason = _should_roll_session(state, git_root)
        if should_roll:
            _close_session(state, git_root, reason)
            _open_session(state, git_root, project_dir)
            rolled_reason = reason
        else:
            rolled_reason = None

    session_n = state["session_number"]
    branch = state.get("session_branch")
    now = datetime.now(timezone.utc)
    date_short = now.strftime("%Y-%m-%d")
    branch_tag = f" {branch}" if branch else ""
    entry = f"[{date_short} S{session_n}{branch_tag}] {message.strip()}"
    state["done"].append(entry)

    # Append to the daily journal first (system of record), THEN trim+save state.
    # If the daily write fails, we still save state — but the trim cap should
    # not destroy entries that are still in flight, so MAX_DONE_KEEP=100
    # gives plenty of headroom even if a daily write was missed.
    daily_path = _append_daily_journal(project_dir, message.strip(), branch, session_n, now)

    _save_state(project_dir, state)

    msg = f"Logged: {entry}"
    if rolled_reason:
        msg += f" (auto-rolled session: {rolled_reason})"
    emit(make_result(
        "journal-log",
        Status.PASS,
        message=msg,
        details={
            "session": session_n,
            "branch": branch,
            "rolled": bool(rolled_reason),
            "reason": rolled_reason,
            "daily_file": str(daily_path) if daily_path else None,
        },
    ), OutputFormat(output_format))

    # Auto-export the dashboard so it never goes stale silently.
    # Suppress with NEXUS_NO_AUTO_EXPORT=1 (e.g. in tight CI loops).
    if auto_export and os.environ.get("NEXUS_NO_AUTO_EXPORT", "") not in ("1", "true", "yes"):
        try:
            _cmd_export(project_dir, "json")
        except Exception:
            pass


def _cmd_next(project_dir: Path, args: tuple, output_format: str) -> None:
    """Manage the 'next tasks' list non-interactively.

    journal next add <task...>     append a task
    journal next done <idx|substr> mark first match as done (moves to 'done')
    journal next list              show current next list
    journal next clear             remove all
    """
    state = _load_state(project_dir)
    next_list = list(state.get("next", []))
    action = args[0] if args else "list"
    rest = args[1:]

    if action == "add":
        task = " ".join(rest).strip()
        if not task:
            emit(make_result("journal-next", Status.FAIL,
                             message="Usage: journal next add <task>"),
                 OutputFormat(output_format))
            return
        if task in next_list:
            emit(make_result("journal-next-add", Status.WARN,
                             message=f"Already queued: {task}"),
                 OutputFormat(output_format))
            return
        next_list.append(task)
        state["next"] = next_list
        _save_state(project_dir, state)
        emit(make_result("journal-next-add", Status.PASS,
                         message=f"Added: {task}",
                         details={"next": next_list}),
             OutputFormat(output_format))

    elif action == "done":
        target = " ".join(rest).strip()
        if not target:
            emit(make_result("journal-next", Status.FAIL,
                             message="Usage: journal next done <index|substring>"),
                 OutputFormat(output_format))
            return
        completed: Optional[str] = None
        try:
            idx = int(target)
            if 0 <= idx < len(next_list):
                completed = next_list.pop(idx)
        except ValueError:
            tl = target.lower()
            for i, item in enumerate(next_list):
                if tl in item.lower():
                    completed = next_list.pop(i)
                    break
        if completed is None:
            emit(make_result("journal-next-done", Status.FAIL,
                             message=f"No matching task: {target}"),
                 OutputFormat(output_format))
            return
        # Auto-bootstrap a session if needed so the entry has a valid Sn tag.
        if state.get("session_number", 0) < 1:
            git_root = _resolve_git_root(project_dir)
            _open_session(state, git_root, project_dir)
        session_n = state["session_number"]
        branch = state.get("session_branch")
        now = datetime.now(timezone.utc)
        date_short = now.strftime("%Y-%m-%d")
        branch_tag = f" {branch}" if branch else ""
        message = f"done: {completed}"
        state["done"].append(f"[{date_short} S{session_n}{branch_tag}] {message}")
        state["next"] = next_list
        _append_daily_journal(project_dir, message, branch, session_n, now)
        _save_state(project_dir, state)
        emit(make_result("journal-next-done", Status.PASS,
                         message=f"Completed: {completed}",
                         details={"next": next_list, "branch": branch}),
             OutputFormat(output_format))

    elif action == "list":
        emit(make_result("journal-next-list", Status.INFO,
                         message=f"{len(next_list)} task(s) queued",
                         details={"next": next_list}),
             OutputFormat(output_format))

    elif action == "clear":
        state["next"] = []
        _save_state(project_dir, state)
        emit(make_result("journal-next-clear", Status.PASS,
                         message="Cleared next list."),
             OutputFormat(output_format))

    else:
        emit(make_result("journal-next", Status.FAIL,
                         message=f"Unknown action: {action}. Use add|done|list|clear."),
             OutputFormat(output_format))


def _cmd_blocker(project_dir: Path, args: tuple, output_format: str) -> None:
    """Manage the blockers list non-interactively.

    journal blocker add <text...>  append a blocker
    journal blocker clear          remove all
    journal blocker list           show current blockers
    """
    state = _load_state(project_dir)
    blockers = list(state.get("blockers", []))
    action = args[0] if args else "list"
    rest = args[1:]

    if action == "add":
        text = " ".join(rest).strip()
        if not text:
            emit(make_result("journal-blocker", Status.FAIL,
                             message="Usage: journal blocker add <text>"),
                 OutputFormat(output_format))
            return
        if text in blockers:
            emit(make_result("journal-blocker-add", Status.WARN,
                             message=f"Already recorded: {text}"),
                 OutputFormat(output_format))
            return
        blockers.append(text)
        state["blockers"] = blockers
        _save_state(project_dir, state)
        emit(make_result("journal-blocker-add", Status.PASS,
                         message=f"Added blocker: {text}",
                         details={"blockers": blockers}),
             OutputFormat(output_format))

    elif action == "clear":
        state["blockers"] = []
        _save_state(project_dir, state)
        emit(make_result("journal-blocker-clear", Status.PASS,
                         message="Cleared blockers."),
             OutputFormat(output_format))

    elif action == "list":
        emit(make_result("journal-blocker-list", Status.INFO,
                         message=f"{len(blockers)} blocker(s)",
                         details={"blockers": blockers}),
             OutputFormat(output_format))

    else:
        emit(make_result("journal-blocker", Status.FAIL,
                         message=f"Unknown action: {action}. Use add|clear|list."),
             OutputFormat(output_format))


def _cmd_status(project_dir: Path, output_format: str) -> None:
    """Display current project state."""
    import click

    state = _load_state(project_dir)
    md_path = project_dir / STATE_MD

    if output_format == "human":
        if md_path.exists():
            _safe_echo(md_path.read_text(encoding="utf-8"))
        else:
            _safe_echo("  No .nexus/state.md found. Run 'journal session-start' to initialize.")
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
    git_root = _resolve_git_root(project_dir)
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
    """Generate .nexus/state-dashboard.html.

    Heatmap is driven from `git log --name-only` rather than session_log so it
    stays meaningful even when session-end is never called.
    """
    from nexus.cli.tools.journal_dashboard import generate_dashboard

    state = _load_state(project_dir)
    git_root = _resolve_git_root(project_dir)

    git_commits = _git_log_recent(git_root, n=10) if git_root else []
    git_status = _git_status_short(git_root) if git_root else None

    if git_root:
        churn = _git_file_churn(git_root, since_iso=None, max_commits=100)
    else:
        churn = {}
    top_files = sorted(churn.items(), key=lambda x: -x[1])[:10]

    audit_entries = _load_audit_log(project_dir)

    html_path = project_dir / DASHBOARD_HTML
    generate_dashboard(
        state=state,
        git_commits=git_commits,
        git_status=git_status,
        audit_entries=audit_entries,
        output_path=html_path,
        top_files=top_files,
    )

    # Also regenerate the AI-optimized summary so AGENTS.md / Cursor reads
    # stay current without a separate command. Auto-export from `journal log`
    # therefore keeps both surfaces (humans + agents) in sync on every commit.
    summary_path, summary_lines = _write_state_summary(project_dir, state, git_root)

    emit(make_result(
        "journal-export",
        Status.PASS,
        message=f"Dashboard + summary exported ({summary_lines} summary lines)",
        details={
            "dashboard_path": str(html_path),
            "summary_path": str(summary_path),
            "summary_lines": summary_lines,
        },
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


# --- Git hook factories (paths baked at install-time) ---

def _make_post_commit_hook(bs_cli_path: str, project_dir: str, log_path: str) -> str:
    """Return a post-commit hook script with absolute paths baked in.

    Stderr is appended to `log_path` instead of /dev/null so silent failures
    (wrong python, missing module) become diagnosable. Stdout still goes to
    /dev/null because journal log emits JSON that would spam the log file.
    """
    return f"""\
#!/bin/sh
# {_HOOK_VERSION_TAG} — auto-log on every git commit
PYTHONIOENCODING=utf-8 python "{bs_cli_path}" journal log "git commit: $(git log -1 --pretty=%s)" \\
  --project-dir "{project_dir}" --format json >/dev/null 2>>"{log_path}" || true
"""


def _make_pre_push_hook(bs_cli_path: str, project_dir: str, log_path: str) -> str:
    """Return a pre-push hook script with absolute paths baked in."""
    return f"""\
#!/bin/sh
# {_HOOK_VERSION_TAG} — regenerate dashboard before every push
PYTHONIOENCODING=utf-8 python "{bs_cli_path}" journal export \\
  --project-dir "{project_dir}" --format json >/dev/null 2>>"{log_path}" || true
"""


def _make_post_commit_hook_bat(bs_cli_path: str, project_dir: str, log_path: str) -> str:
    """Windows .bat companion for post-commit (used when sh is unavailable)."""
    return (
        "@echo off\r\n"
        f"rem {_HOOK_VERSION_TAG} — auto-log on every git commit\r\n"
        f'set PYTHONIOENCODING=utf-8\r\n'
        f'for /f "tokens=*" %%m in (\'git log -1 --pretty=%%s\') do (\r\n'
        f'  python "{bs_cli_path}" journal log "git commit: %%m" '
        f'--project-dir "{project_dir}" --format json >nul 2>>"{log_path}"\r\n'
        f')\r\n'
    )


def _make_pre_push_hook_bat(bs_cli_path: str, project_dir: str, log_path: str) -> str:
    """Windows .bat companion for pre-push."""
    return (
        "@echo off\r\n"
        f"rem {_HOOK_VERSION_TAG} — regenerate dashboard before every push\r\n"
        f'set PYTHONIOENCODING=utf-8\r\n'
        f'python "{bs_cli_path}" journal export '
        f'--project-dir "{project_dir}" --format json >nul 2>>"{log_path}"\r\n'
    )


def _cmd_setup_hooks(project_dir: Path, output_format: str, force: bool = False) -> None:
    """Install or upgrade git hooks for automatic journal tracking.

    Behavior matrix per existing hook:
      missing  -> install
      current  -> skip (or reinstall when force=True)
      outdated -> upgrade in place (treat older Nexus hooks as eligible)
      foreign  -> prompt (human) / skip with note (json) unless force=True
    """
    import click
    import stat
    import sys

    git_root = _resolve_git_root(project_dir)
    if git_root is None:
        emit(make_result(
            "journal-setup-hooks",
            Status.FAIL,
            message="No git repo found. Run 'journal session-start' first to init one.",
        ), OutputFormat(output_format))
        return

    # Bake absolute paths so hooks work regardless of where git_root is
    # relative to the Nexus toolkit (critical for nested-repo setups).
    bs_cli_path = str(Path(__file__).resolve().parent.parent / "bs_cli.py")
    pd_str = str(project_dir.resolve())
    log_path_str = str((project_dir / HOOK_LOG).resolve())
    # Forward slashes work in both sh and Windows Python paths inside strings.
    bs_cli_posix = bs_cli_path.replace("\\", "/")
    pd_posix = pd_str.replace("\\", "/")
    log_posix = log_path_str.replace("\\", "/")

    # Pre-create the .cache dir so the very first hook fire can write to it.
    try:
        Path(log_path_str).parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    hooks_dir = git_root / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    installed: list[str] = []
    upgraded: list[str] = []
    skipped: list[str] = []

    sh_hooks = {
        "post-commit": _make_post_commit_hook(bs_cli_posix, pd_posix, log_posix),
        "pre-push": _make_pre_push_hook(bs_cli_posix, pd_posix, log_posix),
    }

    for hook_name, hook_content in sh_hooks.items():
        hook_path = hooks_dir / hook_name
        status = _hook_status(hook_path)
        action: Optional[str] = None

        if status == "missing":
            action = "install"
        elif status == "current":
            if force:
                action = "reinstall"
            else:
                skipped.append(f"{hook_name} (current)")
                continue
        elif status == "outdated":
            action = "upgrade"
        elif status == "foreign":
            if force:
                action = "overwrite"
            elif output_format == "human":
                if click.confirm(
                    f"  Hook '{hook_name}' already exists (not by Nexus). Overwrite?",
                    default=False,
                ):
                    action = "overwrite"
                else:
                    skipped.append(f"{hook_name} (kept foreign)")
                    continue
            else:
                skipped.append(f"{hook_name} (foreign — pass --force to overwrite)")
                continue

        hook_path.write_text(hook_content, encoding="utf-8")
        try:
            hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass
        if action == "upgrade":
            upgraded.append(hook_name)
        else:
            installed.append(f"{hook_name} ({action})")

    # Windows: write .bat companions so native git (not WSL) can fire hooks.
    is_windows = sys.platform == "win32"
    if is_windows:
        bat_hooks = {
            "post-commit.bat": _make_post_commit_hook_bat(bs_cli_path, pd_str, log_path_str),
            "pre-push.bat": _make_pre_push_hook_bat(bs_cli_path, pd_str, log_path_str),
        }
        for bat_name, bat_content in bat_hooks.items():
            bat_path = hooks_dir / bat_name
            status = _hook_status(bat_path)
            if status == "missing":
                try:
                    bat_path.write_text(bat_content, encoding="utf-8")
                    installed.append(f"{bat_name} (install)")
                except OSError:
                    pass
            elif status == "current" and not force:
                skipped.append(f"{bat_name} (current)")
            else:  # outdated, foreign-with-force, or current-with-force
                try:
                    bat_path.write_text(bat_content, encoding="utf-8")
                    if status == "outdated":
                        upgraded.append(bat_name)
                    else:
                        installed.append(f"{bat_name} ({status})")
                except OSError:
                    pass

    msg_parts = []
    if installed:
        msg_parts.append(f"Installed: {', '.join(installed)}")
    if upgraded:
        msg_parts.append(f"Upgraded: {', '.join(upgraded)}")
    if skipped:
        msg_parts.append(f"Skipped: {', '.join(skipped)}")

    message = " | ".join(msg_parts) if msg_parts else "Nothing to do."

    if output_format == "human":
        click.echo(f"\n  Git hooks path: {hooks_dir}")
        click.echo(f"  bs_cli path  : {bs_cli_path}")
        click.echo(f"  project-dir  : {pd_str}")
        click.echo(f"  hook log     : {log_path_str}")
        for h in installed:
            click.echo(f"  [install] {h}")
        for h in upgraded:
            click.echo(f"  [upgrade] {h}")
        for s in skipped:
            click.echo(f"  - {s}")
        click.echo()
        click.echo(f"  Hook version : v{HOOK_VERSION}")
        click.echo("  post-commit  : auto-logs commit message to .nexus/state.md")
        click.echo("  pre-push     : regenerates state-dashboard.html before push")
        click.echo("  stderr       : appended to the hook log (not /dev/null)")
        if is_windows:
            click.echo("  .bat files   : Windows-native git companions installed")
        click.echo()

    emit(make_result(
        "journal-setup-hooks",
        Status.PASS if (installed or upgraded) else Status.WARN,
        message=message,
        details={
            "hooks_dir": str(hooks_dir),
            "bs_cli_path": bs_cli_path,
            "project_dir": pd_str,
            "log_path": log_path_str,
            "hook_version": HOOK_VERSION,
            "installed": installed,
            "upgraded": upgraded,
            "skipped": skipped,
        },
    ), OutputFormat(output_format)) if output_format != "human" else None


# --- Phase 2: AI-optimized summary + cross-tool integration ---

def _render_state_summary_md(state: dict[str, Any], git_root: Optional[Path]) -> str:
    """Render an AI-optimized snapshot of project state.

    Designed for inclusion via AGENTS.md / Cursor rules. Stays under ~200 lines
    by capping the recent-work and heatmap sections — the full journal lives in
    state.md, this is the read-this-first index.
    """
    project = state.get("project", "Project")
    status = state.get("status", "UNKNOWN")
    session_n = state.get("session_number", 0)
    branch = state.get("session_branch") or "?"
    last_updated = state.get("last_updated", "unknown")

    lines = [
        f"# {project} — Project State",
        f"_Auto-generated by `nexus journal export-summary` · {last_updated}_",
        "",
        f"**Status:** `{status}` · Session {session_n} · branch=`{branch}`",
        "",
        "## Active Now",
    ]

    next_items = state.get("next", [])
    if next_items:
        for n in next_items:
            lines.append(f"- [ ] {n}")
    else:
        lines.append("_Nothing queued. Use `nexus journal next add \"<task>\"`._")
    lines.append("")

    lines.append("## Blockers")
    blockers = state.get("blockers", [])
    if blockers:
        for b in blockers:
            lines.append(f"- {b}")
    else:
        lines.append("_None._")
    lines.append("")

    done_recent = state.get("done", [])[-MAX_SUMMARY_DONE:]
    if done_recent:
        lines.append(f"## Recent Work (last {len(done_recent)} entries)")
        for label, items in _group_done_by_type(done_recent):
            lines.append(f"### {label}")
            for item in items:
                # Strip the "[date Sn] " prefix for compactness
                payload = item.split("] ", 1)[-1] if "] " in item else item
                lines.append(f"- {payload}")
            lines.append("")

    if git_root:
        churn = _git_file_churn(git_root, since_iso=None, max_commits=50)
        top = sorted(churn.items(), key=lambda x: -x[1])[:5]
        if top:
            lines.append("## Most-Changed Files (last 50 commits)")
            for f, c in top:
                lines.append(f"- {c}× `{f}`")
            lines.append("")

        commits = _git_log_recent(git_root, n=5)
        if commits:
            lines.append("## Recent Commits")
            for c in commits:
                lines.append(f"- `{c['hash']}` {c['date']} — {c['message']}")
            lines.append("")

    lines.append("---")
    lines.append("_Full journal: `.nexus/state.md` · Dashboard: `.nexus/state-dashboard.html`_")
    return "\n".join(lines) + "\n"


def _write_state_summary(project_dir: Path, state: dict[str, Any],
                          git_root: Optional[Path]) -> tuple[Path, int]:
    """Write the AI-optimized summary to disk. Returns (path, line_count)."""
    summary = _render_state_summary_md(state, git_root)
    summary_path = project_dir / STATE_SUMMARY_MD
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary, encoding="utf-8")
    return summary_path, summary.count("\n")


def _cmd_export_summary(project_dir: Path, output_format: str) -> None:
    """Generate .nexus/state-summary.md (AI-optimized snapshot, ≤~200 lines)."""
    state = _load_state(project_dir)
    git_root = _resolve_git_root(project_dir)
    path, line_count = _write_state_summary(project_dir, state, git_root)

    emit(make_result(
        "journal-export-summary",
        Status.PASS,
        message=f"Summary exported to {STATE_SUMMARY_MD} ({line_count} lines)",
        details={"path": str(path), "lines": line_count},
    ), OutputFormat(output_format))


# --- AGENTS.md / Cursor rule generation ---

NEXUS_STATE_BLOCK = (
    NEXUS_AGENTS_BEGIN + "\n"
    "## Project State (auto-managed by `nexus journal init-agents`)\n"
    "\n"
    "Current state, active tasks, and recent work for this project live in:\n"
    "\n"
    "- `.nexus/state-summary.md` — AI-optimized summary (≤200 lines, **read this first**)\n"
    "- `.nexus/state.md` — full journal (commit log grouped by Conventional Commits type)\n"
    "- `.nexus/state-dashboard.html` — visual dashboard\n"
    "\n"
    "Update via the journal CLI. Sessions auto-roll when stale (idle ≥4h, new\n"
    "UTC date, or branch changed) — explicit `session-start`/`session-end` is\n"
    "optional, and the post-commit hook keeps the journal current automatically.\n"
    "\n"
    "```bash\n"
    "python nexus/cli/bs_cli.py journal next add \"<task>\"        # queue work\n"
    "python nexus/cli/bs_cli.py journal next done \"<idx|substr>\" # mark complete\n"
    "python nexus/cli/bs_cli.py journal blocker add \"<text>\"     # record a blocker\n"
    "python nexus/cli/bs_cli.py journal log \"<note>\"             # append to journal\n"
    "python nexus/cli/bs_cli.py journal status                   # show current state\n"
    "```\n"
    "\n"
    "This block is regenerated by `nexus journal init-agents`. Edit content\n"
    "outside the markers; anything between them will be replaced.\n"
    + NEXUS_AGENTS_END + "\n"
)

CURSOR_RULE_CONTENT = """\
---
description: Project state and active tasks (auto-generated by nexus journal)
globs: ["**/*"]
alwaysApply: false
---

# Project State

Read these at session start to understand current state and pending work:

- `.nexus/state-summary.md` — AI-optimized summary (≤200 lines)
- `.nexus/state.md` — full project journal

Update via:

- `nexus journal next add "<task>"` — queue work
- `nexus journal blocker add "<text>"` — record blockers
- `nexus journal log "<note>"` — append to the journal (auto-rolls stale sessions)

Run `nexus journal status` to see the current state without reading files.
"""


def _upsert_agents_md(project_dir: Path) -> str:
    """Insert/replace the Nexus-managed block in AGENTS.md.

    Returns 'created' | 'updated' | 'unchanged' | 'inserted'.
    Existing user content outside the markers is preserved verbatim.
    """
    path = project_dir / AGENTS_MD
    if not path.exists():
        # Create a minimal AGENTS.md that's just the Nexus block + a header.
        header = "# Project AGENTS\n\n_Conventions and runtime state for AI coding agents._\n\n"
        path.write_text(header + NEXUS_STATE_BLOCK, encoding="utf-8")
        return "created"

    existing = path.read_text(encoding="utf-8")

    if NEXUS_AGENTS_BEGIN in existing and NEXUS_AGENTS_END in existing:
        # Replace the existing block in place.
        before, _, rest = existing.partition(NEXUS_AGENTS_BEGIN)
        _, _, after = rest.partition(NEXUS_AGENTS_END)
        # Preserve a single trailing newline after the end marker if present.
        new_content = before + NEXUS_STATE_BLOCK + after.lstrip("\n")
        if new_content == existing:
            return "unchanged"
        path.write_text(new_content, encoding="utf-8")
        return "updated"

    # No markers yet — append the block at end of file.
    sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    path.write_text(existing + sep + NEXUS_STATE_BLOCK, encoding="utf-8")
    return "inserted"


def _write_cursor_rule(project_dir: Path) -> str:
    """Write .cursor/rules/state.mdc. Returns 'created' | 'updated' | 'unchanged'."""
    path = project_dir / CURSOR_RULE
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == CURSOR_RULE_CONTENT:
            return "unchanged"
        path.write_text(CURSOR_RULE_CONTENT, encoding="utf-8")
        return "updated"

    path.write_text(CURSOR_RULE_CONTENT, encoding="utf-8")
    return "created"


def _cmd_init_agents(project_dir: Path, output_format: str) -> None:
    """Install/refresh AGENTS.md block + .cursor/rules/state.mdc + state-summary.md.

    Idempotent: safe to run repeatedly. Existing AGENTS.md content outside the
    Nexus markers is preserved.
    """
    agents_action = _upsert_agents_md(project_dir)
    cursor_action = _write_cursor_rule(project_dir)

    state = _load_state(project_dir)
    git_root = _resolve_git_root(project_dir)
    summary_path, summary_lines = _write_state_summary(project_dir, state, git_root)

    msg = (
        f"AGENTS.md: {agents_action} | "
        f".cursor/rules/state.mdc: {cursor_action} | "
        f"state-summary.md: {summary_lines} lines"
    )

    if output_format == "human":
        import click
        click.echo(f"\n  {msg}\n")

    emit(make_result(
        "journal-init-agents",
        Status.PASS,
        message=msg,
        details={
            "agents_md": agents_action,
            "cursor_rule": cursor_action,
            "state_summary_lines": summary_lines,
            "agents_path": str(project_dir / AGENTS_MD),
            "cursor_path": str(project_dir / CURSOR_RULE),
            "summary_path": str(summary_path),
        },
    ), OutputFormat(output_format)) if output_format != "human" else None


# --- Phase 3: Decision records (MADR-minimal) ---

_MADR_TEMPLATE = """\
# {n:04d}. {title}

- **Status:** proposed
- **Date:** {date}
- **Deciders:** TODO

## Context and Problem Statement

TODO — describe the situation, constraints, and the question being answered.

## Considered Options

- TODO option A
- TODO option B

## Decision Outcome

Chosen option: **TODO**, because TODO.

### Consequences

- Good: TODO
- Bad: TODO

<!-- Authored via `nexus journal decision add`. Edit freely; Nexus does not regenerate this file. -->
"""


def _slugify(text: str) -> str:
    """Lowercase, alphanumeric + hyphens, capped at 50 chars. Used for ADR filenames."""
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9\s\-]", "", s)
    s = re.sub(r"[\s\-]+", "-", s).strip("-")
    return s[:50] or "decision"


def _next_decision_number(decisions_dir: Path) -> int:
    """Scan existing NNNN-*.md files and return the next sequence number."""
    if not decisions_dir.exists():
        return 1
    max_n = 0
    try:
        for f in decisions_dir.glob("[0-9][0-9][0-9][0-9]-*.md"):
            try:
                n = int(f.name[:4])
                max_n = max(max_n, n)
            except ValueError:
                continue
    except OSError:
        pass
    return max_n + 1


def _cmd_decision(project_dir: Path, args: tuple, output_format: str) -> None:
    """Manage architectural decision records (MADR-minimal).

    journal decision add "<title>"   create a new ADR stub
    journal decision list            show existing ADRs
    """
    action = args[0] if args else "list"
    rest = args[1:]
    decisions_dir = project_dir / DECISIONS_DIR

    if action == "add":
        title = " ".join(rest).strip()
        if not title:
            emit(make_result("journal-decision", Status.FAIL,
                             message='Usage: journal decision add "<title>"'),
                 OutputFormat(output_format))
            return
        try:
            decisions_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            emit(make_result("journal-decision-add", Status.FAIL,
                             message=f"Could not create {DECISIONS_DIR}: {e}"),
                 OutputFormat(output_format))
            return

        n = _next_decision_number(decisions_dir)
        slug = _slugify(title)
        path = decisions_dir / f"{n:04d}-{slug}.md"
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path.write_text(
            _MADR_TEMPLATE.format(n=n, title=title, date=date),
            encoding="utf-8",
        )

        # Log the decision creation to the journal so it surfaces in done/state.md.
        # Use no_export so we don't double-regenerate the dashboard.
        try:
            _cmd_log(
                project_dir,
                f"decision: ADR {n:04d} — {title} ({path.relative_to(project_dir)})",
                "json",
                auto_export=False,
            )
        except Exception:
            pass

        emit(make_result(
            "journal-decision-add",
            Status.PASS,
            message=f"Created ADR {n:04d}: {title}",
            details={
                "path": str(path),
                "number": n,
                "slug": slug,
                "title": title,
            },
        ), OutputFormat(output_format))

    elif action == "list":
        if not decisions_dir.exists():
            emit(make_result("journal-decision-list", Status.INFO,
                             message="No decisions recorded yet.",
                             details={"decisions": [], "dir": str(decisions_dir)}),
                 OutputFormat(output_format))
            return
        decisions = []
        for f in sorted(decisions_dir.glob("[0-9][0-9][0-9][0-9]-*.md")):
            try:
                first_line = f.read_text(encoding="utf-8").splitlines()[0]
                title = first_line.lstrip("# ").strip()
            except (OSError, IndexError):
                title = f.stem
            decisions.append({
                "file": str(f.relative_to(project_dir)),
                "title": title,
            })
        emit(make_result("journal-decision-list", Status.INFO,
                         message=f"{len(decisions)} ADR(s)",
                         details={"decisions": decisions, "dir": str(decisions_dir)}),
             OutputFormat(output_format))

    else:
        emit(make_result("journal-decision", Status.FAIL,
                         message=f"Unknown action: {action}. Use add|list."),
             OutputFormat(output_format))


# --- Phase 4: Blame (cross-reference a file across journal + git) ---

def _cmd_blame(project_dir: Path, args: tuple, output_format: str) -> None:
    """Cross-reference a file across the journal and git history.

    journal blame <file>   show commits, done entries, and daily mentions
                           that reference the given file.
    """
    if not args:
        emit(make_result("journal-blame", Status.FAIL,
                         message="Usage: journal blame <file>"),
             OutputFormat(output_format))
        return

    target = " ".join(args).strip()
    target_short = Path(target).name
    state = _load_state(project_dir)
    git_root = _resolve_git_root(project_dir)

    # Git: log restricted to the file path
    commits: list[dict] = []
    if git_root:
        rc, out, _ = _git_run(
            ["log", "-20", "--pretty=format:%H|%as|%s", "--", target],
            git_root,
        )
        if rc == 0 and out:
            for line in out.splitlines():
                parts = line.split("|", 2)
                if len(parts) == 3:
                    commits.append({
                        "hash": parts[0][:8],
                        "date": parts[1],
                        "message": parts[2],
                    })

    # State.done: entries whose text mentions the file
    done_entries = [
        d for d in state.get("done", [])
        if target in d or target_short in d
    ]

    # Daily journal: line-level mentions across all daily files
    daily_mentions: list[dict] = []
    daily_dir = project_dir / DAILY_JOURNAL_DIR
    if daily_dir.exists():
        for daily_file in sorted(daily_dir.rglob("*.md")):
            try:
                lines = daily_file.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for ln in lines:
                if target in ln or (target_short and target_short in ln):
                    daily_mentions.append({
                        "file": str(daily_file.relative_to(project_dir)),
                        "line": ln,
                    })

    msg = (
        f"{len(commits)} commit(s), "
        f"{len(done_entries)} done entry/ies, "
        f"{len(daily_mentions)} daily mention(s) for {target}"
    )
    emit(make_result(
        "journal-blame",
        Status.INFO,
        message=msg,
        details={
            "file": target,
            "commits": commits,
            "done_entries": done_entries[-10:],
            "daily_mentions": daily_mentions[-10:],
        },
    ), OutputFormat(output_format))


# --- CLI dispatcher ---

def run_journal(subcommand: str, args: tuple, output_format: str, project_dir: str,
                no_export: bool = False, force: bool = False) -> None:
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
        _cmd_log(pd, msg, output_format, auto_export=not no_export)
    elif subcommand == "status":
        _cmd_status(pd, output_format)
    elif subcommand == "diff":
        _cmd_diff(pd, output_format)
    elif subcommand == "export":
        _cmd_export(pd, output_format)
    elif subcommand == "setup-hooks":
        _cmd_setup_hooks(pd, output_format, force=force)
    elif subcommand == "next":
        _cmd_next(pd, args, output_format)
    elif subcommand == "blocker":
        _cmd_blocker(pd, args, output_format)
    elif subcommand == "export-summary":
        _cmd_export_summary(pd, output_format)
    elif subcommand == "init-agents":
        _cmd_init_agents(pd, output_format)
    elif subcommand == "decision":
        _cmd_decision(pd, args, output_format)
    elif subcommand == "blame":
        _cmd_blame(pd, args, output_format)
    else:
        emit(make_result(
            "journal",
            Status.FAIL,
            message=f"Unknown subcommand: {subcommand}",
        ), OutputFormat(output_format))
