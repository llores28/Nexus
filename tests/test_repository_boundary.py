"""Repository, manifest, and wheel-source boundary invariants."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from nexus.cli.installation import bundled_skill_files


ROOT = Path(__file__).resolve().parents[1]


def _tracked() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return set(result.stdout.splitlines())


def test_manifest_owned_files_are_present_in_clean_clone_sources():
    manifest = json.loads((ROOT / ".nexus" / "install-manifest.json").read_text(encoding="utf-8"))
    tracked = _tracked()

    assert set(manifest["files"]) <= tracked
    assert ".cursor/rules/00-core.mdc" in tracked


def test_managed_provider_surfaces_are_not_ignored():
    manifest = json.loads((ROOT / ".nexus" / "install-manifest.json").read_text(encoding="utf-8"))
    candidates = [
        *manifest["files"],
        ".cursor/rules/10-fastapi.mdc",
        ".github/instructions/python.instructions.md",
    ]

    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin", "-z"],
        cwd=ROOT,
        input="\0".join(candidates) + "\0",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout


def test_legacy_and_runtime_artifacts_are_not_tracked():
    tracked = _tracked()
    forbidden_prefixes = (
        ".windsurf/", ".cache/", "build/", "dist/", ".pytest_cache/", ".ruff_cache/"
    )

    assert ".codeiumignore" not in tracked
    assert not [path for path in tracked if path.startswith(forbidden_prefixes)]
    assert not [
        path for path in tracked
        if path.startswith(".nexus/")
        and path not in {".nexus/profile.json", ".nexus/install-manifest.json"}
    ]


def test_wheel_package_data_uses_an_explicit_runtime_allowlist():
    config = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    setuptools = re.search(
        r"\[tool\.setuptools\]\s*(.*?)(?=\n\[|\Z)", config, flags=re.DOTALL
    )
    package_section = re.search(
        r"\[tool\.setuptools\.package-data\]\s*(.*?)(?=\n\[|\Z)",
        config,
        flags=re.DOTALL,
    )

    assert setuptools and re.search(
        r"^include-package-data\s*=\s*false$", setuptools.group(1), re.MULTILINE
    )
    assert package_section
    package_data = re.findall(r'"([^"]+)"', package_section.group(1))
    assert "*.md" not in package_data
    assert "*.html" not in package_data
    assert {
        "1Fast-Bootstrap.md",
        "2Team-Bootstrap.md",
        "3Enterprise-Bootstrap.md",
        "Universal-Bootstrap.md",
    } <= set(package_data)


def test_bootstrap_prd_resources_ship_inside_the_skill():
    bundle = bundled_skill_files()

    assert "bootstrap-prd/references/PROJECT-INTAKE.md" in bundle
    assert "bootstrap-prd/assets/PRD-TEMPLATE.md" in bundle


def test_ci_actions_are_sha_pinned_with_read_only_permissions():
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")

    assert re.search(r"permissions:\s*\n\s+contents: read", workflow)
    action_refs = re.findall(r"uses:\s+[^@\s]+@([^\s#]+)", workflow)
    assert action_refs
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs)


def test_setup_scripts_recognize_legacy_upgrades_without_editable_installs():
    powershell = (ROOT / "setup.ps1").read_text(encoding="utf-8")
    shell = (ROOT / "setup.sh").read_text(encoding="utf-8")

    for script in (powershell, shell):
        assert ".windsurf" in script
        assert "nexus:agents-md:begin" in script
        assert "pip install --quiet -e" not in script

    assert "Push-Location -LiteralPath $ProjectDir" in powershell
    assert 'cd "$PROJECT_DIR"' in shell
