"""Tests for nexus.cli.profile and profile_seeds.

Covers:
- Round-trip serialization (save -> load preserves the profile).
- Hash determinism and sensitivity (same profile -> same hash; different
  rule -> different hash).
- ``from_detection`` against fixture projects per stack (python+fastapi,
  node+nextjs, go).
- Seed-rule composition (tier escalation adds rules; lang/framework rules
  appear when stack matches; no duplicates).
"""

import json
from pathlib import Path

import pytest

from nexus.cli.profile import (
    NEXUS_VERSION,
    Profile,
    PROFILE_REL,
    Rule,
    from_detection,
    hash_profile,
    load,
    save,
    select_rules,
)
from nexus.cli.profile_seeds import (
    CORE_RULES,
    compose_rules,
    PYTHON_RULES,
    NEXTJS_RULES,
    FASTAPI_RULES,
    TIER_RULES_TEAM,
    TIER_RULES_ENTERPRISE,
)


def _bare_profile(**overrides) -> Profile:
    base = dict(
        nexus_version=NEXUS_VERSION,
        tier="fast",
        project_name="demo",
    )
    base.update(overrides)
    return Profile(**base)


# --------------------------------------------------------------------------
# Serialization round-trip
# --------------------------------------------------------------------------

class TestSerialization:
    def test_round_trip_minimal(self, tmp_path):
        p = _bare_profile()
        save(tmp_path, p)
        loaded = load(tmp_path)
        assert loaded is not None
        assert loaded.tier == p.tier
        assert loaded.project_name == p.project_name
        assert loaded.nexus_version == p.nexus_version

    def test_round_trip_full(self, tmp_path):
        p = _bare_profile(
            tier="enterprise",
            languages=("python", "typescript"),
            frameworks=("fastapi", "nextjs"),
            package_managers=("pip", "pnpm"),
            test_runner="pytest",
            ci="github-actions",
            deployment="docker",
            rules=(
                Rule(id="x", text="X rule", applies_to=("**/*.py",)),
                Rule(id="y", text="Y rule", targets=("cursor", "copilot")),
            ),
            extras={"custom": [1, 2, 3]},
        )
        save(tmp_path, p)
        loaded = load(tmp_path)
        assert loaded is not None
        assert loaded.languages == ("python", "typescript")
        assert loaded.frameworks == ("fastapi", "nextjs")
        assert loaded.deployment == "docker"
        assert len(loaded.rules) == 2
        # Rule fields preserved exactly
        assert loaded.rules[0].applies_to == ("**/*.py",)
        assert loaded.rules[1].targets == ("cursor", "copilot")
        assert loaded.extras == {"custom": [1, 2, 3]}

    def test_load_returns_none_when_missing(self, tmp_path):
        assert load(tmp_path) is None

    def test_load_returns_none_when_corrupt(self, tmp_path):
        path = tmp_path / PROFILE_REL
        path.parent.mkdir(parents=True)
        path.write_text("{ not json", encoding="utf-8")
        assert load(tmp_path) is None

    def test_save_creates_parent_dir(self, tmp_path):
        p = _bare_profile()
        save(tmp_path, p)
        assert (tmp_path / PROFILE_REL).exists()


# --------------------------------------------------------------------------
# Hashing
# --------------------------------------------------------------------------

class TestHashing:
    def test_hash_is_12_chars_hex(self):
        h = hash_profile(_bare_profile())
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_deterministic(self):
        a = _bare_profile(languages=("python",), rules=(Rule(id="x", text="x"),))
        b = _bare_profile(languages=("python",), rules=(Rule(id="x", text="x"),))
        assert hash_profile(a) == hash_profile(b)

    def test_hash_changes_with_rule_text(self):
        a = _bare_profile(rules=(Rule(id="x", text="A"),))
        b = _bare_profile(rules=(Rule(id="x", text="B"),))
        assert hash_profile(a) != hash_profile(b)

    def test_hash_changes_with_tier(self):
        assert hash_profile(_bare_profile(tier="fast")) != hash_profile(_bare_profile(tier="team"))


# --------------------------------------------------------------------------
# from_detection
# --------------------------------------------------------------------------

class TestFromDetection:
    def test_python_fastapi_project(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = ["fastapi", "pytest"]\n',
            encoding="utf-8",
        )
        p = from_detection(tmp_path, tier="team")
        assert "python" in p.languages
        assert "fastapi" in p.frameworks
        assert p.test_runner == "pytest"
        assert p.tier == "team"
        # Seed rules: core + team-tier + python + fastapi
        rule_ids = {r.id for r in p.rules}
        assert "no-secrets" in rule_ids                # core
        assert "tests-required" in rule_ids            # team
        assert "py-no-shell-true" in rule_ids          # python
        assert "fastapi-pydantic" in rule_ids          # fastapi

    def test_node_nextjs_project(self, tmp_path):
        (tmp_path / "package.json").write_text(
            json.dumps({
                "name": "demo",
                "dependencies": {"next": "14"},
                "scripts": {"test": "vitest"},
            }),
            encoding="utf-8",
        )
        (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
        (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
        p = from_detection(tmp_path, tier="fast")
        assert "typescript" in p.languages
        assert "nextjs" in p.frameworks
        assert "pnpm" in p.package_managers
        assert p.test_runner == "vitest"
        rule_ids = {r.id for r in p.rules}
        assert "ts-no-any" in rule_ids
        assert "next-server-components" in rule_ids
        # No team-tier rules at fast tier
        assert "tests-required" not in rule_ids

    def test_go_project_with_dockerfile(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/x\n", encoding="utf-8")
        (tmp_path / "Dockerfile").write_text("FROM golang:1.21\n", encoding="utf-8")
        p = from_detection(tmp_path, tier="fast")
        assert "go" in p.languages
        assert p.deployment == "docker"
        rule_ids = {r.id for r in p.rules}
        assert "go-error-wrap" in rule_ids

    def test_unknown_project_still_returns_core_rules(self, tmp_path):
        p = from_detection(tmp_path, tier="fast")
        assert p.tier == "fast"
        assert p.languages == ()
        assert p.frameworks == ()
        rule_ids = {r.id for r in p.rules}
        # Core rules always present
        for r in CORE_RULES:
            assert r.id in rule_ids

    def test_ci_detection_github_actions(self, tmp_path):
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        (tmp_path / ".github" / "workflows" / "ci.yml").write_text("on: push\n", encoding="utf-8")
        p = from_detection(tmp_path)
        assert p.ci == "github-actions"

    def test_deployment_vercel_beats_docker(self, tmp_path):
        (tmp_path / "vercel.json").write_text("{}", encoding="utf-8")
        (tmp_path / "Dockerfile").write_text("FROM node\n", encoding="utf-8")
        (tmp_path / "package.json").write_text('{"name":"x"}', encoding="utf-8")
        p = from_detection(tmp_path)
        # Vercel signal should win when both present (more specific)
        assert p.deployment == "vercel"


# --------------------------------------------------------------------------
# Seed rule composition
# --------------------------------------------------------------------------

class TestComposeRules:
    def test_fast_tier_only_core(self):
        rules = compose_rules(tier="fast", languages=(), frameworks=())
        ids = {r.id for r in rules}
        for r in CORE_RULES:
            assert r.id in ids
        for r in TIER_RULES_TEAM:
            assert r.id not in ids
        for r in TIER_RULES_ENTERPRISE:
            assert r.id not in ids

    def test_team_adds_team_rules(self):
        rules = compose_rules(tier="team", languages=(), frameworks=())
        ids = {r.id for r in rules}
        for r in TIER_RULES_TEAM:
            assert r.id in ids
        for r in TIER_RULES_ENTERPRISE:
            assert r.id not in ids

    def test_enterprise_adds_both_tier_groups(self):
        rules = compose_rules(tier="enterprise", languages=(), frameworks=())
        ids = {r.id for r in rules}
        for r in TIER_RULES_TEAM:
            assert r.id in ids
        for r in TIER_RULES_ENTERPRISE:
            assert r.id in ids

    def test_python_lang_rules_added(self):
        rules = compose_rules(tier="fast", languages=("python",), frameworks=())
        ids = {r.id for r in rules}
        for r in PYTHON_RULES:
            assert r.id in ids

    def test_fastapi_framework_rules_added(self):
        rules = compose_rules(tier="fast", languages=("python",), frameworks=("fastapi",))
        ids = {r.id for r in rules}
        for r in FASTAPI_RULES:
            assert r.id in ids

    def test_no_duplicate_ids(self):
        rules = compose_rules(
            tier="enterprise",
            languages=("python", "typescript"),
            frameworks=("fastapi", "nextjs"),
        )
        ids = [r.id for r in rules]
        assert len(ids) == len(set(ids)), f"duplicates in: {ids}"


# --------------------------------------------------------------------------
# select_rules — the per-target / per-tier filter
# --------------------------------------------------------------------------

class TestSelectRules:
    def test_tier_min_excludes_higher(self):
        p = _bare_profile(
            tier="fast",
            rules=(
                Rule(id="a", text="a"),                      # tier_min default fast
                Rule(id="b", text="b", tier_min="team"),
                Rule(id="c", text="c", tier_min="enterprise"),
            ),
        )
        ids = {r.id for r in select_rules(p, target="cursor")}
        assert ids == {"a"}

    def test_target_filter(self):
        p = _bare_profile(
            tier="fast",
            rules=(
                Rule(id="a", text="a", targets=("cursor",)),
                Rule(id="b", text="b", targets=("copilot",)),
                Rule(id="c", text="c"),  # targets=None -> all
            ),
        )
        cursor_ids = {r.id for r in select_rules(p, target="cursor")}
        copilot_ids = {r.id for r in select_rules(p, target="copilot")}
        assert cursor_ids == {"a", "c"}
        assert copilot_ids == {"b", "c"}

    def test_user_rules_preserved_across_detect(self, tmp_path):
        """Regression: `nexus profile detect` used to clobber user-added rules.

        With Rule.nexus_managed defaulting to False on round-trip, ``from_detection``
        merges seed rules with any unmanaged rules from an existing profile.
        """
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = ["fastapi"]\n',
            encoding="utf-8",
        )
        # Initial detect
        p1 = from_detection(tmp_path, tier="fast")
        save(tmp_path, p1)
        # Sanity: every seed rule is marked managed
        assert all(r.nexus_managed for r in p1.rules)

        # User adds a custom rule
        custom = Rule(id="my-pathlib-rule", text="Prefer pathlib.")
        merged = p1.rules + (custom,)  # nexus_managed defaults False on Rule()
        p1_with_custom = Profile(
            **{**p1.__dict__, "rules": merged}
        )
        save(tmp_path, p1_with_custom)

        # Re-run detection
        p2 = from_detection(tmp_path, tier="fast")
        ids = {r.id for r in p2.rules}
        assert "my-pathlib-rule" in ids, "user rule was clobbered"
        # And the seed rules still came through too
        assert "no-secrets" in ids
        # The custom rule preserved its unmanaged flag
        custom_round_tripped = next(r for r in p2.rules if r.id == "my-pathlib-rule")
        assert custom_round_tripped.nexus_managed is False

    def test_user_can_override_seed_rule_by_id(self, tmp_path):
        """If a user authors a rule whose id collides with a seed rule, the
        seed wins on re-detection (we strip user rules whose id is in the
        seed set, since the seed library is the source of truth for managed ids).
        Users who want to override should pick a unique id."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = ["fastapi"]\n',
            encoding="utf-8",
        )
        p1 = from_detection(tmp_path, tier="fast")
        # User reuses a seed id (their attempted override) without managed flag
        bad_override = Rule(id="no-secrets", text="My version of no-secrets.")
        p_with_bad = Profile(**{**p1.__dict__, "rules": p1.rules + (bad_override,)})
        save(tmp_path, p_with_bad)

        p2 = from_detection(tmp_path, tier="fast")
        no_secrets = [r for r in p2.rules if r.id == "no-secrets"]
        assert len(no_secrets) == 1
        # The seed-version text wins
        assert "Reference environment variables" in no_secrets[0].text

    def test_only_global_only_scoped_partition(self):
        p = _bare_profile(
            tier="fast",
            rules=(
                Rule(id="g", text="global"),
                Rule(id="s", text="scoped", applies_to=("**/*.py",)),
            ),
        )
        global_ids = {r.id for r in select_rules(p, target="cursor", only_global=True)}
        scoped_ids = {r.id for r in select_rules(p, target="cursor", only_scoped=True)}
        assert global_ids == {"g"}
        assert scoped_ids == {"s"}
