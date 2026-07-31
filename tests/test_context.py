"""Deterministic tests for Nexus context engineering commands."""

import pytest

from nexus.cli.tools.context import (
    CONSUMER_SURFACES,
    audit_context,
    build_map,
    manage_ignores,
    mask_observation,
    migrate_legacy_skills,
    read_mask_input,
    route_task,
)


def test_compatibility_matrix_and_effective_surfaces(tmp_path):
    (tmp_path / "AGENTS.md").write_text("canonical instructions\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("Read AGENTS.md first.\n", encoding="utf-8")
    report = audit_context(tmp_path)
    assert set(report["consumers"]) == set(CONSUMER_SURFACES)
    assert "AGENTS.md" in report["consumers"]["codex"]["files"]
    assert "AGENTS.md" in report["consumers"]["devin"]["files"]
    assert "CLAUDE.md" in report["consumers"]["claude"]["files"]
    assert "CLAUDE.md" not in report["consumers"]["vscode"]["files"]
    assert report["journal"]["initialized"] is False


def test_audit_counts_skill_metadata_not_just_in_time_body(tmp_path):
    (tmp_path / "AGENTS.md").write_text("canonical\n", encoding="utf-8")
    skill = tmp_path / ".agents" / "skills" / "large" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: large\ndescription: Loaded only when needed\n---\n\n" + ("implementation detail\n" * 1000),
        encoding="utf-8",
    )
    report = audit_context(tmp_path)
    assert report["consumers"]["codex"]["chars"] < 500


def test_inventory_map_is_bounded_and_extracts_python_symbols(tmp_path):
    (tmp_path / "app.py").write_text(
        "class Service:\n    pass\n\ndef run(value):\n    return value\n",
        encoding="utf-8",
    )
    result = build_map(tmp_path, None, "inventory", 100)
    assert result["engine"] == "inventory"
    assert "class Service" in result["content"]
    assert "run(value)" in result["content"]
    assert result["estimated_tokens"] <= 100


def test_repomix_missing_falls_back_without_download(tmp_path, monkeypatch):
    monkeypatch.setattr("nexus.cli.tools.context.shutil.which", lambda _: None)
    result = build_map(tmp_path, None, "repomix", 100)
    assert result["engine"] == "inventory"
    assert result["fallback"] == "repomix-not-installed"


def test_mask_redacts_secrets_and_keeps_failure_signature():
    result = mask_observation(
        "API_KEY=super-secret\nFAILED tests/test_auth.py::test_login\n1 failed, 2 passed",
        "test",
        1,
        200,
    )
    assert result["outcome"] == "fail"
    assert result["redactions"] == 1
    assert "super-secret" not in "\n".join(result["failure_signatures"])
    assert result["sha256"]


def test_mask_input_rejects_path_escape(tmp_path):
    with pytest.raises(ValueError, match="within project-dir"):
        read_mask_input(tmp_path, "../outside.log")


def test_ignore_apply_is_idempotent_and_keeps_lockfiles_in_scope(tmp_path):
    first = manage_ignores(tmp_path, "cursor", apply=True)
    second = manage_ignores(tmp_path, "cursor", apply=True)
    text = (tmp_path / ".cursorignore").read_text(encoding="utf-8")
    assert first["results"][0]["action"] == "created"
    assert second["results"][0]["action"] == "unchanged"
    assert "package-lock.json" not in text
    assert text.count("nexus:context-ignore:begin") == 1


def test_routes_are_provider_neutral():
    result = route_task("high-risk")
    assert result["role"] == "review-and-reasoning"
    assert result["advisory_only"] is True
    assert "model" not in result


def test_legacy_skill_migration_preview_apply_collision_and_idempotency(tmp_path):
    source = tmp_path / ".windsurf" / "skills" / "smoke" / "SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text("---\ndescription: Run smoke checks\n---\n\n# Smoke\n", encoding="utf-8")
    preview = migrate_legacy_skills(tmp_path, apply=False)
    assert preview["items"][0]["status"] == "would-create"
    assert not (tmp_path / ".agents").exists()
    applied = migrate_legacy_skills(tmp_path, apply=True)
    assert applied["created"] == 1
    target = tmp_path / ".agents" / "skills" / "smoke" / "SKILL.md"
    assert target.exists()
    repeated = migrate_legacy_skills(tmp_path, apply=True)
    assert repeated["created"] == 0
    assert repeated["collisions"] == 1


def test_workflow_conversion_adds_valid_frontmatter(tmp_path):
    source = tmp_path / ".windsurf" / "workflows" / "handoff.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Handoff\n\nDo the work.\n", encoding="utf-8")
    result = migrate_legacy_skills(tmp_path, apply=True)
    assert result["items"][0]["valid"] is True
    text = (tmp_path / ".agents" / "skills" / "handoff" / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
