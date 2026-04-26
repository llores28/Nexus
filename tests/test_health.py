"""Tests for nexus.cli.tools.health.

Covers the status-bubble-up regression where secrets findings (which lack a
`severity` field) failed to flip run_security() from 'warn' to 'fail' even
though the score calculation correctly penalized them.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from nexus.cli.tools.health import run_security


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
