"""
Journal Dashboard Generator — produces a self-contained state-dashboard.html.

All CSS/JS inlined. No CDN required. Dark-mode design consistent with nexus-architecture.html.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def generate_dashboard(
    state: dict[str, Any],
    git_commits: list[dict],
    git_status: Optional[str],
    audit_entries: list[dict],
    output_path: Path,
    top_files: Optional[list[tuple[str, int]]] = None,
) -> None:
    """Generate and write the self-contained dashboard HTML.

    `top_files` is a precomputed [(path, count), ...] list. When None, the
    heatmap falls back to deriving counts from session_log (legacy path).
    """
    html = _build_html(state, git_commits, git_status, audit_entries, top_files)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def _esc(text: str) -> str:
    """HTML-escape a string."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _build_html(
    state: dict[str, Any],
    git_commits: list[dict],
    git_status: Optional[str],
    audit_entries: list[dict],
    top_files: Optional[list[tuple[str, int]]] = None,
) -> str:
    project = _esc(state.get("project", "Project"))
    status = _esc(state.get("status", "UNKNOWN"))
    session_n = state.get("session_number", 0)
    last_updated = _esc(state.get("last_updated", "unknown"))

    status_color = {
        "IN PROGRESS": "#60a5fa",
        "DONE": "#4ade80",
        "BLOCKED": "#f87171",
        "ON HOLD": "#fbbf24",
    }.get(state.get("status", ""), "#a78bfa")

    done_items = state.get("done", [])[-20:]
    next_items = state.get("next", [])
    blockers = state.get("blockers", [])
    session_log = list(reversed(state.get("session_log", [])[-15:]))

    # Heatmap source: prefer caller-supplied top_files (git churn). Only fall
    # back to session_log aggregation when no churn was provided — this keeps
    # legacy non-git callers working.
    if top_files is None:
        file_freq: dict[str, int] = {}
        for entry in state.get("session_log", []):
            for f in entry.get("changed_files", []):
                file_freq[f] = file_freq.get(f, 0) + 1
        top_files = sorted(file_freq.items(), key=lambda x: -x[1])[:10]

    done_html = _render_list(done_items, "No items logged yet.", bullet=True)
    next_html = _render_checklist(next_items)
    blockers_html = _render_list(blockers, "None", bullet=True)
    session_html = _render_session_table(session_log)
    heatmap_html = _render_heatmap(top_files)
    git_html = _render_git_section(git_commits, git_status)
    audit_html = _render_audit_table(audit_entries)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{project} — Nexus Project State</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #222636;
    --border: rgba(99,102,241,0.2);
    --text: #e2e8f0;
    --text-dim: #94a3b8;
    --accent: #6366f1;
    --green: #4ade80;
    --red: #f87171;
    --yellow: #fbbf24;
    --blue: #60a5fa;
    --purple: #a78bfa;
  }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    font-size: 14px;
    line-height: 1.6;
    padding: 24px;
  }}
  h1 {{ font-size: 1.6rem; font-weight: 700; margin-bottom: 4px; }}
  h2 {{ font-size: 1rem; font-weight: 600; margin-bottom: 12px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.06em; }}
  .meta {{ color: var(--text-dim); font-size: 0.8rem; margin-bottom: 24px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 20px; }}
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px;
  }}
  .card.wide {{ grid-column: 1 / -1; }}
  .status-badge {{
    display: inline-block;
    padding: 4px 14px;
    border-radius: 20px;
    font-weight: 700;
    font-size: 0.85rem;
    background: rgba(99,102,241,0.15);
    border: 1px solid var(--border);
    color: {status_color};
    margin-bottom: 10px;
  }}
  .stat {{ font-size: 2rem; font-weight: 800; margin: 6px 0 2px; }}
  .stat-label {{ font-size: 0.75rem; color: var(--text-dim); }}
  .stats-row {{ display: flex; gap: 28px; flex-wrap: wrap; }}
  ul {{ list-style: none; padding: 0; }}
  ul li {{ padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.04); font-size: 0.88rem; }}
  ul li:last-child {{ border-bottom: none; }}
  ul li::before {{ content: "›"; color: var(--accent); margin-right: 7px; }}
  .checklist li::before {{ content: "☐"; color: var(--yellow); margin-right: 7px; }}
  .blockers li::before {{ content: "⚠"; color: var(--red); margin-right: 7px; }}
  .done-list li::before {{ content: "✓"; color: var(--green); margin-right: 7px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th {{ text-align: left; padding: 8px 10px; background: var(--surface2); color: var(--text-dim); font-weight: 600; border-bottom: 1px solid var(--border); }}
  td {{ padding: 7px 10px; border-bottom: 1px solid rgba(255,255,255,0.04); vertical-align: top; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: rgba(99,102,241,0.05); }}
  .tag {{ display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 0.75rem; background: rgba(99,102,241,0.15); color: var(--purple); }}
  .bar-wrap {{ background: var(--surface2); border-radius: 4px; height: 8px; margin-top: 3px; }}
  .bar {{ height: 8px; border-radius: 4px; background: linear-gradient(90deg, var(--accent), var(--purple)); }}
  .empty {{ color: var(--text-dim); font-style: italic; font-size: 0.85rem; }}
  .commit-hash {{ font-family: monospace; font-size: 0.8rem; color: var(--text-dim); }}
  .git-status {{ font-family: monospace; font-size: 0.8rem; white-space: pre-wrap; color: var(--blue); background: var(--surface2); padding: 10px; border-radius: 6px; }}
  footer {{ margin-top: 32px; text-align: center; color: var(--text-dim); font-size: 0.75rem; }}
  .section-sep {{ margin: 20px 0; border: none; border-top: 1px solid var(--border); }}
</style>
</head>
<body>

<h1>🗂 {project}</h1>
<p class="meta">Generated by Nexus Journal · {last_updated} · Session {session_n}</p>

<!-- Status + Stats Row -->
<div class="grid">
  <div class="card">
    <h2>Status</h2>
    <div class="status-badge">{status}</div>
    <div class="stats-row" style="margin-top:12px;">
      <div>
        <div class="stat">{session_n}</div>
        <div class="stat-label">Sessions</div>
      </div>
      <div>
        <div class="stat">{len(done_items)}</div>
        <div class="stat-label">Done Items</div>
      </div>
      <div>
        <div class="stat">{len(next_items)}</div>
        <div class="stat-label">Next Tasks</div>
      </div>
      <div>
        <div class="stat" style="color:{'var(--red)' if blockers else 'var(--green)'};">{len(blockers)}</div>
        <div class="stat-label">Blockers</div>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>What's Next</h2>
    {next_html}
  </div>

  <div class="card">
    <h2>Blockers</h2>
    {blockers_html}
  </div>
</div>

<!-- Done Items -->
<div class="card" style="margin-bottom:16px;">
  <h2>What's Been Done (last 20)</h2>
  {done_html}
</div>

<!-- Session Log + Heatmap -->
<div class="grid">
  <div class="card wide">
    <h2>Session Log</h2>
    {session_html}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2>Most Changed Files</h2>
    {heatmap_html}
  </div>
  <div class="card">
    {git_html}
  </div>
</div>

<!-- Audit Trail -->
<div class="card" style="margin-top:16px;">
  <h2>Recent CLI Activity (Audit Trail)</h2>
  {audit_html}
</div>

<footer>
  Nexus Project Tracker · <a href="https://github.com/llores28/Nexus" style="color:var(--accent);">llores28/Nexus</a>
</footer>

</body>
</html>"""


def _render_list(items: list, empty_msg: str, bullet: bool = False, css_class: str = "") -> str:
    if not items:
        return f'<p class="empty">{_esc(empty_msg)}</p>'
    cls = css_class or ("done-list" if not css_class else css_class)
    lis = "".join(f"<li>{_esc(str(i))}</li>" for i in items)
    return f'<ul class="{cls}">{lis}</ul>'


def _render_checklist(items: list) -> str:
    if not items:
        return '<p class="empty">Nothing queued.</p>'
    lis = "".join(f"<li>{_esc(str(i))}</li>" for i in items)
    return f'<ul class="checklist">{lis}</ul>'


def _render_session_table(session_log: list[dict]) -> str:
    if not session_log:
        return '<p class="empty">No sessions recorded yet.</p>'
    rows = ""
    for entry in session_log:
        n = _esc(str(entry.get("session", "?")))
        date = _esc(str(entry.get("date", "?")))
        summary = _esc(str(entry.get("summary", ""))[:70])
        fc = _esc(str(entry.get("file_count", 0)))
        files = entry.get("changed_files", [])[:4]
        file_tags = " ".join(
            f'<span class="tag">{_esc(f.split("/")[-1] if "/" in f else f)}</span>'
            for f in files
        )
        rows += f"<tr><td>{n}</td><td>{date}</td><td>{summary}</td><td>{fc}</td><td>{file_tags}</td></tr>"
    return f"""<table>
  <thead><tr><th>#</th><th>Date</th><th>Summary</th><th>Files</th><th>Changed</th></tr></thead>
  <tbody>{rows}</tbody>
</table>"""


def _render_heatmap(top_files: list[tuple[str, int]]) -> str:
    if not top_files:
        return '<p class="empty">No file change data yet.</p>'
    max_count = max(c for _, c in top_files) if top_files else 1
    rows = ""
    for f, count in top_files:
        short = f.split("/")[-1] if "/" in f else f.split("\\")[-1] if "\\" in f else f
        pct = int((count / max_count) * 100)
        rows += f"""
<div style="margin-bottom:10px;">
  <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
    <span style="font-size:0.82rem;color:var(--text);">{_esc(short)}</span>
    <span style="font-size:0.75rem;color:var(--text-dim);">{count}x</span>
  </div>
  <div class="bar-wrap"><div class="bar" style="width:{pct}%;"></div></div>
</div>"""
    return rows


def _render_git_section(commits: list[dict], status: Optional[str]) -> str:
    lines = ["<h2>Git</h2>"]
    if status:
        lines.append(f'<div class="git-status">{_esc(status[:400])}</div>')
        lines.append("<br>")
    if commits:
        rows = ""
        for c in commits:
            h = _esc(c.get("hash", "?"))
            d = _esc(c.get("date", "?"))
            m = _esc(c.get("message", "")[:60])
            rows += f"<tr><td class='commit-hash'>{h}</td><td>{d}</td><td>{m}</td></tr>"
        lines.append(f"""<table>
  <thead><tr><th>Hash</th><th>Date</th><th>Message</th></tr></thead>
  <tbody>{rows}</tbody>
</table>""")
    else:
        lines.append('<p class="empty">No git data available.</p>')
    return "\n".join(lines)


def _render_audit_table(entries: list[dict]) -> str:
    if not entries:
        return '<p class="empty">No CLI activity recorded yet.</p>'
    rows = ""
    for entry in reversed(entries):
        ts = _esc(str(entry.get("timestamp", "?")))
        tool = _esc(str(entry.get("tool", "?")))
        ec = entry.get("exit_code", 0)
        ec_color = "var(--green)" if ec == 0 else "var(--red)"
        dur = _esc(str(entry.get("duration_ms", "?")))
        rows += f"<tr><td>{ts}</td><td><span class='tag'>{tool}</span></td><td style='color:{ec_color};'>{ec}</td><td>{dur}ms</td></tr>"
    return f"""<table>
  <thead><tr><th>Timestamp</th><th>Tool</th><th>Exit</th><th>Duration</th></tr></thead>
  <tbody>{rows}</tbody>
</table>"""
