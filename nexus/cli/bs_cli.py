"""
Nexus CLI Toolkit — main entry point.

Usage: python nexus/cli/bs_cli.py <subcommand> [options]

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

import click

# Ensure the nexus package is importable
_CLI_DIR = Path(__file__).resolve().parent
_NEXUS_DIR = _CLI_DIR.parent
if str(_NEXUS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_NEXUS_DIR.parent))

from nexus.cli.security import audit_log


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
@click.version_option(version="0.2.0", prog_name="nexus")
def cli():
    """Nexus CLI Toolkit — profile-driven cross-IDE generator with drift detection."""
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
@click.option("--project-dir", default=".", help="Project directory to test.")
@click.pass_context
def smoketest_cmd(ctx, output_format, level, project_dir):
    """Run tiered smoke tests on the project."""
    from nexus.cli.tools.smoketest import run_smoketest
    run_smoketest(output_format=output_format, level=level, project_dir=project_dir)


@cli.command("debug")
@click.argument("subcommand", type=click.Choice(["logs", "trace", "deps", "env", "ports", "secrets-scan"]))
@click.argument("args", nargs=-1)
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="json")
@click.option("--project-dir", default=".", help="Project directory.")
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
@click.pass_context
def scaffold_cmd(ctx, name, description, output_format):
    """Scaffold a new CLI tool from template."""
    from nexus.cli.tools.scaffold import run_scaffold
    run_scaffold(name=name, description=description, output_format=output_format)


@cli.command("local-env")
@click.argument("subcommand", type=click.Choice(["init", "build", "up", "down", "logs", "status", "validate"]))
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="json")
@click.option("--project-dir", default=".", help="Project directory.")
@click.pass_context
def local_env_cmd(ctx, subcommand, output_format, project_dir):
    """Local environment and container validation tools."""
    from nexus.cli.tools.local_env import run_local_env
    run_local_env(subcommand=subcommand, output_format=output_format, project_dir=project_dir)


@cli.command("health")
@click.argument("subcommand", type=click.Choice(["check", "components", "security", "usage", "report"]))
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="json")
@click.option("--project-dir", default=".", help="Project directory.")
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
@click.option("--project-dir", default=".", help="Project to initialize.")
@click.pass_context
def init_cmd(ctx, output_format, upgrade, refresh, template, accept_defaults, project_dir):
    """Bootstrap (or upgrade) the current project with Nexus."""
    from nexus.cli.tools.init import run_init
    run_init(project_dir=project_dir, output_format=output_format,
             upgrade=upgrade, refresh=refresh, template=template,
             accept_defaults=accept_defaults)


@cli.command("journal")
@click.argument("subcommand", type=click.Choice([
    "session-start", "session-end", "log", "status", "diff", "export",
    "setup-hooks", "next", "blocker", "export-summary", "init-agents",
    "decision", "blame", "health",
]))
@click.argument("args", nargs=-1)
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="human")
@click.option("--project-dir", default=".", help="Project directory.")
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
@click.option("--project-dir", default=".", help="Project directory to scan.")
@click.pass_context
def supply_chain_cmd(ctx, subcommand, args, output_format, project_dir):
    """Supply chain security scanner — detect compromised packages and IOCs."""
    from nexus.cli.tools.supply_chain import run_supply_chain
    run_supply_chain(subcommand=subcommand, args=args, output_format=output_format, project_dir=project_dir)


@cli.command("profile")
@click.argument("subcommand", type=click.Choice(["detect", "show", "set"]))
@click.argument("args", nargs=-1)
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="human")
@click.option("--project-dir", default=".", help="Project directory.")
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
@click.option("--project-dir", default=".", help="Project directory.")
@click.pass_context
def generate_cmd(ctx, targets, dry_run, force, output_format, project_dir):
    """Generate IDE-specific files (AGENTS.md, CLAUDE.md, .cursor/rules/, copilot-instructions) from the profile."""
    from nexus.cli.tools.generate_cmd import run_generate
    run_generate(output_format=output_format, project_dir=project_dir,
                 targets=targets, dry_run=dry_run, force=force)


@cli.command("doctor")
@click.option("--deep", is_flag=True, help="Re-run stack detection and diff against stored profile.")
@click.option("--format", "output_format", type=click.Choice(["json", "human", "yaml"]), default="human")
@click.option("--project-dir", default=".", help="Project directory.")
@click.pass_context
def doctor_cmd(ctx, deep, output_format, project_dir):
    """Check rule drift, version mismatch, missing IDE files, and journal health."""
    from nexus.cli.tools.doctor import run_doctor
    run_doctor(output_format=output_format, project_dir=project_dir, deep=deep)


if __name__ == "__main__":
    cli()
