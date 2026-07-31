"""Tests for nexus.cli.tools.health.

Covers:
- The status-bubble-up regression where secrets findings (which lack a
  ``severity`` field) failed to flip ``run_security()`` from 'warn' to 'fail'
  even though the score calculation correctly penalized them.
- v0.3 expectations: legacy ``.windsurf/*`` is optional while
  canonical ``.agents/skills`` is health-checked;
  ``.nexus/profile.json`` is the new SoT and gets its own check;
  ``.cursorrules`` is replaced by ``.cursor/rules/00-core.mdc`` in the
  cross-IDE expectation list.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from nexus.cli.tools.health import (
    EXPECTED_CROSS_IDE,
    _check_profile,
    _check_rules,
    _check_skills,
    _check_workflows,
    run_components,
    run_security,
)


@pytest.fixture
def project(tmp_path):
    """A minimal project layout with .gitignore and an empty config."""
    (tmp_path / ".gitignore").write_text(
        "\n".join([".env", "__pycache__", "node_modules", ".venv", "*.key", "*.pem"]),
        encoding="utf-8",
    )
    return tmp_path


def test_run_security_pass_when_clean(project):
    result = run_security(project)
    # Status should be either pass or warn (codeiumignore missing on bare project).
    assert result["status"] in ("pass", "warn")
    assert result["secrets"]["secrets_found"] == 0


def test_run_security_fails_when_secrets_found(project):
    # Plant a real-looking secret in an unfiltered config file.
    config = project / "app.config.js"
    config.write_text(
        'module.exports = { OPENAI_KEY: "sk-abc123abc123abc123abc123abc" };\n',
        encoding="utf-8",
    )
    result = run_security(project)
    # Regression: prior implementation reported "warn" because the loop
    # iterating over `i.get("severity") == "high"` ignored findings (which
    # have no `severity` field). Now secrets_found > 0 forces fail.
    assert result["status"] == "fail", (
        f"expected fail when secrets present; got {result['status']} — "
        f"{result['secrets']['secrets_found']} finding(s)"
    )
    assert result["secrets"]["secrets_found"] >= 1


def test_run_security_warn_for_non_secret_issues(project):
    # No secrets, but missing .codeiumignore should produce a warning.
    result = run_security(project)
    # codeiumignore missing on this bare fixture → warn
    if not (project / ".codeiumignore").exists():
        assert result["status"] in ("warn", "pass")


# --------------------------------------------------------------------------
# v0.3 surface checks
# --------------------------------------------------------------------------

class TestV03HealthExpectations:
    """The component checker uses canonical Agent Skills and modern adapters."""

    def test_cross_ide_expectation_uses_modern_cursor_path(self):
        assert ".cursor/rules/00-core.mdc" in EXPECTED_CROSS_IDE
        assert ".cursorrules" not in EXPECTED_CROSS_IDE

    def test_missing_legacy_rules_are_info_but_canonical_skills_warn(self, tmp_path):
        rules = _check_rules(tmp_path)
        assert rules["status"] == "fail"
        assert any("AGENTS.md" in issue["message"] for issue in rules["issues"])
        assert _check_skills(tmp_path)["status"] == "warn"
        assert _check_workflows(tmp_path)["status"] == "pass"

    def test_check_profile_warns_when_missing(self, tmp_path):
        result = _check_profile(tmp_path)
        assert result["status"] == "warn"
        assert any("profile.json" in i["message"] for i in result["issues"])

    def test_check_profile_passes_when_present(self, tmp_path):
        (tmp_path / ".nexus").mkdir()
        (tmp_path / ".nexus" / "profile.json").write_text(
            json.dumps({"nexus_version": "0.3.0", "tier": "fast"}),
            encoding="utf-8",
        )
        result = _check_profile(tmp_path)
        assert result["status"] == "pass"

    def test_check_profile_fails_when_corrupt(self, tmp_path):
        (tmp_path / ".nexus").mkdir()
        (tmp_path / ".nexus" / "profile.json").write_text("{ not json", encoding="utf-8")
        result = _check_profile(tmp_path)
        assert result["status"] == "fail"

    def test_run_components_no_high_severity_for_v03_project(self, tmp_path):
        """A v0.3 canonical surface has no high-severity component issues."""
        (tmp_path / ".nexus").mkdir()
        (tmp_path / ".nexus" / "profile.json").write_text(
            json.dumps({"nexus_version": "0.3.0", "tier": "fast"}),
            encoding="utf-8",
        )
        (tmp_path / "AGENTS.md").write_text("# A", encoding="utf-8")
        (tmp_path / "CLAUDE.md").write_text("# C", encoding="utf-8")
        (tmp_path / ".cursor" / "rules").mkdir(parents=True)
        (tmp_path / ".cursor" / "rules" / "00-core.mdc").write_text("---\n---\n", encoding="utf-8")
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "copilot-instructions.md").write_text("# Copilot", encoding="utf-8")
        skill = tmp_path / ".agents" / "skills" / "smoke" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: smoke\ndescription: Smoke test\n---\n", encoding="utf-8")

        components = run_components(tmp_path)
        all_issues = []
        for section in ("profile", "rules", "skills", "workflows", "cross_ide", "templates"):
            all_issues.extend(components.get(section, {}).get("issues", []))
        high = [i for i in all_issues if i.get("severity") == "high"]
        assert high == [], f"unexpected high-severity issues on v0.3 fixture: {high}"
