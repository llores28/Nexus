"""Truthful supply-chain coverage and scan boundaries."""

from __future__ import annotations

import json

from nexus.cli.tools.supply_chain import _find_lockfiles, _run_audit, _run_scan


def _result(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_lockfile_inventory_skips_generated_and_vendored_trees(tmp_path):
    real = tmp_path / "package-lock.json"
    real.write_text("{}", encoding="utf-8")
    for directory in ("node_modules", ".venv", "build", "dist", ".cache"):
        ignored = tmp_path / directory / "package-lock.json"
        ignored.parent.mkdir(parents=True, exist_ok=True)
        ignored.write_text("{}", encoding="utf-8")

    assert _find_lockfiles(tmp_path) == [real]


def test_python_only_audit_warns_about_unscanned_advisories(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["click==8.1.7"]\n',
        encoding="utf-8",
    )

    _run_audit(str(tmp_path), "json")

    result = _result(capsys)
    assert result["status"] == "warn"
    assert result["details"]["coverage"]["python_manifests"] == 1
    assert result["details"]["coverage"]["python_advisories"] == "not-scanned"
    assert any(
        item["issue"] == "python_advisory_coverage_unavailable"
        for item in result["details"]["hardening_recommendations"]
    )


def test_empty_scan_is_info_not_pass(tmp_path, capsys):
    _run_scan(str(tmp_path), "json")

    result = _result(capsys)
    assert result["status"] == "info"
    assert "no clean result claimed" in result["message"].lower()


def test_missing_audit_directory_fails(tmp_path, capsys):
    _run_audit(str(tmp_path / "missing"), "json")

    assert _result(capsys)["status"] == "fail"
