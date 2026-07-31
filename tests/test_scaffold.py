"""Project-local scaffold behavior."""

from __future__ import annotations

import json

from nexus.cli.tools.scaffold import run_scaffold


def _result(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_scaffold_writes_trackable_project_local_tool(tmp_path, capsys):
    run_scaffold(
        name="release-check",
        description="Check a release",
        output_format="json",
        project_dir=str(tmp_path),
    )

    result = _result(capsys)
    tool = tmp_path / "tools" / "nexus" / "release_check.py"
    assert result["status"] == "pass"
    assert result["details"]["tool_file"] == "tools/nexus/release_check.py"
    assert tool.is_file()
    compile(tool.read_text(encoding="utf-8"), str(tool), "exec")
    assert "if __name__ == \"__main__\"" in tool.read_text(encoding="utf-8")


def test_scaffold_preserves_existing_tool(tmp_path, capsys):
    tool = tmp_path / "tools" / "nexus" / "owned.py"
    tool.parent.mkdir(parents=True)
    tool.write_text("user content\n", encoding="utf-8")

    run_scaffold("owned", output_format="json", project_dir=str(tmp_path))

    assert _result(capsys)["status"] == "fail"
    assert tool.read_text(encoding="utf-8") == "user content\n"


def test_scaffold_rejects_path_like_name(tmp_path, capsys):
    run_scaffold("../escape", output_format="json", project_dir=str(tmp_path))

    assert _result(capsys)["status"] == "fail"
    assert not (tmp_path.parent / "escape.py").exists()
