"""Tests for nexus.cli.generators.

Covers each generator's output shape (frontmatter, stamp, rules) and the
runner's idempotency / managed-block behavior.
"""

import json
from pathlib import Path

import pytest

from nexus.cli.profile import NEXUS_VERSION, Profile, Rule, hash_profile
from nexus.cli.generators import (
    ALL_TARGETS,
    GeneratedFile,
    begin_marker,
    end_marker,
    overwrite_file,
    run_all,
    upsert_managed_block,
)


@pytest.fixture
def fastapi_profile():
    return Profile(
        nexus_version=NEXUS_VERSION,
        tier="team",
        project_name="demo-api",
        languages=("python",),
        frameworks=("fastapi",),
        package_managers=("pip",),
        test_runner="pytest",
        ci="github-actions",
        deployment="docker",
        rules=(
            Rule(id="no-secrets", text="No secrets in code."),
            Rule(id="py-no-shell-true", text="No shell=True.", applies_to=("**/*.py",)),
            Rule(id="fastapi-pydantic", text="Use Pydantic.", applies_to=("**/*.py",)),
        ),
    )


@pytest.fixture
def nextjs_profile():
    return Profile(
        nexus_version=NEXUS_VERSION,
        tier="fast",
        project_name="demo-web",
        languages=("typescript",),
        frameworks=("nextjs",),
        package_managers=("pnpm",),
        test_runner="vitest",
        rules=(
            Rule(id="no-secrets", text="No secrets in code."),
            Rule(id="ts-no-any", text="Avoid any.", applies_to=("**/*.ts", "**/*.tsx")),
            Rule(id="next-server-components", text="Default to RSC.",
                 applies_to=("**/*.tsx", "**/*.jsx")),
        ),
    )


# --------------------------------------------------------------------------
# Managed-block helper
# --------------------------------------------------------------------------

class TestUpsertManagedBlock:
    def test_creates_when_missing(self, tmp_path):
        p = tmp_path / "x.md"
        result = upsert_managed_block(p, "hello", "demo")
        assert result == "created"
        text = p.read_text(encoding="utf-8")
        assert begin_marker("demo") in text
        assert end_marker("demo") in text
        assert "hello" in text

    def test_idempotent_unchanged(self, tmp_path):
        p = tmp_path / "x.md"
        upsert_managed_block(p, "hello", "demo")
        result = upsert_managed_block(p, "hello", "demo")
        assert result == "unchanged"

    def test_updates_in_place_preserves_outside(self, tmp_path):
        p = tmp_path / "x.md"
        p.write_text(
            "user-prelude\n" + begin_marker("demo") + "\nold body\n" + end_marker("demo") + "\nuser-postscript\n",
            encoding="utf-8",
        )
        result = upsert_managed_block(p, "new body", "demo")
        assert result == "updated"
        text = p.read_text(encoding="utf-8")
        assert "user-prelude" in text
        assert "user-postscript" in text
        assert "new body" in text
        assert "old body" not in text

    def test_appends_when_no_markers_present(self, tmp_path):
        p = tmp_path / "x.md"
        p.write_text("# Title\n\nSome user content.\n", encoding="utf-8")
        result = upsert_managed_block(p, "managed", "demo")
        assert result == "inserted"
        text = p.read_text(encoding="utf-8")
        assert "# Title" in text
        assert "Some user content." in text
        assert begin_marker("demo") in text


# --------------------------------------------------------------------------
# Per-generator output shape
# --------------------------------------------------------------------------

class TestAgentsMdGenerator:
    def test_emits_managed_block_with_stamp(self, tmp_path, fastapi_profile):
        results = run_all(fastapi_profile, tmp_path, targets=["agents_md"])
        path = tmp_path / "AGENTS.md"
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "<!-- nexus: profile=" in text
        assert hash_profile(fastapi_profile) in text
        assert "demo-api" in text
        assert "fastapi" in text.lower()

    def test_preserves_user_content_outside_block(self, tmp_path, fastapi_profile):
        path = tmp_path / "AGENTS.md"
        path.write_text("# Existing user header\n\nUser-authored intro.\n", encoding="utf-8")
        run_all(fastapi_profile, tmp_path, targets=["agents_md"])
        text = path.read_text(encoding="utf-8")
        assert "# Existing user header" in text
        assert "User-authored intro." in text
        assert "demo-api" in text  # block was appended


class TestClaudeMdGenerator:
    def test_emits_stack_section(self, tmp_path, fastapi_profile):
        run_all(fastapi_profile, tmp_path, targets=["claude"])
        text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        assert "## Stack" in text
        assert "pytest" in text
        assert "Pydantic" in text  # rule body present

    def test_idempotent(self, tmp_path, fastapi_profile):
        run_all(fastapi_profile, tmp_path, targets=["claude"])
        before = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        results = run_all(fastapi_profile, tmp_path, targets=["claude"])
        after = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        assert before == after
        assert results[0][1] == "unchanged"


class TestCursorRulesGenerator:
    def test_core_rule_has_always_apply_true(self, tmp_path, fastapi_profile):
        run_all(fastapi_profile, tmp_path, targets=["cursor"])
        core = (tmp_path / ".cursor" / "rules" / "00-core.mdc").read_text(encoding="utf-8")
        assert core.startswith("---")
        assert "alwaysApply: true" in core
        assert "<!-- nexus: profile=" in core

    def test_framework_rule_has_globs(self, tmp_path, fastapi_profile):
        run_all(fastapi_profile, tmp_path, targets=["cursor"])
        fw = (tmp_path / ".cursor" / "rules" / "10-fastapi.mdc")
        assert fw.exists()
        text = fw.read_text(encoding="utf-8")
        assert "globs:" in text
        assert "**/*.py" in text
        assert "alwaysApply: false" in text
        assert "Pydantic" in text  # framework-scoped rule body

    def test_no_framework_rule_when_no_matching_rules(self, tmp_path):
        # Profile claims fastapi but has no python-scoped rules — no 10-fastapi.mdc file
        p = Profile(
            nexus_version=NEXUS_VERSION, tier="fast", project_name="demo",
            languages=("python",), frameworks=("fastapi",),
            rules=(Rule(id="x", text="repo-wide only"),),  # no applies_to
        )
        run_all(p, tmp_path, targets=["cursor"])
        assert (tmp_path / ".cursor" / "rules" / "00-core.mdc").exists()
        assert not (tmp_path / ".cursor" / "rules" / "10-fastapi.mdc").exists()


class TestCopilotGenerator:
    def test_repo_wide_present(self, tmp_path, nextjs_profile):
        run_all(nextjs_profile, tmp_path, targets=["copilot"])
        text = (tmp_path / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
        assert "<!-- nexus: profile=" in text
        assert "demo-web" in text

    def test_per_lang_has_apply_to(self, tmp_path, nextjs_profile):
        run_all(nextjs_profile, tmp_path, targets=["copilot"])
        path = tmp_path / ".github" / "instructions" / "typescript.instructions.md"
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "applyTo:" in text
        assert "**/*.ts" in text
        assert "Avoid any" in text or "avoid any" in text.lower()


# --------------------------------------------------------------------------
# Runner-level
# --------------------------------------------------------------------------

class TestRunAll:
    def test_dry_run_writes_nothing(self, tmp_path, fastapi_profile):
        results = run_all(fastapi_profile, tmp_path, dry_run=True)
        assert all(action == "dry-run" for _, action in results)
        # No files created
        assert not (tmp_path / "AGENTS.md").exists()
        assert not (tmp_path / "CLAUDE.md").exists()
        assert not (tmp_path / ".cursor").exists()
        assert not (tmp_path / ".github").exists()

    def test_default_targets_all(self, tmp_path, fastapi_profile):
        results = run_all(fastapi_profile, tmp_path)
        targets_seen = {f.target for f, _ in results}
        # All four targets should produce at least one file
        for t in ALL_TARGETS:
            assert t in targets_seen, f"target {t} produced no files"

    def test_unknown_target_in_list_silently_skipped(self, tmp_path, fastapi_profile):
        # run_all takes a list and looks up generators; unknown ones are skipped at the registry level.
        results = run_all(fastapi_profile, tmp_path, targets=["agents_md", "bogus"])
        targets_seen = {f.target for f, _ in results}
        assert "agents_md" in targets_seen
        assert "bogus" not in targets_seen

    def test_double_run_is_idempotent(self, tmp_path, fastapi_profile):
        first = run_all(fastapi_profile, tmp_path)
        second = run_all(fastapi_profile, tmp_path)
        non_unchanged = [(f.path, action) for f, action in second if action not in ("unchanged",)]
        assert non_unchanged == [], f"second run had non-unchanged actions: {non_unchanged}"

    def test_hash_changes_when_rule_changes(self, tmp_path, fastapi_profile):
        run_all(fastapi_profile, tmp_path)
        first_hash = hash_profile(fastapi_profile)
        agents_text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
        assert first_hash in agents_text

        # Modify rules — should produce a new hash and updated stamps
        new_profile = Profile(
            **{**fastapi_profile.__dict__, "rules": fastapi_profile.rules + (
                Rule(id="extra", text="Another rule."),
            )}
        )
        new_hash = hash_profile(new_profile)
        assert new_hash != first_hash
        run_all(new_profile, tmp_path)
        agents_text2 = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
        assert new_hash in agents_text2
        assert first_hash not in agents_text2  # stamp updated
