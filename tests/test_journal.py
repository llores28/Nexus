"""Unit tests for the Nexus journal pipeline.

Covers pure logic (CC parser, grouping, slugify, ADR numbering, hook status)
and side-effecting helpers exercised against tmp_path. Git-backed paths are
covered indirectly through `run_journal` calls — they degrade gracefully to
the no-git fallback in tmp_path, which exercises the resilience the pipeline
needs in the real world.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from nexus.cli.tools.journal import (
    HEALTH_STALE_DAYS,
    HOOK_VERSION,
    MAX_DONE_KEEP,
    NEXUS_AGENTS_BEGIN,
    NEXUS_AGENTS_END,
    _append_daily_journal,
    _backfill_commits,
    _classify_done_item,
    _diagnose_journal,
    _group_done_by_type,
    _git_run,
    _handoff_payload,
    _hook_status,
    _load_state,
    _next_decision_number,
    _parse_conventional_commit,
    _save_state,
    _render_state_summary_md,
    _should_roll_session,
    _slugify,
    _upsert_agents_md,
    run_journal,
)


def test_git_output_is_decoded_as_utf8(monkeypatch, tmp_path):
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="modernize dashboard — theme", stderr="")

    monkeypatch.setattr("nexus.cli.tools.journal.subprocess.run", fake_run)
    code, stdout, _ = _git_run(["log", "-1"], tmp_path)
    assert code == 0
    assert "—" in stdout
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


def test_v2_handoff_has_exact_compaction_fields(tmp_path):
    state = _load_state(tmp_path)
    state["intent"] = "Ship compact context"
    state["done"] = ["added context audit"]
    state["decision_notes"] = ["AGENTS.md is canonical"]
    state["next"] = ["run tests"]
    state["blockers"] = ["none external"]
    payload = _handoff_payload(state)
    assert list(payload) == [
        "intent", "changes_made", "decisions_taken", "next_steps_and_blockers"
    ]


def test_state_summary_has_four_headings_and_at_most_80_lines(tmp_path):
    state = _load_state(tmp_path)
    state["intent"] = "Keep context small"
    state["done"] = [f"change {i}" for i in range(100)]
    state["decision_notes"] = [f"decision {i}" for i in range(100)]
    state["next"] = [f"next {i}" for i in range(100)]
    state["blockers"] = [f"blocker {i}" for i in range(100)]
    rendered = _render_state_summary_md(state, None)
    headings = [line for line in rendered.splitlines() if line.startswith("# ")]
    assert headings == [
        "# Intent", "# Changes Made", "# Decisions Taken", "# Next Steps / Blockers"
    ]
    assert len(rendered.splitlines()) <= 80


# --------------------------------------------------------------------------
# Conventional Commits parser
# --------------------------------------------------------------------------

class TestConventionalCommitParser:
    def test_simple(self):
        r = _parse_conventional_commit("feat: add thing")
        assert r["type"] == "feat"
        assert r["scope"] is None
        assert r["breaking"] is False
        assert r["summary"] == "add thing"

    def test_with_scope(self):
        r = _parse_conventional_commit("fix(auth): null check")
        assert r["scope"] == "auth"
        assert r["type"] == "fix"

    def test_breaking(self):
        r = _parse_conventional_commit("feat!: rewrite API")
        assert r["breaking"] is True

    def test_strips_hook_prefix(self):
        r = _parse_conventional_commit("git commit: feat: from hook")
        assert r["type"] == "feat"
        assert r["summary"] == "from hook"

    def test_non_conventional_returns_none(self):
        assert _parse_conventional_commit("random message") is None

    def test_classify_with_branch_tag(self):
        # The new Phase 3 entry format includes a branch tag inside [].
        item = "[2026-04-25 S2 main] git commit: feat: foo"
        assert _classify_done_item(item) == "feat"

    def test_classify_other_when_no_match(self):
        assert _classify_done_item("[2026-04-25 S2 main] random") == "other"

    def test_classify_strips_backfill_tag(self):
        # Regression: `_backfill_commits` writes entries as
        # `[YYYY-MM-DD Sn branch] [backfill] git commit: feat: foo`.
        # The classifier used to do split("] ", 1)[-1] which only stripped
        # ONE leading bracket, leaving `[backfill] git commit: feat: foo`
        # to fail the CC regex and fall through to "Other". With multi-tag
        # stripping, all backfilled entries classify by their actual CC type.
        item = "[2026-04-25 S1 main] [backfill] git commit: feat: alpha"
        assert _classify_done_item(item) == "feat"
        item2 = "[2026-04-25 S1 main] [backfill] git commit: fix: beta"
        assert _classify_done_item(item2) == "fix"
        item3 = "[2026-04-25 S1 main] [backfill] git commit: docs: gamma"
        assert _classify_done_item(item3) == "docs"

    def test_classify_strips_backfill_in_grouping(self):
        # Same fix surfaced through the grouping path.
        items = [
            "[2026-04-25 S1 main] [backfill] git commit: feat: A",
            "[2026-04-25 S1 main] [backfill] git commit: fix: B",
            "[2026-04-25 S1 main] git commit: feat: C",
        ]
        groups = dict(_group_done_by_type(items))
        assert "Features" in groups and len(groups["Features"]) == 2
        assert "Fixes" in groups and len(groups["Fixes"]) == 1
        assert "Other" not in groups, (
            "no entry should land in Other once [backfill] is stripped"
        )


# --------------------------------------------------------------------------
# Grouping
# --------------------------------------------------------------------------

class TestGrouping:
    def test_orders_groups(self):
        items = [
            "[2026-04-25 S1 main] git commit: docs: x",
            "[2026-04-25 S1 main] git commit: feat: y",
            "[2026-04-25 S1 main] git commit: fix: z",
        ]
        groups = _group_done_by_type(items)
        labels = [label for label, _ in groups]
        assert labels.index("Features") < labels.index("Fixes") < labels.index("Docs")

    def test_empty(self):
        assert _group_done_by_type([]) == []

    def test_unrecognized_lands_in_other(self):
        groups = dict(_group_done_by_type(["raw note", "another raw"]))
        assert "Other" in groups
        assert len(groups["Other"]) == 2


# --------------------------------------------------------------------------
# Slugify and ADR numbering
# --------------------------------------------------------------------------

class TestSlugify:
    def test_basic(self):
        assert _slugify("Hello World") == "hello-world"

    def test_strips_punct(self):
        assert _slugify("Use feature flags!") == "use-feature-flags"

    def test_caps_at_50(self):
        assert len(_slugify("a" * 200)) <= 50

    def test_empty_falls_back(self):
        assert _slugify("!!!") == "decision"


class TestDecisionNumbering:
    def test_empty_dir(self, tmp_path):
        assert _next_decision_number(tmp_path) == 1

    def test_finds_next(self, tmp_path):
        (tmp_path / "0001-foo.md").write_text("")
        (tmp_path / "0003-bar.md").write_text("")
        assert _next_decision_number(tmp_path) == 4

    def test_ignores_non_madr(self, tmp_path):
        (tmp_path / "README.md").write_text("")
        (tmp_path / "0007-x.md").write_text("")
        assert _next_decision_number(tmp_path) == 8


# --------------------------------------------------------------------------
# State persistence + trim
# --------------------------------------------------------------------------

class TestStateLifecycle:
    def test_load_defaults(self, tmp_path):
        state = _load_state(tmp_path)
        assert state["session_number"] == 0
        assert state["done"] == []
        assert state["session_branch"] is None

    def test_save_and_load_roundtrip(self, tmp_path):
        state = _load_state(tmp_path)
        state["status"] = "DONE"
        state["done"].append("[2026-04-25 S1 main] test")
        _save_state(tmp_path, state)
        reloaded = _load_state(tmp_path)
        assert reloaded["status"] == "DONE"
        assert reloaded["done"] == ["[2026-04-25 S1 main] test"]

    def test_done_trim_to_max_keep(self, tmp_path):
        state = _load_state(tmp_path)
        state["done"] = [f"item-{i}" for i in range(MAX_DONE_KEEP + 50)]
        _save_state(tmp_path, state)
        reloaded = _load_state(tmp_path)
        assert len(reloaded["done"]) == MAX_DONE_KEEP
        # Newest entries are preserved
        assert reloaded["done"][-1] == f"item-{MAX_DONE_KEEP + 49}"

    def test_state_md_renders_cc_groups(self, tmp_path):
        state = _load_state(tmp_path)
        state["done"] = [
            "[2026-04-25 S1 main] git commit: feat: alpha",
            "[2026-04-25 S1 main] git commit: fix: beta",
        ]
        _save_state(tmp_path, state)
        md = (tmp_path / ".nexus" / "state.md").read_text(encoding="utf-8")
        assert "### Features" in md
        assert "### Fixes" in md
        assert "alpha" in md


# --------------------------------------------------------------------------
# Daily journal
# --------------------------------------------------------------------------

class TestDailyJournal:
    def test_creates_directory_and_file(self, tmp_path):
        path = _append_daily_journal(tmp_path, "test entry", branch="main", session_n=1)
        assert path is not None
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "test entry" in content
        assert "[main]" in content
        assert content.startswith("# 20")  # date header

    def test_appends_multiple_in_same_day(self, tmp_path):
        when = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)
        _append_daily_journal(tmp_path, "first", "main", 1, when)
        _append_daily_journal(tmp_path, "second", "main", 1, when)
        files = list((tmp_path / ".nexus" / "journal").rglob("*.md"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "first" in content
        assert "second" in content

    def test_no_branch_tag_when_none(self, tmp_path):
        path = _append_daily_journal(tmp_path, "headless", branch=None, session_n=1)
        content = path.read_text(encoding="utf-8")
        assert "[None]" not in content
        assert "headless" in content

    def test_append_is_idempotent_for_identical_line(self, tmp_path):
        # Regression: running `journal health refresh` twice used to write
        # duplicate entries to the same daily file (backfill passes the
        # commit's authored `when`, so two passes produce byte-identical
        # lines). The second append is now a no-op.
        when = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)
        path1 = _append_daily_journal(tmp_path, "feat: same commit", "main", 1, when)
        path2 = _append_daily_journal(tmp_path, "feat: same commit", "main", 1, when)
        path3 = _append_daily_journal(tmp_path, "feat: same commit", "main", 1, when)
        assert path1 == path2 == path3
        content = path1.read_text(encoding="utf-8")
        assert content.count("feat: same commit") == 1, (
            "identical line was written more than once — daily-file dedup broken"
        )

    def test_append_distinct_lines_still_appended(self, tmp_path):
        # The dedup must NOT collapse legitimately distinct entries (different
        # message, time, session, or branch).
        when = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)
        _append_daily_journal(tmp_path, "feat: A", "main", 1, when)
        _append_daily_journal(tmp_path, "feat: B", "main", 1, when)  # different msg
        _append_daily_journal(tmp_path, "feat: A", "main", 2, when)  # different session
        path = _append_daily_journal(
            tmp_path, "feat: A", "feature-x", 1, when,                # different branch
        )
        content = path.read_text(encoding="utf-8")
        # A appears 3 times (S1/main, S2/main, S1/feature-x); B once.
        assert content.count("feat: A") == 3
        assert content.count("feat: B") == 1


# --------------------------------------------------------------------------
# Session staleness
# --------------------------------------------------------------------------

class TestSessionRoll:
    # Pin "now" to a non-edge UTC time so hours_ago=0.5 never crosses
    # midnight UTC and triggers the new-date rule unintentionally.
    _NOW = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)

    @classmethod
    def _state(cls, hours_ago=0.0, branch="main", session_n=1):
        start = cls._NOW - timedelta(hours=hours_ago)
        return {
            "session_number": session_n,
            "session_start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "session_branch": branch,
        }

    def test_fresh_session_does_not_roll(self):
        should_roll, _ = _should_roll_session(
            self._state(hours_ago=0.5), git_root=None, now=self._NOW,
        )
        assert should_roll is False

    def test_idle_triggers_roll(self):
        should_roll, reason = _should_roll_session(
            self._state(hours_ago=5), git_root=None, now=self._NOW,
        )
        assert should_roll is True
        assert "idle" in reason

    def test_no_session_no_roll(self):
        state = {"session_number": 0, "session_start_time": None}
        should_roll, _ = _should_roll_session(state, git_root=None, now=self._NOW)
        assert should_roll is False

    def test_new_utc_date_triggers_roll(self):
        # Session started yesterday UTC; even within the idle window, a date
        # change should still roll. Regression guard for the time-of-day flake
        # that the now= injection was added to fix.
        yesterday_noon = self._NOW - timedelta(days=1)
        state = {
            "session_number": 1,
            "session_start_time": yesterday_noon.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "session_branch": "main",
        }
        should_roll, reason = _should_roll_session(state, git_root=None, now=self._NOW)
        assert should_roll is True
        # "idle" wins because >4h elapsed; either reason is acceptable.
        assert "idle" in reason or "new date" in reason


# --------------------------------------------------------------------------
# Hook detection
# --------------------------------------------------------------------------

class TestHookStatus:
    def test_missing(self, tmp_path):
        assert _hook_status(tmp_path / "absent") == "missing"

    def test_current(self, tmp_path):
        p = tmp_path / "hook"
        p.write_text(f"#!/bin/sh\n# nexus-journal-hook v{HOOK_VERSION}\necho hi\n")
        assert _hook_status(p) == "current"

    def test_outdated(self, tmp_path):
        # An older Nexus hook (no v2 marker) should be flagged for upgrade.
        p = tmp_path / "hook"
        p.write_text("#!/bin/sh\n# Nexus journal — old style\nbs_cli stuff\n")
        assert _hook_status(p) == "outdated"

    def test_foreign(self, tmp_path):
        p = tmp_path / "hook"
        p.write_text("#!/bin/sh\necho 'unrelated'\n")
        assert _hook_status(p) == "foreign"


# --------------------------------------------------------------------------
# AGENTS.md upsert
# --------------------------------------------------------------------------

class TestAgentsUpsert:
    def test_creates_when_missing(self, tmp_path):
        action = _upsert_agents_md(tmp_path)
        assert action == "created"
        content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
        assert NEXUS_AGENTS_BEGIN in content
        assert NEXUS_AGENTS_END in content

    def test_inserts_when_no_markers(self, tmp_path):
        agents = tmp_path / "AGENTS.md"
        agents.write_text("# Existing\n\nUser content here.\n")
        action = _upsert_agents_md(tmp_path)
        assert action == "inserted"
        content = agents.read_text(encoding="utf-8")
        assert "User content here." in content
        assert NEXUS_AGENTS_BEGIN in content

    def test_replaces_existing_block_preserves_outside_content(self, tmp_path):
        agents = tmp_path / "AGENTS.md"
        agents.write_text(
            f"# Existing\n\nBefore.\n\n{NEXUS_AGENTS_BEGIN}\nOLD CONTENT\n{NEXUS_AGENTS_END}\nAfter.\n"
        )
        action = _upsert_agents_md(tmp_path)
        assert action == "updated"
        content = agents.read_text(encoding="utf-8")
        assert "OLD CONTENT" not in content
        assert "Before." in content
        assert "After." in content

    def test_idempotent(self, tmp_path):
        _upsert_agents_md(tmp_path)
        action2 = _upsert_agents_md(tmp_path)
        assert action2 == "unchanged"


# --------------------------------------------------------------------------
# CLI dispatch (next / blocker / decision)
# --------------------------------------------------------------------------

class TestRunJournal:
    def test_next_add_persists(self, tmp_path):
        run_journal("next", ("add", "task one"), "json", str(tmp_path))
        run_journal("next", ("add", "task two"), "json", str(tmp_path))
        state = _load_state(tmp_path)
        assert "task one" in state["next"]
        assert "task two" in state["next"]

    def test_next_done_moves_to_done(self, tmp_path):
        run_journal("next", ("add", "queued task"), "json", str(tmp_path))
        run_journal("next", ("done", "queued"), "json", str(tmp_path))
        state = _load_state(tmp_path)
        assert state["next"] == []
        assert any("queued task" in d for d in state["done"])

    def test_next_done_writes_to_daily_file(self, tmp_path):
        run_journal("next", ("add", "demo"), "json", str(tmp_path))
        run_journal("next", ("done", "demo"), "json", str(tmp_path))
        daily = list((tmp_path / ".nexus" / "journal").rglob("*.md"))
        assert daily, "daily journal file should exist after next done"
        assert "demo" in daily[0].read_text(encoding="utf-8")

    def test_blocker_add(self, tmp_path):
        run_journal("blocker", ("add", "tests broken"), "json", str(tmp_path))
        state = _load_state(tmp_path)
        assert "tests broken" in state["blockers"]

    def test_blocker_clear(self, tmp_path):
        run_journal("blocker", ("add", "to be cleared"), "json", str(tmp_path))
        run_journal("blocker", ("clear",), "json", str(tmp_path))
        state = _load_state(tmp_path)
        assert state["blockers"] == []

    def test_decision_add_creates_adr(self, tmp_path):
        run_journal("decision", ("add", "Sample decision"), "json", str(tmp_path))
        adrs = list((tmp_path / "docs" / "decisions").glob("*.md"))
        assert len(adrs) == 1
        assert adrs[0].name.startswith("0001-")
        # Decision creation auto-logs to journal.
        state = _load_state(tmp_path)
        assert any("decision: ADR 0001" in d for d in state["done"])

    def test_decision_add_increments(self, tmp_path):
        run_journal("decision", ("add", "First"), "json", str(tmp_path))
        run_journal("decision", ("add", "Second"), "json", str(tmp_path))
        adrs = sorted((tmp_path / "docs" / "decisions").glob("*.md"))
        assert [a.name[:4] for a in adrs] == ["0001", "0002"]

    def test_log_records_session_and_daily(self, tmp_path):
        run_journal("log", ("hello world",), "json", str(tmp_path), no_export=True)
        state = _load_state(tmp_path)
        # Auto-bootstrapped session 1
        assert state["session_number"] >= 1
        assert any("hello world" in d for d in state["done"])
        # Daily file written
        daily = list((tmp_path / ".nexus" / "journal").rglob("*.md"))
        assert daily and "hello world" in daily[0].read_text(encoding="utf-8")

    def test_health_missing_when_no_state(self, tmp_path):
        d = _diagnose_journal(tmp_path)
        assert d["status"] == "missing"
        assert d["issues"]

    def test_health_ok_after_log(self, tmp_path):
        run_journal("log", ("first entry",), "json", str(tmp_path), no_export=True)
        d = _diagnose_journal(tmp_path)
        # No git in tmp_path so commit drift can't surface; status should be ok.
        assert d["status"] == "ok"
        assert d["issues"] == []

    def test_health_drift_when_done_empty_but_git_has_history(self, tmp_path):
        """Regression: a freshly created state.json with empty done MUST be
        flagged as drift when git has commits — even though `last_updated` is
        "now" (it was just saved). This is the case `nexus init --upgrade`
        hits on a project that predates Phase 1 hooks."""
        import subprocess

        # Build a minimal git repo with one commit.
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@x", "PATH": __import__("os").environ.get("PATH", "")}
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, env=env)
        (tmp_path / "README.md").write_text("# test\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, env=env)
        subprocess.run(
            ["git", "commit", "-q", "-m", "feat: initial commit"],
            cwd=tmp_path, check=True, env=env,
        )

        # Save a fresh state.json with empty done and last_updated = now (this
        # mimics `_persist_tier` writing state during init upgrade).
        state = _load_state(tmp_path)
        _save_state(tmp_path, state)
        assert state["done"] == []

        # The diagnostic must surface drift, not "ok", because the commit
        # subject is not in done.
        d = _diagnose_journal(tmp_path)
        assert d["status"] == "drift", (
            f"expected drift (commit not in empty done), got {d['status']}: {d['issues']}"
        )
        assert d["missing_commits"]
        assert any("initial commit" in c["subject"] for c in d["missing_commits"])

    def test_health_stale_after_long_idle(self, tmp_path):
        run_journal("log", ("seed",), "json", str(tmp_path), no_export=True)
        # Forge an old last_updated to simulate age.
        state = _load_state(tmp_path)
        old = (datetime.now(timezone.utc) - timedelta(days=HEALTH_STALE_DAYS + 5))
        state["last_updated"] = old.strftime("%Y-%m-%dT%H:%M:%SZ")
        _save_state(tmp_path, state)
        # _save_state overwrites last_updated, so write the JSON directly.
        import json as _json
        path = tmp_path / ".nexus" / "state.json"
        raw = _json.loads(path.read_text(encoding="utf-8"))
        raw["last_updated"] = old.strftime("%Y-%m-%dT%H:%M:%SZ")
        path.write_text(_json.dumps(raw), encoding="utf-8")

        d = _diagnose_journal(tmp_path)
        assert d["status"] == "stale"
        assert any("last_updated" in i for i in d["issues"])

    def test_backfill_appends_done_and_daily(self, tmp_path):
        run_journal("log", ("seed",), "json", str(tmp_path), no_export=True)
        state = _load_state(tmp_path)
        before_done = len(state["done"])
        missing = [
            {"hash": "abc12345", "iso_date": "2026-04-25T10:00:00+00:00",
             "subject": "fix: synthetic commit", "full_hash": "abc12345..."},
            {"hash": "def67890", "iso_date": "2026-04-25T11:00:00+00:00",
             "subject": "feat: another", "full_hash": "def67890..."},
        ]
        written = _backfill_commits(tmp_path, state, missing)
        _save_state(tmp_path, state)
        assert written == 2
        reloaded = _load_state(tmp_path)
        assert len(reloaded["done"]) == before_done + 2
        assert any("[backfill]" in d for d in reloaded["done"])
        # Daily file at the commit's date should have the entries.
        daily = tmp_path / ".nexus" / "journal" / "2026-04" / "25.md"
        assert daily.exists()
        content = daily.read_text(encoding="utf-8")
        assert "fix: synthetic commit" in content
        assert "feat: another" in content

    def test_health_refresh_persists_backfill_to_state(self, tmp_path, capsys, monkeypatch):
        # Regression for a bug where _cmd_health called _backfill_commits but
        # forgot to _save_state, so daily files were written but state.done
        # never grew — every subsequent `health` call kept reporting drift.
        run_journal("log", ("seed",), "json", str(tmp_path), no_export=True)
        before = len(_load_state(tmp_path)["done"])

        # Force the diagnostic to report missing commits without needing real git.
        from nexus.cli.tools import journal as journal_mod
        fake_missing = [
            {"hash": "11111111", "iso_date": "2026-04-25T09:00:00+00:00",
             "subject": "fix: pretend missing"},
            {"hash": "22222222", "iso_date": "2026-04-25T10:00:00+00:00",
             "subject": "feat: pretend other"},
        ]
        real_diagnose = journal_mod._diagnose_journal

        def fake_diagnose(pd):
            d = real_diagnose(pd)
            d["status"] = "drift"
            d["missing_commits"] = fake_missing
            d["issues"] = ["2 commit(s) in recent history are not reflected in done."]
            return d

        monkeypatch.setattr(journal_mod, "_diagnose_journal", fake_diagnose)
        capsys.readouterr()
        run_journal("health", ("refresh",), "json", str(tmp_path))

        reloaded = _load_state(tmp_path)
        assert len(reloaded["done"]) == before + 2, (
            "health refresh must persist backfilled commits to state.json"
        )
        assert any("[backfill]" in d for d in reloaded["done"])

    def test_health_refresh_idempotent_on_clean_state(self, tmp_path, capsys):
        run_journal("log", ("seed",), "json", str(tmp_path), no_export=True)
        capsys.readouterr()
        run_journal("health", ("refresh",), "json", str(tmp_path))
        # Run twice; second call should be ok (no double-backfill).
        run_journal("health", ("refresh",), "json", str(tmp_path))
        out = capsys.readouterr().out
        # Final status should be ok, and we should not see a non-zero backfill
        # in the second invocation.
        # Look at the LAST emitted JSON document.
        import json as _json
        decoder = _json.JSONDecoder()
        docs = []
        idx = 0
        while idx < len(out):
            stripped = out[idx:].lstrip()
            if not stripped:
                break
            offset = len(out[idx:]) - len(stripped)
            try:
                doc, end = decoder.raw_decode(stripped)
            except _json.JSONDecodeError:
                break
            docs.append(doc)
            idx += offset + end
        assert docs, "expected at least one JSON document from health refresh"
        last = docs[-1]
        assert last["details"]["backfilled"] == 0

    def test_blame_finds_done_and_daily_mentions(self, tmp_path, capsys):
        run_journal("log", ("touched src/foo.py",), "json", str(tmp_path), no_export=True)
        run_journal("log", ("unrelated edit elsewhere",), "json", str(tmp_path), no_export=True)
        # Drain stdout from the prep `log` calls so we only assert on blame's output.
        capsys.readouterr()
        run_journal("blame", ("src/foo.py",), "json", str(tmp_path))
        out = capsys.readouterr().out
        assert "touched src/foo.py" in out
        assert "unrelated edit elsewhere" not in out
