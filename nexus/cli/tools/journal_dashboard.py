"""
Journal Dashboard Generator — produces a self-contained state-dashboard.html.

All CSS/JS inlined. No CDN required. Modern dual-theme design with optional
live API fetch (graceful fallback to static state when unreachable).

Wave B + C upgrades (2026-04-29):
- Mobile-first responsive (card-stack tables under 640px) + ARIA + semantic HTML
- Dark/light theme toggle persisted in localStorage
- Command palette (Cmd/Ctrl+K) with fuzzy search across done items, sessions,
  changed files, and queued tasks
- Inline SVG sparklines for cost + quality trends (rendered only when data
  flows in from the live API; static export omits gracefully)
- Optional fetch of ``ATLAS_API_BASE/api/dashboard`` on load — falls back to
  the embedded static snapshot when the API is unreachable (offline-first)
- WebSocket subscriber for live audit-trail tail when API is reachable
- "View Live" header link to the React dashboard at ``ATLAS_LIVE_DASH_URL``

Hide-when-empty rule: "What's Next" and "Blockers" cards now collapse when
their data structure is empty, instead of rendering placeholder text. The
status-bar stat cells still show the count so the absence is visible.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


# Backend integration defaults — overridable via env or by editing the
# emitted HTML's <script> block. Kept short so the file stays self-contained.
DEFAULT_API_BASE = "http://localhost:8000"
DEFAULT_LIVE_DASH_URL = "http://localhost:3001"


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

    status_color_var = {
        "IN PROGRESS": "var(--blue)",
        "DONE": "var(--green)",
        "BLOCKED": "var(--red)",
        "ON HOLD": "var(--yellow)",
    }.get(state.get("status", ""), "var(--purple)")

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
    # Wave B.4: collapse empty Next/Blockers — return None to skip the card entirely
    next_html = _render_checklist(next_items) if next_items else None
    blockers_html = _render_list(blockers, "None", bullet=True, css_class="blockers") if blockers else None
    session_html = _render_session_table(session_log)
    heatmap_html = _render_heatmap(top_files)
    git_html = _render_git_section(git_commits, git_status)
    audit_html = _render_audit_table(audit_entries)

    # Embed a JSON payload of search-indexable items for the Cmd+K palette.
    # Kept inline so the dashboard remains a single self-contained file.
    palette_payload = _palette_index(
        done_items=list(done_items),
        next_items=list(next_items),
        sessions=list(session_log),
        files=[f for f, _ in top_files],
    )

    # ── Cards-row HTML — only emit cards whose data is non-empty ───────────
    secondary_cards = []
    if next_html is not None:
        secondary_cards.append(
            f'<article class="card" aria-labelledby="card-next">'
            f'  <h2 id="card-next">What\'s Next <span class="count">({len(next_items)})</span></h2>'
            f'  {next_html}'
            f'</article>'
        )
    if blockers_html is not None:
        secondary_cards.append(
            f'<article class="card" aria-labelledby="card-blockers">'
            f'  <h2 id="card-blockers">Blockers <span class="count">({len(blockers)})</span></h2>'
            f'  {blockers_html}'
            f'</article>'
        )
    secondary_cards_html = "\n  ".join(secondary_cards)

    # Sparkline placeholders — populated by JS when the live API responds.
    sparkline_section = (
        '<div class="grid sparkline-grid" id="sparkline-grid" hidden>'
        '  <article class="card" aria-labelledby="card-cost">'
        '    <h2 id="card-cost">Cost (last 30d)</h2>'
        '    <div id="cost-stat" class="stat">—</div>'
        '    <svg id="cost-spark" class="sparkline" viewBox="0 0 200 60" preserveAspectRatio="none" aria-hidden="true"></svg>'
        '  </article>'
        '  <article class="card" aria-labelledby="card-quality">'
        '    <h2 id="card-quality">Quality trend</h2>'
        '    <div id="quality-stat" class="stat">—</div>'
        '    <svg id="quality-spark" class="sparkline" viewBox="0 0 200 60" preserveAspectRatio="none" aria-hidden="true"></svg>'
        '  </article>'
        '</div>'
    )

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="dark light">
<title>{project} — Nexus Project State</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root[data-theme="dark"] {{
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
    --row-hover: rgba(99,102,241,0.08);
    --shadow: 0 1px 3px rgba(0,0,0,0.4);
  }}
  :root[data-theme="light"] {{
    --bg: #f7f8fb;
    --surface: #ffffff;
    --surface2: #eef0f6;
    --border: rgba(99,102,241,0.25);
    --text: #1f2433;
    --text-dim: #5b6478;
    --accent: #5048e5;
    --green: #16a34a;
    --red: #dc2626;
    --yellow: #d97706;
    --blue: #2563eb;
    --purple: #7c3aed;
    --row-hover: rgba(99,102,241,0.06);
    --shadow: 0 1px 3px rgba(15,17,23,0.08);
  }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, 'Segoe UI', system-ui, sans-serif;
    font-size: 14px;
    line-height: 1.6;
    padding: 24px;
    transition: background 180ms ease, color 180ms ease;
  }}
  main {{ max-width: 1400px; margin: 0 auto; }}
  header.topbar {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; margin-bottom: 6px; }}
  header.topbar .title-block {{ flex: 1 1 auto; min-width: 0; }}
  header.topbar nav {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
  h1 {{ font-size: 1.6rem; font-weight: 700; margin-bottom: 4px; }}
  h2 {{ font-size: 0.92rem; font-weight: 600; margin-bottom: 12px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.06em; }}
  h2 .count {{ color: var(--text-dim); font-weight: 400; text-transform: none; letter-spacing: 0; font-size: 0.85em; }}
  .meta {{ color: var(--text-dim); font-size: 0.8rem; margin-bottom: 24px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 20px; }}
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px;
    box-shadow: var(--shadow);
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
    color: {status_color_var};
    margin-bottom: 10px;
  }}
  .stat {{ font-size: 1.7rem; font-weight: 800; margin: 6px 0 2px; line-height: 1.1; }}
  .stat-label {{ font-size: 0.75rem; color: var(--text-dim); }}
  .stats-row {{ display: flex; gap: 28px; flex-wrap: wrap; }}
  ul {{ list-style: none; padding: 0; }}
  ul li {{ padding: 4px 0; border-bottom: 1px solid rgba(127,127,127,0.08); font-size: 0.88rem; }}
  ul li:last-child {{ border-bottom: none; }}
  ul li::before {{ content: "›"; color: var(--accent); margin-right: 7px; }}
  .checklist li::before {{ content: "☐"; color: var(--yellow); margin-right: 7px; }}
  .blockers li::before {{ content: "⚠"; color: var(--red); margin-right: 7px; }}
  .done-list li::before {{ content: "✓"; color: var(--green); margin-right: 7px; }}
  .table-wrap {{ width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th {{ text-align: left; padding: 8px 10px; background: var(--surface2); color: var(--text-dim); font-weight: 600; border-bottom: 1px solid var(--border); position: sticky; top: 0; }}
  td {{ padding: 7px 10px; border-bottom: 1px solid rgba(127,127,127,0.08); vertical-align: top; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: var(--row-hover); }}
  .tag {{ display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 0.75rem; background: rgba(99,102,241,0.15); color: var(--purple); margin: 1px 2px; }}
  .bar-wrap {{ background: var(--surface2); border-radius: 4px; height: 8px; margin-top: 3px; }}
  .bar {{ height: 8px; border-radius: 4px; background: linear-gradient(90deg, var(--accent), var(--purple)); }}
  .empty {{ color: var(--text-dim); font-style: italic; font-size: 0.85rem; }}
  .commit-hash {{ font-family: ui-monospace, 'Cascadia Code', Menlo, monospace; font-size: 0.8rem; color: var(--text-dim); }}
  .git-status {{ font-family: ui-monospace, 'Cascadia Code', Menlo, monospace; font-size: 0.8rem; white-space: pre-wrap; color: var(--blue); background: var(--surface2); padding: 10px; border-radius: 6px; max-height: 220px; overflow-y: auto; }}
  footer {{ margin-top: 32px; text-align: center; color: var(--text-dim); font-size: 0.75rem; }}
  .section-sep {{ margin: 20px 0; border: none; border-top: 1px solid var(--border); }}

  /* Sparklines */
  .sparkline {{ width: 100%; height: 60px; margin-top: 8px; }}
  .sparkline path.line {{ fill: none; stroke: var(--accent); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }}
  .sparkline path.fill {{ fill: var(--accent); fill-opacity: 0.12; stroke: none; }}
  .sparkline circle {{ fill: var(--accent); }}

  /* Header buttons */
  .btn {{
    background: var(--surface); color: var(--text); border: 1px solid var(--border);
    border-radius: 8px; padding: 6px 12px; font-size: 0.78rem; cursor: pointer;
    text-decoration: none; display: inline-flex; align-items: center; gap: 6px;
    transition: background 120ms ease, border-color 120ms ease;
  }}
  .btn:hover {{ border-color: var(--accent); background: var(--surface2); }}
  .btn .kbd {{ font-family: ui-monospace, monospace; font-size: 0.72rem; padding: 1px 5px; border-radius: 4px; background: var(--surface2); border: 1px solid var(--border); color: var(--text-dim); }}
  .live-badge {{ display: none; align-items: center; gap: 6px; font-size: 0.75rem; color: var(--text-dim); padding: 5px 10px; }}
  .live-badge::before {{ content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--green); box-shadow: 0 0 8px var(--green); animation: pulse 2s infinite ease-in-out; }}
  .live-badge.on {{ display: inline-flex; }}
  @keyframes pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} }}

  /* Command palette */
  .palette-overlay {{
    position: fixed; inset: 0; background: rgba(0,0,0,0.45); display: none;
    align-items: flex-start; justify-content: center; padding-top: 12vh; z-index: 1000;
  }}
  .palette-overlay.open {{ display: flex; }}
  .palette {{
    width: min(640px, 92vw); background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; box-shadow: 0 18px 48px rgba(0,0,0,0.45); overflow: hidden;
  }}
  .palette input {{
    width: 100%; padding: 14px 18px; font-size: 1rem; background: transparent;
    color: var(--text); border: none; border-bottom: 1px solid var(--border); outline: none;
  }}
  .palette ol {{ list-style: none; max-height: 56vh; overflow-y: auto; padding: 6px 0; margin: 0; }}
  .palette li {{ padding: 8px 18px; font-size: 0.88rem; cursor: pointer; display: flex; gap: 10px; align-items: baseline; }}
  .palette li:hover, .palette li.selected {{ background: var(--row-hover); }}
  .palette li .kind {{ font-size: 0.7rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.04em; flex-shrink: 0; min-width: 64px; }}
  .palette .empty-msg {{ padding: 14px 18px; color: var(--text-dim); font-style: italic; }}

  /* Mobile-first card-stack tables (Wave B.5) */
  @media (max-width: 640px) {{
    body {{ padding: 14px; }}
    h1 {{ font-size: 1.35rem; }}
    .grid {{ grid-template-columns: 1fr; gap: 12px; }}
    .card {{ padding: 14px; }}
    .stats-row {{ gap: 16px; }}
    .stat {{ font-size: 1.3rem; }}
    .commit-hash {{ font-size: 0.72rem; }}
    /* Convert tables to stacked card rows */
    .table-wrap.stack table, .table-wrap.stack thead, .table-wrap.stack tbody,
    .table-wrap.stack th, .table-wrap.stack td, .table-wrap.stack tr {{ display: block; }}
    .table-wrap.stack thead {{ position: absolute; left: -10000px; top: -10000px; }}
    .table-wrap.stack tr {{ border: 1px solid var(--border); border-radius: 8px; padding: 10px; margin-bottom: 8px; background: var(--surface2); }}
    .table-wrap.stack td {{ border: none; padding: 4px 0; font-size: 0.82rem; }}
    .table-wrap.stack td::before {{ content: attr(data-label) ": "; color: var(--text-dim); font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; margin-right: 6px; }}
  }}

  /* Reduced-motion: tone down the live-badge pulse */
  @media (prefers-reduced-motion: reduce) {{
    .live-badge::before {{ animation: none; }}
    body {{ transition: none; }}
  }}
</style>
</head>
<body>

<main>

<header class="topbar">
  <div class="title-block">
    <h1>🗂 {project}</h1>
    <p class="meta">Generated by Nexus Journal · {last_updated} · Session {session_n}</p>
  </div>
  <nav aria-label="Dashboard controls">
    <span id="live-badge" class="live-badge" title="Live API connected">live</span>
    <button id="palette-btn" class="btn" type="button" aria-label="Open command palette">⌘ Search <span class="kbd">⌘K</span></button>
    <button id="theme-toggle" class="btn" type="button" aria-label="Toggle light/dark theme">🌗 Theme</button>
    <a id="live-link" class="btn" href="#" rel="noopener" aria-label="Open the live React dashboard">↗ View Live</a>
  </nav>
</header>

<!-- Status + Stats Row -->
<section class="grid" aria-label="Project status">
  <article class="card" aria-labelledby="card-status">
    <h2 id="card-status">Status</h2>
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
  </article>

  {secondary_cards_html}
</section>

{sparkline_section}

<!-- Done Items -->
<article class="card" style="margin-bottom:16px;" aria-labelledby="card-done">
  <h2 id="card-done">What's Been Done <span class="count">(last 20)</span></h2>
  {done_html}
</article>

<!-- Session Log -->
<section class="grid" aria-label="Session activity">
  <article class="card wide" aria-labelledby="card-sessions">
    <h2 id="card-sessions">Session Log</h2>
    {session_html}
  </article>
</section>

<section class="grid" aria-label="Files and git">
  <article class="card" aria-labelledby="card-files">
    <h2 id="card-files">Most Changed Files</h2>
    {heatmap_html}
  </article>
  <article class="card" aria-labelledby="card-git">
    {git_html}
  </article>
</section>

<!-- Audit Trail -->
<article class="card" style="margin-top:16px;" aria-labelledby="card-audit">
  <h2 id="card-audit">Recent CLI Activity <span class="count" id="audit-count">(audit trail)</span></h2>
  {audit_html}
</article>

<footer>
  Nexus Project Tracker · <a href="https://github.com/llores28/Nexus" style="color:var(--accent);">llores28/Nexus</a>
</footer>

</main>

<!-- Command palette overlay -->
<div id="palette-overlay" class="palette-overlay" role="dialog" aria-modal="true" aria-label="Command palette">
  <div class="palette" role="combobox" aria-haspopup="listbox" aria-expanded="true">
    <input id="palette-input" type="text" placeholder="Search done items, sessions, files…" aria-label="Search query" autocomplete="off" />
    <ol id="palette-results" role="listbox"></ol>
  </div>
</div>

<script>
(function() {{
  // ── Config — overridable via meta tag or window globals ──────────────
  const API_BASE = (window.ATLAS_API_BASE || "{DEFAULT_API_BASE}").replace(/\\/$/, "");
  const LIVE_DASH = window.ATLAS_LIVE_DASH_URL || "{DEFAULT_LIVE_DASH_URL}";
  document.getElementById("live-link").href = LIVE_DASH;

  // ── Theme toggle (Wave B.6) ───────────────────────────────────────────
  const themeBtn = document.getElementById("theme-toggle");
  const root = document.documentElement;
  const stored = (() => {{ try {{ return localStorage.getItem("nexus-dash-theme"); }} catch (e) {{ return null; }} }})();
  if (stored === "light" || stored === "dark") root.setAttribute("data-theme", stored);
  themeBtn.addEventListener("click", () => {{
    const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try {{ localStorage.setItem("nexus-dash-theme", next); }} catch (e) {{}}
  }});

  // ── Mark tables for mobile card-stack with data-label attrs ───────────
  document.querySelectorAll("table").forEach(table => {{
    const headers = Array.from(table.querySelectorAll("thead th")).map(th => th.textContent.trim());
    table.querySelectorAll("tbody tr").forEach(row => {{
      Array.from(row.children).forEach((cell, i) => {{
        if (headers[i]) cell.setAttribute("data-label", headers[i]);
      }});
    }});
    if (!table.parentElement.classList.contains("table-wrap")) {{
      const wrap = document.createElement("div");
      wrap.className = "table-wrap stack";
      table.parentNode.insertBefore(wrap, table);
      wrap.appendChild(table);
    }} else {{
      table.parentElement.classList.add("stack");
    }}
  }});

  // ── Command palette (Wave B.7) ────────────────────────────────────────
  const PALETTE_INDEX = {json.dumps(palette_payload)};
  const overlay = document.getElementById("palette-overlay");
  const input = document.getElementById("palette-input");
  const results = document.getElementById("palette-results");
  let selectedIdx = 0;

  function openPalette() {{
    overlay.classList.add("open");
    input.value = "";
    renderResults("");
    setTimeout(() => input.focus(), 30);
  }}
  function closePalette() {{ overlay.classList.remove("open"); }}

  function fuzzyMatch(query, text) {{
    // Simple subsequence fuzzy match — good enough for short lists
    if (!query) return true;
    let q = 0;
    for (let i = 0; i < text.length && q < query.length; i++) {{
      if (text[i].toLowerCase() === query[q].toLowerCase()) q++;
    }}
    return q === query.length;
  }}

  function renderResults(query) {{
    const q = query.trim().toLowerCase();
    const matched = PALETTE_INDEX.filter(item => fuzzyMatch(q, item.label)).slice(0, 30);
    if (matched.length === 0) {{
      results.innerHTML = '<div class="empty-msg">No matches.</div>';
      return;
    }}
    selectedIdx = 0;
    results.innerHTML = matched.map((item, i) =>
      `<li class="${{i === 0 ? 'selected' : ''}}" role="option" data-idx="${{i}}">` +
      `  <span class="kind">${{item.kind}}</span>` +
      `  <span>${{item.label.replace(/[<>&]/g, c => ({{'<':'&lt;','>':'&gt;','&':'&amp;'}})[c])}}</span>` +
      `</li>`
    ).join("");
  }}

  document.getElementById("palette-btn").addEventListener("click", openPalette);
  document.addEventListener("keydown", (e) => {{
    const isMod = e.metaKey || e.ctrlKey;
    if (isMod && (e.key === "k" || e.key === "K")) {{
      e.preventDefault();
      overlay.classList.contains("open") ? closePalette() : openPalette();
    }} else if (e.key === "Escape" && overlay.classList.contains("open")) {{
      closePalette();
    }} else if (overlay.classList.contains("open") && (e.key === "ArrowDown" || e.key === "ArrowUp")) {{
      e.preventDefault();
      const items = results.querySelectorAll("li");
      if (items.length === 0) return;
      items[selectedIdx]?.classList.remove("selected");
      selectedIdx = (selectedIdx + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      items[selectedIdx]?.classList.add("selected");
      items[selectedIdx]?.scrollIntoView({{ block: "nearest" }});
    }}
  }});
  overlay.addEventListener("click", (e) => {{ if (e.target === overlay) closePalette(); }});
  input.addEventListener("input", (e) => renderResults(e.target.value));

  // ── Optional live API fetch (Wave C.9) — graceful fallback ────────────
  // The static export already has data; this just augments with cost/quality
  // sparklines and switches the audit trail to the live tail.
  async function tryFetchLive() {{
    try {{
      const ctrl = new AbortController();
      const timeoutId = setTimeout(() => ctrl.abort(), 1500);
      const res = await fetch(`${{API_BASE}}/api/dashboard`, {{ signal: ctrl.signal, credentials: "omit" }});
      clearTimeout(timeoutId);
      if (!res.ok) throw new Error(`HTTP ${{res.status}}`);
      const data = await res.json();
      document.getElementById("live-badge").classList.add("on");
      hydrateLive(data);
      tryWebSocketAudit();
    }} catch (e) {{
      // Silent — static snapshot remains in place. This is the offline-first contract.
    }}
  }}

  function hydrateLive(data) {{
    const grid = document.getElementById("sparkline-grid");
    let shown = false;
    if (Array.isArray(data.cost_trend) && data.cost_trend.length) {{
      drawSparkline("cost-spark", data.cost_trend);
      const sum = data.cost_trend.reduce((a, b) => a + b, 0);
      document.getElementById("cost-stat").textContent = "$" + sum.toFixed(2);
      shown = true;
    }} else if (typeof data.total_cost === "number") {{
      document.getElementById("cost-stat").textContent = "$" + data.total_cost.toFixed(2);
      shown = true;
    }}
    if (Array.isArray(data.quality_trend) && data.quality_trend.length) {{
      drawSparkline("quality-spark", data.quality_trend);
      const avg = data.quality_trend.reduce((a, b) => a + b, 0) / data.quality_trend.length;
      document.getElementById("quality-stat").textContent = avg.toFixed(2);
      shown = true;
    }} else if (typeof data.quality_average === "number") {{
      document.getElementById("quality-stat").textContent = data.quality_average.toFixed(2);
      shown = true;
    }}
    if (shown) grid.removeAttribute("hidden");
  }}

  // ── Inline SVG sparkline (Wave B.8) ───────────────────────────────────
  function drawSparkline(svgId, values) {{
    const svg = document.getElementById(svgId);
    if (!svg || !values || values.length === 0) return;
    const W = 200, H = 60, P = 4;
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    const step = (W - 2 * P) / Math.max(values.length - 1, 1);
    const pts = values.map((v, i) => {{
      const x = P + i * step;
      const y = H - P - ((v - min) / range) * (H - 2 * P);
      return [x, y];
    }});
    const linePath = "M " + pts.map(([x, y]) => `${{x.toFixed(1)}} ${{y.toFixed(1)}}`).join(" L ");
    const fillPath = linePath + ` L ${{(W-P).toFixed(1)}} ${{(H-P).toFixed(1)}} L ${{P.toFixed(1)}} ${{(H-P).toFixed(1)}} Z`;
    const last = pts[pts.length - 1];
    svg.innerHTML =
      `<path class="fill" d="${{fillPath}}" />` +
      `<path class="line" d="${{linePath}}" />` +
      `<circle cx="${{last[0].toFixed(1)}}" cy="${{last[1].toFixed(1)}}" r="3" />`;
  }}

  // ── WebSocket audit-trail tail (Wave C.10) ────────────────────────────
  function tryWebSocketAudit() {{
    try {{
      const wsUrl = API_BASE.replace(/^http/, "ws") + "/ws";
      const ws = new WebSocket(wsUrl);
      ws.onmessage = (ev) => {{
        try {{
          const evt = typeof ev.data === "string" ? JSON.parse(ev.data) : null;
          if (evt && evt.type === "audit") prependAuditRow(evt);
        }} catch (e) {{}}
      }};
      ws.onerror = () => {{ try {{ ws.close(); }} catch (e) {{}} }};
    }} catch (e) {{
      // WebSocket optional; static snapshot remains authoritative.
    }}
  }}

  function prependAuditRow(evt) {{
    const tbody = document.querySelector("article[aria-labelledby='card-audit'] tbody");
    if (!tbody) return;
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td data-label="Timestamp">${{evt.timestamp || new Date().toISOString()}}</td>` +
      `<td data-label="Tool"><span class="tag">${{evt.tool || "?"}}</span></td>` +
      `<td data-label="Exit" style="color:${{evt.exit_code ? 'var(--red)' : 'var(--green)'}};">${{evt.exit_code ?? 0}}</td>` +
      `<td data-label="Duration">${{evt.duration_ms ?? "?"}}ms</td>`;
    tbody.insertBefore(tr, tbody.firstChild);
    while (tbody.children.length > 50) tbody.removeChild(tbody.lastChild);
  }}

  // Kick it off — non-blocking, errors swallowed
  tryFetchLive();
}})();
</script>

</body>
</html>"""


def _palette_index(
    *,
    done_items: list,
    next_items: list,
    sessions: list[dict],
    files: list[str],
) -> list[dict]:
    """Build the JSON payload the Cmd+K palette searches over.

    Each entry has a ``kind`` (one of done/next/session/file) and a
    ``label`` (the searchable string). Kept small to keep the inline
    JSON manageable on large projects."""
    out: list[dict] = []
    for item in done_items[-40:]:
        out.append({"kind": "done", "label": str(item)[:160]})
    for item in next_items[:40]:
        out.append({"kind": "next", "label": str(item)[:160]})
    for entry in sessions[:30]:
        label = f"S{entry.get('session', '?')} · {entry.get('date', '')} · {str(entry.get('summary', ''))[:120]}"
        out.append({"kind": "session", "label": label})
    for f in files[:40]:
        out.append({"kind": "file", "label": f})
    return out


def _render_list(items: list, empty_msg: str, bullet: bool = False, css_class: str = "") -> str:
    if not items:
        return f'<p class="empty">{_esc(empty_msg)}</p>'
    cls = css_class or "done-list"
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
        # Wave B.4: expanded summary truncation 70 → 160 chars
        summary = _esc(str(entry.get("summary", ""))[:160])
        fc = _esc(str(entry.get("file_count", 0)))
        files = entry.get("changed_files", [])[:4]
        file_tags = " ".join(
            f'<span class="tag">{_esc(f.split("/")[-1] if "/" in f else f)}</span>'
            for f in files
        )
        rows += (
            f"<tr>"
            f"<td scope='row'>{n}</td>"
            f"<td>{date}</td>"
            f"<td>{summary}</td>"
            f"<td>{fc}</td>"
            f"<td>{file_tags}</td>"
            f"</tr>"
        )
    return f"""<div class="table-wrap"><table role="table">
  <thead><tr><th scope="col">#</th><th scope="col">Date</th><th scope="col">Summary</th><th scope="col">Files</th><th scope="col">Changed</th></tr></thead>
  <tbody>{rows}</tbody>
</table></div>"""


def _render_heatmap(top_files: list[tuple[str, int]]) -> str:
    if not top_files:
        return '<p class="empty">No file change data yet.</p>'
    max_count = max(c for _, c in top_files) if top_files else 1
    rows = ""
    for f, count in top_files:
        short = f.split("/")[-1] if "/" in f else f.split("\\")[-1] if "\\" in f else f
        pct = int((count / max_count) * 100)
        rows += f"""
<div style="margin-bottom:10px;" title="{_esc(f)}">
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
        lines.append(f'<div class="git-status">{_esc(status[:1200])}</div>')
        lines.append("<br>")
    if commits:
        rows = ""
        for c in commits:
            h = _esc(c.get("hash", "?"))
            d = _esc(c.get("date", "?"))
            m = _esc(c.get("message", "")[:80])
            rows += (
                f"<tr>"
                f"<td class='commit-hash' scope='row'>{h}</td>"
                f"<td>{d}</td>"
                f"<td>{m}</td>"
                f"</tr>"
            )
        lines.append(f"""<div class="table-wrap"><table role="table">
  <thead><tr><th scope="col">Hash</th><th scope="col">Date</th><th scope="col">Message</th></tr></thead>
  <tbody>{rows}</tbody>
</table></div>""")
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
        rows += (
            f"<tr>"
            f"<td scope='row'>{ts}</td>"
            f"<td><span class='tag'>{tool}</span></td>"
            f"<td style='color:{ec_color};'>{ec}</td>"
            f"<td>{dur}ms</td>"
            f"</tr>"
        )
    return f"""<div class="table-wrap"><table role="table">
  <thead><tr><th scope="col">Timestamp</th><th scope="col">Tool</th><th scope="col">Exit</th><th scope="col">Duration</th></tr></thead>
  <tbody>{rows}</tbody>
</table></div>"""
