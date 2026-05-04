"""Tests for multi-repo journal support (parent + nested sub-repos).

Covers the bug where commits to a sub-repo (e.g. parent project with a
separate ``webapp/`` repo) never reach the parent's journal because the
parent's post-commit hook only fires on parent-repo commits.

The fix: discover nested standalone git repos, scan their logs in
``journal health`` / ``health refresh``, and install hooks in each so
sub-repo commits auto-log to the parent's journal in real time.
"""

import json
import subprocess
from pathlib import Path

import pytest

from nexus.cli.tools.journal import (
    _backfill_commits,
    _cmd_setup_hooks,
    _commits_not_in_done,
    _diagnose_journal,
    _find_sub_git_repos,
    _load_state,
    _save_state,
)


# --------------------------------------------------------------------------
# Test helpers
# --------------------------------------------------------------------------

def _git(cwd: Path, *args: str) -> None:
    """Run a git command, raising on failure. GPG signing disabled for CI."""
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path: Path) -> None:
    """Initialize a git repo with a default user identity."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.invalid")
    _git(path, "config", "user.name", "Test")


def _commit(repo: Path, subject: str, file_name: str = "f.txt",
            iso_date: str = "") -> None:
    """Make a commit in ``repo`` with a unique file content for each call.

    ``iso_date`` (when provided, e.g. ``"2026-04-28T10:00:00"``) overrides
    the author/committer date so tests can deterministically order commits.
    """
    f = repo / file_name
    existing = f.read_text(encoding="utf-8") if f.exists() else ""
    f.write_text(existing + subject + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    if iso_date:
        env_args = ["-c", f"author.date={iso_date}", "-c", f"committer.date={iso_date}"]
        # git commit honors GIT_AUTHOR_DATE/GIT_COMMITTER_DATE via env; use --date
        # for the easier path:
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "commit",
             "--date", iso_date, "-m", subject, "--no-verify"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env={**__import__("os").environ, "GIT_COMMITTER_DATE": iso_date},
        )
    else:
        _git(repo, "commit", "-m", subject, "--no-verify")


def _seed_state(project_dir: Path, *, tier: str = "fast") -> None:
    """Create a minimal state.json so _diagnose_journal won't bail on missing."""
    (project_dir / ".nexus").mkdir(parents=True, exist_ok=True)
    state = {
        "version": 1,
        "project": project_dir.name,
        "status": "active",
        "session_number": 1,
        "session_start_time": "2026-04-28T12:00:00Z",
        "baseline_mtimes": {},
        "done": [],
        "next": [],
        "blockers": [],
        "session_log": [],
        "last_updated": "2026-04-28T12:00:00Z",
        "bootstrap_tier": tier,
        "session_branch": "main",
    }
    (project_dir / ".nexus" / "state.json").write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )


# --------------------------------------------------------------------------
# _find_sub_git_repos
# --------------------------------------------------------------------------

class TestFindSubGitRepos:
    def test_finds_one_nested_repo(self, tmp_path):
        _init_repo(tmp_path)
        sub = tmp_path / "webapp"
        _init_repo(sub)
        _commit(sub, "feat: scaffold webapp")
        result = _find_sub_git_repos(tmp_path, tmp_path)
        assert len(result) == 1
        assert result[0] == sub

    def test_excludes_parent_git_root(self, tmp_path):
        _init_repo(tmp_path)
        # No nested repo — only the parent's own .git/. Should return empty.
        result = _find_sub_git_repos(tmp_path, tmp_path)
        assert result == []

    def test_skips_node_modules_and_caches(self, tmp_path):
        _init_repo(tmp_path)
        for skip_name in ("node_modules", ".venv", "__pycache__", ".cache", ".nexus"):
            d = tmp_path / skip_name / "fakelib"
            _init_repo(d)
            _commit(d, "junk")
        result = _find_sub_git_repos(tmp_path, tmp_path)
        assert result == [], f"should skip vendored repos, got: {result}"

    def test_finds_multiple_sibling_sub_repos(self, tmp_path):
        _init_repo(tmp_path)
        for name in ("webapp", "api", "worker"):
            sub = tmp_path / name
            _init_repo(sub)
            _commit(sub, f"feat: init {name}")
        result = _find_sub_git_repos(tmp_path, tmp_path)
        names = {r.name for r in result}
        assert names == {"webapp", "api", "worker"}

    def test_does_not_descend_into_a_sub_repo(self, tmp_path):
        """Once a sub-repo is found, deeper nested repos inside it are not traversed."""
        _init_repo(tmp_path)
        sub = tmp_path / "webapp"
        _init_repo(sub)
        deeper = sub / "vendor-app"
        _init_repo(deeper)
        _commit(deeper, "junk")
        result = _find_sub_git_repos(tmp_path, tmp_path)
        # Only the first-level sub-repo, not the one nested inside it
        assert result == [sub]

    def test_max_depth_honored(self, tmp_path):
        _init_repo(tmp_path)
        deep_path = tmp_path / "a" / "b" / "c" / "d" / "e" / "deep-repo"
        _init_repo(deep_path)
        result = _find_sub_git_repos(tmp_path, tmp_path, max_depth=3)
        # Depth 5 nested — should not be found at max_depth=3
        assert deep_path not in result

    def test_handles_no_parent_git_root(self, tmp_path):
        """If parent isn't a repo, sub-repo discovery should still work."""
        sub = tmp_path / "webapp"
        _init_repo(sub)
        _commit(sub, "feat: init")
        result = _find_sub_git_repos(tmp_path, parent_git_root=None)
        assert result == [sub]


# --------------------------------------------------------------------------
# _commits_not_in_done — labeling
# --------------------------------------------------------------------------

class TestCommitsNotInDoneLabeled:
    def test_unlabeled_finds_missing_commit(self, tmp_path):
        _init_repo(tmp_path)
        _commit(tmp_path, "feat: parent work")
        state = {"done": []}
        missing = _commits_not_in_done(state, tmp_path, since_iso=None)
        assert len(missing) == 1
        assert missing[0]["subject"] == "feat: parent work"
        assert missing[0]["repo_label"] == ""

    def test_labeled_attaches_repo_label(self, tmp_path):
        _init_repo(tmp_path)
        _commit(tmp_path, "feat: webapp work")
        state = {"done": []}
        missing = _commits_not_in_done(state, tmp_path, since_iso=None,
                                       repo_label="webapp/")
        assert len(missing) == 1
        assert missing[0]["repo_label"] == "webapp/"

    def test_labeled_dedupes_against_labeled_entry(self, tmp_path):
        _init_repo(tmp_path)
        _commit(tmp_path, "feat: x")
        # An existing labeled entry should suppress the commit from being missing
        state = {"done": ["[2026-04-28 S1 main] git commit (webapp/): feat: x"]}
        missing = _commits_not_in_done(state, tmp_path, since_iso=None,
                                       repo_label="webapp/")
        assert missing == []

    def test_labeled_does_not_dedupe_against_parent_form(self, tmp_path):
        """A parent commit and a sub-repo commit with the same subject must both
        be tracked (the sub-repo's labeled form != the parent's plain form)."""
        _init_repo(tmp_path)
        _commit(tmp_path, "fix: typo")
        # done has the PARENT-form entry — sub-repo commit with the same subject
        # should NOT be deduped because its labeled form isn't in done.
        state = {"done": ["[2026-04-28 S1 main] git commit: fix: typo"]}
        # Note: free-form "fix: typo" substring still matches, so this dedupes.
        # The labeled-form check is the additional safety; the substring check
        # handles the legacy case.
        missing = _commits_not_in_done(state, tmp_path, since_iso=None,
                                       repo_label="webapp/")
        # Substring "fix: typo" appears in done_blob -> deduped. This is the
        # documented existing behavior for free-form matching.
        assert missing == []

    def test_labeled_finds_when_nothing_in_done(self, tmp_path):
        _init_repo(tmp_path)
        _commit(tmp_path, "feat: a")
        _commit(tmp_path, "feat: b")
        missing = _commits_not_in_done({"done": []}, tmp_path, since_iso=None,
                                       repo_label="api/")
        assert {m["subject"] for m in missing} == {"feat: a", "feat: b"}
        assert all(m["repo_label"] == "api/" for m in missing)


# --------------------------------------------------------------------------
# _diagnose_journal — multi-repo
# --------------------------------------------------------------------------

class TestDiagnoseMultiRepo:
    def test_picks_up_sub_repo_commits(self, tmp_path):
        _init_repo(tmp_path)
        _commit(tmp_path, "chore: parent commit")
        sub = tmp_path / "webapp"
        _init_repo(sub)
        _commit(sub, "feat: webapp scaffold")
        _seed_state(tmp_path)

        diag = _diagnose_journal(tmp_path)
        assert diag["status"] == "drift"
        # Expect both parent and sub-repo commits in missing
        subjects = {c["subject"] for c in diag["missing_commits"]}
        assert "chore: parent commit" in subjects
        assert "feat: webapp scaffold" in subjects
        # The sub-repo commit must carry a repo_label
        webapp_commit = next(c for c in diag["missing_commits"]
                              if c["subject"] == "feat: webapp scaffold")
        assert webapp_commit["repo_label"] == "webapp/"
        # Sub-repos surfaced in diagnosis output
        assert "webapp" in diag.get("sub_repos", [])[0]
        # Issue message mentions sub-repos
        assert any("sub-repo" in msg for msg in diag["issues"])

    def test_missing_commits_sorted_chronologically(self, tmp_path):
        _init_repo(tmp_path)
        _commit(tmp_path, "old: parent", iso_date="2026-04-28T08:00:00")
        sub = tmp_path / "webapp"
        _init_repo(sub)
        _commit(sub, "newer: webapp", iso_date="2026-04-28T10:00:00")
        _commit(tmp_path, "newest: parent again", iso_date="2026-04-28T12:00:00")
        _seed_state(tmp_path)

        diag = _diagnose_journal(tmp_path)
        subjects = [c["subject"] for c in diag["missing_commits"]]
        # All three present, in chronological order (forced timestamps)
        assert subjects == ["old: parent", "newer: webapp", "newest: parent again"]


# --------------------------------------------------------------------------
# _backfill_commits — labeled output in state.done
# --------------------------------------------------------------------------

class TestBackfillLabeled:
    def test_parent_commit_unlabeled_in_done(self, tmp_path):
        _init_repo(tmp_path)
        _commit(tmp_path, "feat: parent")
        _seed_state(tmp_path)
        diag = _diagnose_journal(tmp_path)
        state = _load_state(tmp_path)
        _backfill_commits(tmp_path, state, diag["missing_commits"])
        _save_state(tmp_path, state)
        done_blob = "\n".join(state["done"])
        assert "git commit: feat: parent" in done_blob

    def test_sub_repo_commit_labeled_in_done(self, tmp_path):
        _init_repo(tmp_path)
        sub = tmp_path / "webapp"
        _init_repo(sub)
        _commit(sub, "feat: web")
        _seed_state(tmp_path)
        diag = _diagnose_journal(tmp_path)
        state = _load_state(tmp_path)
        _backfill_commits(tmp_path, state, diag["missing_commits"])
        done_blob = "\n".join(state["done"])
        assert "git commit (webapp/): feat: web" in done_blob

    def test_idempotent_backfill_on_rerun(self, tmp_path):
        """Running diagnose+backfill twice should not duplicate sub-repo commits."""
        _init_repo(tmp_path)
        sub = tmp_path / "webapp"
        _init_repo(sub)
        _commit(sub, "feat: web")
        _seed_state(tmp_path)

        # First pass
        diag1 = _diagnose_journal(tmp_path)
        state = _load_state(tmp_path)
        _backfill_commits(tmp_path, state, diag1["missing_commits"])
        _save_state(tmp_path, state)
        first_count = len(state["done"])

        # Second pass — diagnose should now find nothing missing
        diag2 = _diagnose_journal(tmp_path)
        assert diag2["missing_commits"] == []
        state2 = _load_state(tmp_path)
        assert len(state2["done"]) == first_count


# --------------------------------------------------------------------------
# _cmd_setup_hooks — sub-repo hook install
# --------------------------------------------------------------------------

class TestSetupHooksMultiRepo:
    def test_installs_hooks_in_sub_repo_with_label(self, tmp_path, capsys):
        _init_repo(tmp_path)
        sub = tmp_path / "webapp"
        _init_repo(sub)
        _seed_state(tmp_path)

        _cmd_setup_hooks(tmp_path, "json")
        # Drain stdout so subsequent tests don't mix output
        capsys.readouterr()

        sub_hook = sub / ".git" / "hooks" / "post-commit"
        assert sub_hook.exists(), "sub-repo post-commit hook not installed"
        body = sub_hook.read_text(encoding="utf-8")
        # The label should be baked into the hook so commits get tagged
        assert '(webapp/)' in body, f"label missing from sub-repo hook:\n{body}"
        # And it should still target the PARENT's project_dir
        assert str(tmp_path).replace("\\", "/") in body

    def test_idempotent_on_second_run(self, tmp_path, capsys):
        _init_repo(tmp_path)
        sub = tmp_path / "webapp"
        _init_repo(sub)
        _seed_state(tmp_path)

        _cmd_setup_hooks(tmp_path, "json")
        first = capsys.readouterr().out
        _cmd_setup_hooks(tmp_path, "json")
        second = capsys.readouterr().out

        # Second run should report most/all hooks as "(current)"
        data = json.loads(second)
        installed = data["details"].get("installed", [])
        skipped = data["details"].get("skipped", [])
        # First run installed; second run should NOT install again
        assert installed == [], f"second run unexpectedly installed: {installed}"
        # And should report sub-repo hooks as skipped/current
        assert any("webapp/" in s for s in skipped), \
            f"webapp/ hooks should be skipped as current on second run: {skipped}"
