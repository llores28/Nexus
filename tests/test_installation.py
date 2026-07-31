"""Installation, ownership, projection, and onboarding regression tests."""

import json
from pathlib import Path

from click.testing import CliRunner

from nexus.cli.bs_cli import cli
from nexus.cli.generators import run_all
from nexus.cli.installation import (
    ALL_CONSUMERS,
    apply_generated_files,
    bundled_skill_files,
    install_skills,
    load_manifest,
    sha256_file,
    validate_skill,
)
from nexus.cli.profile import NEXUS_VERSION, Profile, Rule, save


def _profile(name: str = "demo") -> Profile:
    return Profile(
        nexus_version=NEXUS_VERSION,
        tier="fast",
        project_name=name,
        rules=(Rule(id="security", text="Do not commit secrets."),),
    )


def test_packaged_bundle_matches_repository_dogfood_copy():
    root = Path(__file__).resolve().parents[1] / ".agents" / "skills"
    dogfood = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert dogfood == bundled_skill_files()


def test_skill_validation_rejects_escaping_relative_reference(tmp_path):
    skill = tmp_path / "safe-name"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: safe-name\ndescription: Validate a skill.\n---\n\n[unsafe](../../secret.txt)\n",
        encoding="utf-8",
    )
    assert any("unsafe relative reference" in issue for issue in validate_skill(skill))


def test_skill_install_and_claude_projection_are_complete(tmp_path):
    result = install_skills(
        tmp_path,
        consumers=ALL_CONSUMERS,
        tier="fast",
    )
    assert result["actions"]
    for rel, expected in bundled_skill_files().items():
        canonical = tmp_path / ".agents" / "skills" / rel
        projection = tmp_path / ".claude" / "skills" / rel
        assert canonical.read_bytes() == expected
        assert projection.read_bytes() == expected


def test_user_modified_owned_skill_is_preserved_and_remains_tracked(tmp_path):
    install_skills(tmp_path, consumers=ALL_CONSUMERS, tier="fast")
    skill = tmp_path / ".agents" / "skills" / "research" / "SKILL.md"
    original_hash = sha256_file(skill)
    skill.write_text(skill.read_text(encoding="utf-8") + "\nUser note.\n", encoding="utf-8")

    result = install_skills(tmp_path, consumers=ALL_CONSUMERS, tier="fast")
    action = next(item for item in result["actions"] if item["path"].endswith("research/SKILL.md"))
    assert action["action"] == "preserve"
    assert "User note." in skill.read_text(encoding="utf-8")
    manifest = load_manifest(tmp_path)
    assert manifest is not None
    assert manifest["files"][".agents/skills/research/SKILL.md"]["sha256"] == original_hash


def test_user_modified_adapter_collision_is_preserved(tmp_path):
    profile = _profile()
    planned = run_all(profile, tmp_path, targets=["agents_md", "claude"], dry_run=True)
    apply_generated_files(
        tmp_path,
        (item for item, _ in planned),
        tier="fast",
        consumers=ALL_CONSUMERS,
    )
    claude = tmp_path / "CLAUDE.md"
    claude.write_text(claude.read_text(encoding="utf-8") + "\nUser override.\n", encoding="utf-8")

    changed = Profile(**{**profile.__dict__, "project_name": "changed"})
    planned = run_all(changed, tmp_path, targets=["agents_md", "claude"], dry_run=True)
    actions = apply_generated_files(
        tmp_path,
        (item for item, _ in planned),
        tier="fast",
        consumers=ALL_CONSUMERS,
    )
    claude_action = next(item for item in actions if item.path == "CLAUDE.md")
    assert claude_action.action == "preserve"
    assert "User override." in claude.read_text(encoding="utf-8")


def test_fresh_init_dry_run_writes_nothing(tmp_path):
    result = CliRunner().invoke(
        cli,
        ["init", "--project-dir", str(tmp_path), "--template", "fast", "--yes", "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert list(tmp_path.iterdir()) == []
    assert "No files were written" in result.output


def test_unattended_fresh_init_requires_explicit_tier(tmp_path):
    result = CliRunner().invoke(
        cli,
        ["init", "--project-dir", str(tmp_path), "--yes"],
    )
    assert result.exit_code != 0
    assert "requires --template" in result.output
    assert list(tmp_path.iterdir()) == []


def test_fresh_init_installs_advertised_surfaces_and_manifest(tmp_path):
    result = CliRunner().invoke(
        cli,
        ["init", "--project-dir", str(tmp_path), "--template", "fast", "--yes"],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / "CLAUDE.md").is_file()
    assert (tmp_path / ".cursorignore").is_file()
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__/" in gitignore
    assert "node_modules/" in gitignore
    assert (tmp_path / ".agents" / "skills" / "nexus-onboard" / "SKILL.md").is_file()
    assert (tmp_path / ".claude" / "skills" / "nexus-onboard" / "SKILL.md").is_file()
    manifest = json.loads((tmp_path / ".nexus" / "install-manifest.json").read_text(encoding="utf-8"))
    assert manifest["nexus_version"] == NEXUS_VERSION
    assert manifest["consumers"] == list(ALL_CONSUMERS)
    assert ".cursorignore" in manifest["files"]


def test_profile_only_project_can_upgrade(tmp_path):
    save(tmp_path, _profile(tmp_path.name))
    result = CliRunner().invoke(
        cli,
        ["init", "--project-dir", str(tmp_path), "--upgrade", "--yes"],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".nexus" / "install-manifest.json").is_file()
    assert "Reusing previously chosen tier: fast" in result.output
    assert "Upgrade plan" in result.output


def test_manifest_only_project_can_upgrade(tmp_path):
    nexus_dir = tmp_path / ".nexus"
    nexus_dir.mkdir()
    (nexus_dir / "install-manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "nexus_version": NEXUS_VERSION,
            "tier": "team",
            "consumers": list(ALL_CONSUMERS),
            "files": {},
        }),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        cli,
        ["init", "--project-dir", str(tmp_path), "--upgrade", "--yes"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads((nexus_dir / "profile.json").read_text(encoding="utf-8"))["tier"] == "team"


def test_legacy_state_project_can_upgrade(tmp_path):
    nexus_dir = tmp_path / ".nexus"
    nexus_dir.mkdir()
    (nexus_dir / "state.json").write_text(
        json.dumps({"bootstrap_tier": "enterprise"}),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        cli,
        ["init", "--project-dir", str(tmp_path), "--upgrade", "--yes"],
    )
    assert result.exit_code == 0, result.output
    assert load_manifest(tmp_path)["tier"] == "enterprise"


def test_legacy_windsurf_skill_migrates_without_modifying_source(tmp_path):
    legacy = tmp_path / ".windsurf" / "skills" / "legacy-helper" / "SKILL.md"
    legacy.parent.mkdir(parents=True)
    source = "---\nname: legacy-helper\ndescription: Legacy helper workflow.\n---\n\n# Legacy helper\n"
    legacy.write_text(source, encoding="utf-8")
    result = CliRunner().invoke(
        cli,
        [
            "init", "--project-dir", str(tmp_path), "--upgrade", "--template", "fast",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert legacy.read_text(encoding="utf-8") == source
    canonical = tmp_path / ".agents" / "skills" / "legacy-helper" / "SKILL.md"
    projection = tmp_path / ".claude" / "skills" / "legacy-helper" / "SKILL.md"
    assert canonical.read_bytes() == projection.read_bytes()
