"""Regression tests for interpreter-stable Python smoke commands."""

import sys

from nexus.cli.tools.smoketest import _detect_project, _project_python, _run_step, run_smoketest


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


def test_dependency_check_skips_unrelated_global_interpreter(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="demo"\nversion="1.0"\n', encoding="utf-8"
    )

    assert _project_python(tmp_path) is None
    result = run_smoketest(output_format="json", project_dir=str(tmp_path))
    capsys.readouterr()

    dependency = next(step for step in result["steps"] if step["step"] == "deps-verify")
    assert dependency["status"] == "skip"
    assert "project-local .venv" in dependency["message"]
