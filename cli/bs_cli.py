"""
Nexus CLI Toolkit — main entry point.

Usage from a host project: python nexus/cli/bs_cli.py <subcommand> [options]

All tools emit structured JSON by default (--format json).
Use --format human for rich terminal output.
"""

import sys
import time
from pathlib import Path


def _ensure_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 on Windows (cp1252 default breaks Unicode output)."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
        elif hasattr(stream, "buffer"):
            import io
            try:
                setattr(
                    sys,
                    stream_name,
                    io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"),
                )
            except Exception:
                pass


_ensure_utf8_stdio()

import click  # noqa: E402 - UTF-8 stdio must be configured before Click imports.


def _is_project_local_installer(path: Path) -> bool:
    """Return whether *path* is the self-contained ``project/nexus`` folder."""
    if path.name.casefold() != "nexus":
        return False
    pyproject = path / "pyproject.toml"
    if not pyproject.is_file() or not (path / "cli" / "bs_cli.py").is_file():
        return False
    try:
        content = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return 'name = "nexus-bootstrap"' in content


def _default_project_dir() -> str:
    """Use the containing project when invoked from ``project/nexus``."""
    current = Path.cwd().resolve()
    if _is_project_local_installer(current):
        return str(current.parent)
    return str(current)

# Ensure the nexus package is importable
_CLI_DIR = Path(__file__).resolve().parent
_NEXUS_DIR = _CLI_DIR.parent
if str(_NEXUS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_NEXUS_DIR.parent))

from nexus import __version__  # noqa: E402 - direct-script path bootstrap above.
from nexus.cli.security import audit_log  # noqa: E402 - direct-script path bootstrap above.


class AuditGroup(click.Group):
    """Click group that audit-logs every subcommand invocation."""

    def invoke(self, ctx):
        start = time.time()
        exit_code = 0
        try:
            return super().invoke(ctx)
        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else 1
            raise
        except Exception:
            exit_code = 1
            raise
        finally:
            duration_ms = int((time.time() - start) * 1000)
            tool_name = ctx.invoked_subcommand or "bs-cli"
            params = dict(ctx.params) if ctx.params else {}
            audit_log(
                tool=tool_name,
                args=params,
                exit_code=exit_code,
                duration_ms=duration_ms,
            )


@click.group(cls=AuditGroup)
@click.version_option(version=__version__, prog_name="nexus")
def cli():
    """Nexus CLI Toolkit — provider-neutral project context and operations."""
    pass


# --- Lazy-load subcommands to minimize import overhead ---

@cli.command("prereqs")
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="json")
@click.option("--component", default=None, help="Check/guide a specific component only.")
@click.option("--guide", is_flag=True, help="Output setup instructions for missing components.")
@click.pass_context
def prereqs_cmd(ctx, output_format, component, guide):
    """Check prerequisites and guide setup for missing components."""
    from nexus.cli.tools.prereqs import run_prereqs
    run_prereqs(output_format=output_format, component=component, guide=guide)


@cli.command("smoketest")
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="json")
@click.option("--level", type=click.Choice(["quick", "full"]), default="quick", help="Test depth.")
@click.option("--isolated-install", is_flag=True,
              help="Build and install the project wheel in a temporary virtual environment.")
@click.option("--project-dir", default=_default_project_dir, help="Project directory to test.")
@click.pass_context
def smoketest_cmd(ctx, output_format, level, isolated_install, project_dir):
    """Run tiered smoke tests on the project."""
    from nexus.cli.tools.smoketest import run_smoketest
    result = run_smoketest(output_format=output_format, level=level, project_dir=project_dir,
                           isolated_install=isolated_install)
    if result["status"] == "fail":
        ctx.exit(1)


@cli.command("debug")
@click.argument("subcommand", type=click.Choice(["logs", "trace", "deps", "env", "ports", "secrets-scan"]))
@click.argument("args", nargs=-1)
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="json")
@click.option("--project-dir", default=_default_project_dir, help="Project directory.")
@click.pass_context
def debug_cmd(ctx, subcommand, args, output_format, project_dir):
    """Debug investigation tools."""
    from nexus.cli.tools.debug import run_debug
    run_debug(subcommand=subcommand, args=args, output_format=output_format, project_dir=project_dir)


@cli.command("research")
@click.argument("subcommand", type=click.Choice(["docs", "deps", "changelog", "compare"]))
@click.argument("args", nargs=-1)
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="json")
@click.pass_context
def research_cmd(ctx, subcommand, args, output_format):
    """Research and investigate dependencies, docs, and APIs."""
    from nexus.cli.tools.research import run_research
    run_research(subcommand=subcommand, args=args, output_format=output_format)


@cli.command("scrape")
@click.argument("subcommand", type=click.Choice(["page", "api", "links", "docs"]))
@click.argument("url")
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="json")
@click.option("--depth", default=2, help="Max crawl depth for docs subcommand.")
@click.pass_context
def scrape_cmd(ctx, subcommand, url, output_format, depth):
    """Webscraping tools for external docs and APIs."""
    from nexus.cli.tools.scrape import run_scrape
    run_scrape(subcommand=subcommand, url=url, output_format=output_format, depth=depth)


@cli.command("scaffold")
@click.argument("name")
@click.option("--description", default="", help="Tool description.")
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="json")
@click.option("--project-dir", default=_default_project_dir, help="Project directory that will own the generated tool.")
@click.pass_context
def scaffold_cmd(ctx, name, description, output_format, project_dir):
    """Scaffold a tracked project-local CLI tool."""
    from nexus.cli.tools.scaffold import run_scaffold
    run_scaffold(
        name=name,
        description=description,
        output_format=output_format,
        project_dir=project_dir,
    )


@cli.command("local-env")
@click.argument("subcommand", type=click.Choice(["init", "build", "up", "down", "logs", "status", "validate"]))
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="json")
@click.option("--project-dir", default=_default_project_dir, help="Project directory.")
@click.pass_context
def local_env_cmd(ctx, subcommand, output_format, project_dir):
    """Local environment and container validation tools."""
    from nexus.cli.tools.local_env import run_local_env
    run_local_env(subcommand=subcommand, output_format=output_format, project_dir=project_dir)


@cli.command("health")
@click.argument("subcommand", type=click.Choice(["check", "components", "security", "usage", "report"]))
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="json")
@click.option("--project-dir", default=_default_project_dir, help="Project directory.")
@click.pass_context
def health_cmd(ctx, subcommand, output_format, project_dir):
    """Nexus health check — validate components work cohesively."""
    from nexus.cli.tools.health import run_health
    run_health(subcommand=subcommand, output_format=output_format, project_dir=project_dir)


@cli.command("init")
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="human")
@click.option("--upgrade", is_flag=True,
              help="Maintain an already-bootstrapped project: reuse tier, re-validate hooks. Never overwrites BOOTSTRAP.md.")
@click.option("--refresh", is_flag=True,
              help="Used with --upgrade to also regenerate BOOTSTRAP.md from the current tier template.")
@click.option("--template", type=click.Choice(["fast", "team", "enterprise"]), default=None,
              help="Skip the wizard and force a specific tier.")
@click.option("--accept-defaults", "--yes", "-y", "accept_defaults", is_flag=True,
              help="Auto-confirm interactive prompts (hook install, journal refresh, etc.). For CI/automation.")
@click.option("--dry-run", is_flag=True, help="Preview all planned writes and migrations without changing files.")
@click.option("--consumers", default="all",
              help="Comma-separated consumers: all,codex,devin,claude,cursor,copilot,devin-review.")
@click.option("--project-dir", default=_default_project_dir, help="Project to initialize.")
@click.pass_context
def init_cmd(ctx, output_format, upgrade, refresh, template, accept_defaults, dry_run, consumers, project_dir):
    """Bootstrap (or upgrade) the current project with Nexus."""
    from nexus.cli.tools.init import run_init
    run_init(project_dir=project_dir, output_format=output_format,
             upgrade=upgrade, refresh=refresh, template=template,
             accept_defaults=accept_defaults, dry_run=dry_run, consumers=consumers)


@cli.command("journal")
@click.argument("subcommand", type=click.Choice([
    "session-start", "session-end", "log", "status", "diff", "export",
    "setup-hooks", "next", "blocker", "export-summary", "init-agents",
    "decision", "intent", "handoff", "blame", "health",
]))
@click.argument("args", nargs=-1)
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="human")
@click.option("--project-dir", default=_default_project_dir, help="Project directory.")
@click.option("--no-export", "no_export", is_flag=True, default=False,
              help="Skip auto-dashboard export after 'log' (useful in tight CI loops).")
@click.option("--force", "force", is_flag=True, default=False,
              help="With 'setup-hooks': overwrite existing Nexus-installed hooks (used to upgrade old hook versions).")
@click.pass_context
def journal_cmd(ctx, subcommand, args, output_format, project_dir, no_export, force):
    """Project journal — cross-session state tracking, git diff, and dashboard export."""
    from nexus.cli.tools.journal import run_journal
    run_journal(subcommand=subcommand, args=args, output_format=output_format,
                project_dir=project_dir, no_export=no_export, force=force)


@cli.command("supply-chain")
@click.argument("subcommand", type=click.Choice(["scan", "ioc", "audit", "advisories"]))
@click.argument("args", nargs=-1)
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="json")
@click.option("--project-dir", default=_default_project_dir, help="Project directory to scan.")
@click.pass_context
def supply_chain_cmd(ctx, subcommand, args, output_format, project_dir):
    """Supply chain security scanner — detect compromised packages and IOCs."""
    from nexus.cli.tools.supply_chain import run_supply_chain
    run_supply_chain(subcommand=subcommand, args=args, output_format=output_format, project_dir=project_dir)


@cli.command("profile")
@click.argument("subcommand", type=click.Choice(["detect", "show", "set"]))
@click.argument("args", nargs=-1)
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="human")
@click.option("--project-dir", default=_default_project_dir, help="Project directory.")
@click.pass_context
def profile_cmd(ctx, subcommand, args, output_format, project_dir):
    """Manage the project profile (.nexus/profile.json) -- the source of truth for cross-IDE generation."""
    from nexus.cli.tools.profile_cmd import run_profile
    run_profile(subcommand=subcommand, args=args, output_format=output_format, project_dir=project_dir)


@cli.command("generate")
@click.option("--target", "targets", default=None,
              help="Comma-separated targets (agents_md,claude,cursor,copilot). Default: all.")
@click.option("--dry-run", is_flag=True, help="Show what would be written without writing.")
@click.option("--force", is_flag=True, help="Overwrite managed blocks even when no profile change is detected.")
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="human")
@click.option("--project-dir", default=_default_project_dir, help="Project directory.")
@click.pass_context
def generate_cmd(ctx, targets, dry_run, force, output_format, project_dir):
    """Generate IDE-specific files (AGENTS.md, CLAUDE.md, .cursor/rules/, copilot-instructions) from the profile."""
    from nexus.cli.tools.generate_cmd import run_generate
    run_generate(output_format=output_format, project_dir=project_dir,
                 targets=targets, dry_run=dry_run, force=force)


@cli.command("doctor")
@click.option("--deep", is_flag=True, help="Re-run stack detection and diff against stored profile.")
@click.option("--consumer", default="all",
              help="Consumer to verify: all,codex,devin,claude,cursor,copilot,devin-review,vscode.")
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="human")
@click.option("--project-dir", default=_default_project_dir, help="Project directory.")
@click.pass_context
def doctor_cmd(ctx, deep, consumer, output_format, project_dir):
    """Check rule drift, version mismatch, missing IDE files, and journal health."""
    from nexus.cli.tools.doctor import run_doctor
    result = run_doctor(output_format=output_format, project_dir=project_dir, deep=deep,
                        consumer=consumer)
    if result["status"] == "fail":
        ctx.exit(1)


@cli.group("context")
def context_group():
    """Audit, map, mask, scope, and route AI coding context."""
    pass


@context_group.command("audit")
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="json")
@click.option("--project-dir", default=_default_project_dir, help="Project directory.")
def context_audit_cmd(output_format, project_dir):
    """Report effective context, duplication, ignores, and readiness."""
    from nexus.cli.tools.context import audit_context, audit_status, emit_context_result
    details = audit_context(Path(project_dir))
    status = audit_status(details)
    emit_context_result("context-audit", details, output_format, status)
    if status.value == "fail":
        raise click.exceptions.Exit(1)


@context_group.command("map")
@click.argument("query", required=False)
@click.option("--engine", type=click.Choice(["inventory", "repomix"]), default="inventory")
@click.option("--budget-tokens", type=click.IntRange(min=64), default=2000)
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="json")
@click.option("--project-dir", default=_default_project_dir, help="Project directory.")
def context_map_cmd(query, engine, budget_tokens, output_format, project_dir):
    """Build a bounded repository skeleton, optionally filtered by QUERY."""
    from nexus.cli.tools.context import build_map, emit_context_result
    emit_context_result("context-map", build_map(Path(project_dir), query, engine, budget_tokens), output_format)


@context_group.command("mask")
@click.option("--input", "input_value", required=True, help="Project-relative file or - for stdin.")
@click.option("--kind", type=click.Choice(["auto", "test", "lint", "build"]), default="auto")
@click.option("--exit-code", type=int, default=0)
@click.option("--max-chars", type=click.IntRange(min=64), default=1200)
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="json")
@click.option("--project-dir", default=_default_project_dir, help="Project directory.")
def context_mask_cmd(input_value, kind, exit_code, max_chars, output_format, project_dir):
    """Compress test, lint, build, or terminal output deterministically."""
    from nexus.cli.tools.context import emit_context_result, mask_observation, read_mask_input
    try:
        raw = read_mask_input(Path(project_dir), input_value)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    emit_context_result("context-mask", mask_observation(raw, kind, exit_code, max_chars), output_format)


@context_group.command("ignores")
@click.option("--check", "check_only", is_flag=True, help="Only report missing patterns (default).")
@click.option("--apply", "apply_changes", is_flag=True, help="Write idempotent managed blocks.")
@click.option("--tool", type=click.Choice(["all", "codeium", "cursor", "aider", "repomix"]), default="all")
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="json")
@click.option("--project-dir", default=_default_project_dir, help="Project directory.")
def context_ignores_cmd(check_only, apply_changes, tool, output_format, project_dir):
    """Check or apply AI-tool context ignore rules."""
    from nexus.cli.tools.context import emit_context_result, manage_ignores
    if check_only and apply_changes:
        raise click.UsageError("--check and --apply are mutually exclusive")
    emit_context_result("context-ignores", manage_ignores(Path(project_dir), tool, apply_changes), output_format)


@context_group.command("route")
@click.option("--task-class", "task_class", type=click.Choice(["mechanical", "routine", "complex", "high-risk"]), required=True)
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="json")
def context_route_cmd(task_class, output_format):
    """Recommend a capability role and verification depth."""
    from nexus.cli.tools.context import emit_context_result, route_task
    emit_context_result("context-route", route_task(task_class), output_format)


if __name__ == "__main__":
    cli()
