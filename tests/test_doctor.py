"""Tests for nexus.cli.tools.doctor.

Covers drift detection (hand-edit a generated file -> doctor flags it),
version mismatch, missing-file diagnosis, and the ``--deep`` stack diff.
"""

import json
from pathlib import Path

import pytest

from nexus.cli.generators import run_all
from nexus.cli.installation import ALL_CONSUMERS, install_skills, record_managed_files
from nexus.cli.profile import (
    NEXUS_VERSION,
    Profile,
    Rule,
    hash_profile,
    save,
)
from nexus.cli.tools.doctor import _check_file, _read_stamp_hash, diagnose, run_doctor


@pytest.fixture
def seeded_project(tmp_path):
    """A project with a profile + freshly generated files."""
    profile = Profile(
        nexus_version=NEXUS_VERSION,
        tier="fast",
        project_name="demo",
        languages=("python",),
        frameworks=("fastapi",),
        rules=(
            Rule(id="no-secrets", text="No secrets."),
            Rule(id="py-x", text="Py rule.", applies_to=("**/*.py",)),
            Rule(id="fastapi-x", text="FastAPI rule.", applies_to=("**/*.py",)),
        ),
    )
    save(tmp_path, profile)
    generated = run_all(profile, tmp_path)
    install_skills(tmp_path, consumers=ALL_CONSUMERS, tier=profile.tier)
    record_managed_files(tmp_path, (item.path for item, _ in generated))
    return tmp_path, profile


# --------------------------------------------------------------------------
# Stamp parsing helpers
# --------------------------------------------------------------------------

class TestReadStampHash:
    def test_returns_hash_from_stamped_file(self, tmp_path):
        f = tmp_path / "x.md"
        f.write_text("<!-- nexus: profile=abc123def456 generator=x nexus_version=0.2.0 -->\nbody\n", encoding="utf-8")
        assert _read_stamp_hash(f) == "abc123def456"

    def test_returns_none_when_unstamped(self, tmp_path):
        f = tmp_path / "x.md"
        f.write_text("just user content\n", encoding="utf-8")
        assert _read_stamp_hash(f) is None

    def test_returns_none_on_oserror(self, tmp_path):
        assert _read_stamp_hash(tmp_path / "does-not-exist") is None


class TestCheckFile:
    def test_ok_when_hashes_match(self, tmp_path):
        f = tmp_path / "x.md"
        f.write_text("<!-- nexus: profile=abc123def456 generator=x nexus_version=0.2.0 -->\n", encoding="utf-8")
        st, _ = _check_file(f, "abc123def456")
        assert st == "ok"

    def test_drift_when_hashes_differ(self, tmp_path):
        f = tmp_path / "x.md"
        f.write_text("<!-- nexus: profile=oldhash00000 generator=x nexus_version=0.2.0 -->\n", encoding="utf-8")
        st, _ = _check_file(f, "newhash00000")
        assert st == "drift"

    def test_missing_when_file_absent(self, tmp_path):
        st, _ = _check_file(tmp_path / "missing.md", "anyhash00000")
        assert st == "missing"

    def test_unstamped_when_file_has_no_stamp(self, tmp_path):
        f = tmp_path / "x.md"
        f.write_text("plain user content\n", encoding="utf-8")
        st, _ = _check_file(f, "anyhash00000")
        assert st == "unstamped"


# --------------------------------------------------------------------------
# run_doctor — end-to-end drift detection
# --------------------------------------------------------------------------

class TestRunDoctor:
    def test_vscode_host_checks_canonical_surfaces_without_new_adapter(self, seeded_project):
        pd, _ = seeded_project
        result = diagnose(pd, deep=False, consumer="vscode")
        assert not any(item["check"].startswith("adapter:claude") for item in result["items"])
        assert next(item for item in result["items"] if item["check"] == "canonical-skills")["status"] == "ok"

    def test_devin_review_audits_combined_instruction_duplicates(self, seeded_project):
        pd, _ = seeded_project
        duplicate = "Flag any authorization change that lacks a focused regression test."
        claude = pd / "CLAUDE.md"
        cursor = pd / ".cursor" / "rules" / "00-core.mdc"
        claude.write_text(claude.read_text(encoding="utf-8") + duplicate + "\n", encoding="utf-8")
        cursor.write_text(cursor.read_text(encoding="utf-8") + duplicate + "\n", encoding="utf-8")
        result = diagnose(pd, deep=False, consumer="devin-review")
        check = next(item for item in result["items"] if item["check"] == "devin-review-duplication")
        assert check["status"] == "fail"

    def test_clean_project_no_drift(self, seeded_project, capsys):
        pd, _ = seeded_project
        # Should not raise
        run_doctor(output_format="json", project_dir=str(pd), deep=False)
        out = capsys.readouterr().out
        data = json.loads(out)
        # Drift / missing-file checks all ok (the journal-health check may warn
        # in a bare fixture project — that's a separate signal)
        assert data["details"]["drift_count"] == 0
        assert data["details"]["missing_count"] == 0
        adapter_items = [it for it in data["items"] if it["check"].startswith("adapter:")]
        assert adapter_items
        assert all(it["status"] == "ok" for it in adapter_items)
        assert next(it for it in data["items"] if it["check"] == "canonical-skills")["status"] == "ok"

    def test_hand_edit_inside_managed_block_flags_drift(self, seeded_project, capsys):
        pd, _ = seeded_project
        # Corrupt the stamp on AGENTS.md to simulate a hand-edit (or stale stamp)
        agents = pd / "AGENTS.md"
        text = agents.read_text(encoding="utf-8")
        text = text.replace("<!-- nexus: profile=", "<!-- nexus: profile=ZZZZZZZZZZZZ x=", 1)
        # That broke the format slightly; rewrite cleanly with a wrong hash:
        agents.write_text(
            text.replace("ZZZZZZZZZZZZ x=", "deadbeefdead "),
            encoding="utf-8",
        )
        run_doctor(output_format="json", project_dir=str(pd), deep=False)
        data = json.loads(capsys.readouterr().out)
        assert data["status"] == "fail"
        assert data["details"]["drift_count"] >= 1

    def test_missing_generated_file_flags_warn(self, seeded_project, capsys):
        pd, _ = seeded_project
        (pd / "CLAUDE.md").unlink()
        run_doctor(output_format="json", project_dir=str(pd), deep=False)
        data = json.loads(capsys.readouterr().out)
        assert data["status"] == "fail"
        assert data["details"]["missing_count"] >= 1

    def test_no_profile_reports_failure(self, tmp_path, capsys):
        result = run_doctor(output_format="json", project_dir=str(tmp_path), deep=False)
        data = json.loads(capsys.readouterr().out)
        assert result["status"] == "fail"
        assert data["status"] == "fail"
        assert any(item["check"] == "profile-present" for item in data["items"])

    def test_version_mismatch_warns(self, tmp_path, capsys):
        # Save a profile with an old version
        profile = Profile(
            nexus_version="0.0.0-old",
            tier="fast",
            project_name="demo",
            rules=(Rule(id="x", text="x"),),
        )
        save(tmp_path, profile)
        # Generate files with the actual current version (mismatched stamp)
        generated = run_all(profile, tmp_path)
        install_skills(tmp_path, consumers=ALL_CONSUMERS, tier=profile.tier)
        record_managed_files(tmp_path, (item.path for item, _ in generated))
        run_doctor(output_format="json", project_dir=str(tmp_path), deep=False)
        data = json.loads(capsys.readouterr().out)
        assert data["status"] == "warn"
        version_check = next(it for it in data["items"] if it["check"] == "version-match")
        assert version_check["status"] == "warn"

    def test_regenerate_clears_drift(self, seeded_project, capsys):
        pd, profile = seeded_project
        # Simulate drift by corrupting stamp
        agents = pd / "AGENTS.md"
        agents.write_text(
            agents.read_text(encoding="utf-8").replace(
                hash_profile(profile), "deadbeefdead"
            ),
            encoding="utf-8",
        )
        # Re-run generators -> stamp restored
        run_all(profile, pd)
        run_doctor(output_format="json", project_dir=str(pd), deep=False)
        data = json.loads(capsys.readouterr().out)
        assert data["details"]["drift_count"] == 0
        assert data["details"]["missing_count"] == 0
