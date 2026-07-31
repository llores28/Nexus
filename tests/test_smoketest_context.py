"""Regression tests for interpreter-stable Python smoke commands."""

import sys

from nexus.cli.tools.smoketest import _detect_project, _run_step


def test_python_detection_uses_module_invocations(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="demo"\n[project.optional-dependencies]\ndev=["pytest"]\n',
        encoding="utf-8",
    )
    detected = _detect_project(tmp_path)
    assert detected["commands"]["install"].startswith("python -m pip")
    assert detected["commands"]["test"] == "python -m pytest"
    assert "lint" not in detected["commands"]


def test_run_step_resolves_python_to_active_interpreter(tmp_path):
    result = _run_step("python", "python -c \"print('ok')\"", tmp_path)
    assert result["status"] == "pass"
    assert sys.executable
