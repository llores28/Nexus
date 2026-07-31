"""Unit tests for nexus.cli.security.

Covers the security framework primitives that previously had zero coverage:
path validation (broken-import regression), is_template_file (substring-trap
regression), placeholder-aware secret scanning, and audit-log rotation.
"""

from pathlib import Path

import pytest

from nexus.cli.security import (
    _rotate_log_if_needed,
    audit_log,
    gitignored_files,
    is_template_file,
    sanitize_output,
    scan_text_for_secrets,
    validate_package_name,
    validate_path,
    validate_url,
)


# --------------------------------------------------------------------------
# validate_path
# --------------------------------------------------------------------------

class TestValidatePath:
    def test_resolves_within_root(self, tmp_path):
        target = validate_path("subdir/file.txt", tmp_path)
        assert str(target).startswith(str(tmp_path.resolve()))

    def test_blocks_traversal(self, tmp_path):
        with pytest.raises(ValueError, match="traversal"):
            validate_path("../../etc/passwd", tmp_path)

    def test_blocks_same_prefix_sibling(self, tmp_path):
        project = tmp_path / "repo"
        sibling = tmp_path / "repo-escape"
        project.mkdir()
        sibling.mkdir()

        with pytest.raises(ValueError, match="traversal"):
            validate_path(str(sibling), project)

    def test_default_project_root_uses_nexus_utils(self, tmp_path, monkeypatch):
        # Regression: security.py used to `from bootstrap.cli.utils import find_project_root`,
        # a leftover from the bootstrap → nexus rename. validate_path() called without an
        # explicit project_root would crash on import. This test covers the fixed path.
        monkeypatch.chdir(tmp_path)
        # Should not raise — the import path now resolves correctly.
        target = validate_path("file.txt")
        assert isinstance(target, Path)


# --------------------------------------------------------------------------
# is_template_file — the substring-trap regression
# --------------------------------------------------------------------------

class TestIsTemplateFile:
    @pytest.mark.parametrize("name", [
        ".env.example",
        ".env.template",
        ".env.sample",
        "config.dist",
        "settings.tmpl",
        ".env.template.json",  # suffix-followed-by-extension
        ".env.SAMPLE",         # case-insensitive
    ])
    def test_recognizes_templates(self, tmp_path, name):
        assert is_template_file(tmp_path / name) is True

    @pytest.mark.parametrize("name", [
        "redistribute.json",   # contains 'dist' but is not a template
        "samplefoo.json",      # contains 'sample' as substring only
        "templatehouse.txt",   # contains 'template' as substring only
        "myexample.py",        # contains 'example' as substring only
        ".env",                # plain config (real secrets)
        "config.json",         # ordinary file
    ])
    def test_rejects_substring_only_matches(self, tmp_path, name):
        # Regression: prior implementation did `s in name` which falsely matched
        # all of these. The new endswith / segment-followed-by-extension logic
        # rejects them as not templates.
        assert is_template_file(tmp_path / name) is False


# --------------------------------------------------------------------------
# scan_text_for_secrets — placeholder filter
# --------------------------------------------------------------------------

class TestScanTextForSecrets:
    def test_flags_real_secret(self):
        # OpenAI sk- keys (strict pattern) are flagged regardless of placeholder filter.
        findings = scan_text_for_secrets("OPENAI_KEY=sk-abc123abc123abc123abc123")
        assert len(findings) >= 1

    def test_skips_env_passthrough(self):
        # Loose `name=value` patterns get the placeholder filter.
        findings = scan_text_for_secrets("API_KEY=${OPENAI_KEY}")
        assert findings == []

    def test_skips_template_placeholders(self):
        cases = [
            "API_KEY=<your-key>",
            "PASSWORD=changeme",
            "SECRET=your_secret_here",
            "TOKEN=...",
            "SECRET=xxx",
        ]
        for line in cases:
            findings = scan_text_for_secrets(line)
            assert findings == [], f"unexpected finding for placeholder: {line!r}"

    def test_aws_key_always_flagged(self):
        # Strict pattern (literal AWS key); placeholder filter does not apply.
        findings = scan_text_for_secrets("AKIAIOSFODNN7EXAMPLE")
        assert len(findings) >= 1


# --------------------------------------------------------------------------
# validate_url
# --------------------------------------------------------------------------

class TestValidateUrl:
    def test_https_passes(self):
        assert validate_url("https://example.com/path") == "https://example.com/path"

    def test_blocks_file_scheme(self):
        with pytest.raises(ValueError, match="scheme"):
            validate_url("file:///etc/passwd")

    def test_blocks_data_scheme(self):
        with pytest.raises(ValueError, match="scheme"):
            validate_url("data:text/html,<script>alert(1)</script>")

    def test_blocks_private_ip(self):
        with pytest.raises(ValueError, match="private/internal"):
            validate_url("http://127.0.0.1/")

    def test_allows_private_when_opted_in(self):
        # allow_private should bypass the SSRF check (used by local-env tools).
        assert validate_url("http://127.0.0.1/", allow_private=True) == "http://127.0.0.1/"


# --------------------------------------------------------------------------
# validate_package_name
# --------------------------------------------------------------------------

class TestValidatePackageName:
    @pytest.mark.parametrize("name", ["axios", "@scope/pkg", "django.contrib.auth", "my-package_v2"])
    def test_accepts_valid(self, name):
        assert validate_package_name(name) == name

    @pytest.mark.parametrize("name", [
        "pkg; rm -rf /",
        "pkg && evil",
        "$(whoami)",
        "`id`",
        "a" * 215,  # exceeds 214-char npm limit
    ])
    def test_rejects_invalid(self, name):
        with pytest.raises(ValueError):
            validate_package_name(name)


# --------------------------------------------------------------------------
# sanitize_output
# --------------------------------------------------------------------------

class TestSanitizeOutput:
    def test_redacts_secret_in_log_line(self):
        out = sanitize_output("api_key=sk-abc123abc123abc123abc123 some other text")
        assert "sk-abc123" not in out
        assert "[REDACTED]" in out

    def test_passthrough_clean_text(self):
        clean = "ordinary log message with no secrets"
        assert sanitize_output(clean) == clean


# --------------------------------------------------------------------------
# Audit log rotation
# --------------------------------------------------------------------------

class TestAuditLogRotation:
    def test_rotate_below_threshold_is_noop(self, tmp_path):
        log = tmp_path / "audit.jsonl"
        log.write_text("small entry\n", encoding="utf-8")
        _rotate_log_if_needed(log, max_bytes=1024)
        assert log.exists()
        assert not (tmp_path / "audit.jsonl.1").exists()

    def test_rotate_over_threshold_moves_to_backup(self, tmp_path):
        log = tmp_path / "audit.jsonl"
        log.write_text("x" * 2048, encoding="utf-8")
        _rotate_log_if_needed(log, max_bytes=1024)
        backup = tmp_path / "audit.jsonl.1"
        assert backup.exists()
        assert not log.exists()
        assert backup.read_text(encoding="utf-8") == "x" * 2048

    def test_rotate_replaces_existing_backup(self, tmp_path):
        log = tmp_path / "audit.jsonl"
        log.write_text("new", encoding="utf-8")
        backup = tmp_path / "audit.jsonl.1"
        backup.write_text("old", encoding="utf-8")
        # Force log over threshold
        log.write_text("x" * 2048, encoding="utf-8")
        _rotate_log_if_needed(log, max_bytes=1024)
        assert backup.read_text(encoding="utf-8") == "x" * 2048

    def test_audit_log_writes_entry(self, tmp_path):
        audit_log("test-tool", {"arg": "value"}, exit_code=0, duration_ms=10, project_root=tmp_path)
        path = tmp_path / ".cache" / "bs-cli" / "audit.jsonl"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "test-tool" in content
        assert '"exit_code": 0' in content


# --------------------------------------------------------------------------
# gitignored_files (smoke; full coverage requires real git)
# --------------------------------------------------------------------------

class TestGitignoredFiles:
    def test_no_git_returns_empty_set(self, tmp_path):
        # Without a git repo, check-ignore exits non-zero; we should get an empty set.
        result = gitignored_files(tmp_path, [tmp_path / "anything.txt"])
        assert result == set()

    def test_empty_paths_returns_empty_set(self, tmp_path):
        assert gitignored_files(tmp_path, []) == set()
