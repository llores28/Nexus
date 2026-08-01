"""
Smoketest Tool — tiered project health checks.

Auto-detects project type and runs:
  quick: (1) deps verify, (2) lint/typecheck, (3) unit tests
  full:  + (4) build, (5) server start + health check + stop
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import venv
from pathlib import Path
from typing import Any, Optional

from nexus.cli.utils import (
    OutputFormat, Status, emit, make_result, truncate_output, find_project_root,
)
from nexus.cli.security import validate_path, audit_log


# --- Project detection ---

def _detect_project(project_dir: Path) -> dict[str, Any]:
    """Detect project type, package manager, and available commands."""
    info: dict[str, Any] = {
        "type": "unknown",
        "package_manager": None,
        "commands": {},
        "has_dockerfile": False,
    }

    # Node.js
    pkg_json = project_dir / "package.json"
    if pkg_json.exists():
        info["type"] = "node"
        try:
            with open(pkg_json, "r", encoding="utf-8") as f:
                pkg = json.load(f)
            scripts = pkg.get("scripts", {})
            info["commands"] = {
                "install": _detect_node_pm(project_dir) + " install",
                "lint": _find_script(scripts, ["lint", "eslint"]),
                "typecheck": _find_script(scripts, ["typecheck", "type-check", "tsc"]),
                "test": _find_script(scripts, ["test", "jest", "vitest"]),
                "build": _find_script(scripts, ["build"]),
                "start": _find_script(scripts, ["start", "dev", "serve"]),
            }
            info["package_manager"] = _detect_node_pm(project_dir)
        except (json.JSONDecodeError, OSError):
            pass

    # Python
    pyproject = project_dir / "pyproject.toml"
    requirements = project_dir / "requirements.txt"
    if pyproject.exists() or requirements.exists():
        if info["type"] == "unknown":
            info["type"] = "python"
        elif info["type"] == "node":
            info["type"] = "fullstack"

        py_cmds = {}
        if pyproject.exists():
            py_cmds["install"] = "python -m pip check"
            # Check for common tools in pyproject
            try:
                content = pyproject.read_text(encoding="utf-8")
                if "pytest" in content:
                    py_cmds["test"] = "python -m pytest"
                if "[tool.ruff" in content and _module_available("ruff"):
                    py_cmds["lint"] = "python -m ruff check ."
                elif "[flake8]" in content and _module_available("flake8"):
                    py_cmds["lint"] = "python -m flake8 ."
                if "[tool.mypy]" in content and _module_available("mypy"):
                    py_cmds["typecheck"] = "python -m mypy ."
            except OSError:
                pass
        elif requirements.exists():
            py_cmds["install"] = "python -m pip check"

        # Merge with any existing commands
        for k, v in py_cmds.items():
            if not info["commands"].get(k):
                info["commands"][k] = v
        if info.get("package_manager") is None:
            info["package_manager"] = "pip"

    # Go
    go_mod = project_dir / "go.mod"
    if go_mod.exists():
        info["type"] = "go"
        info["commands"] = {
            "install": "go mod download",
            "build": "go build ./...",
            "test": "go test ./...",
            "lint": "golangci-lint run" if _cmd_exists("golangci-lint") else None,
        }

    # Docker
    info["has_dockerfile"] = (project_dir / "Dockerfile").exists()
    info["has_compose"] = (
        (project_dir / "docker-compose.yml").exists()
        or (project_dir / "docker-compose.yaml").exists()
        or (project_dir / "compose.yml").exists()
        or (project_dir / "compose.yaml").exists()
    )

    return info


def _detect_node_pm(project_dir: Path) -> str:
    """Detect Node package manager."""
    if (project_dir / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (project_dir / "yarn.lock").exists():
        return "yarn"
    if (project_dir / "bun.lockb").exists():
        return "bun"
    return "npm"


def _find_script(scripts: dict, names: list[str]) -> Optional[str]:
    """Find first matching npm script."""
    for name in names:
        if name in scripts:
            pm = "npm"  # Will be replaced at run time
            return f"{pm} run {name}"
    return None


def _cmd_exists(cmd: str) -> bool:
    """Check if a command exists on PATH."""
    import shutil
    return shutil.which(cmd) is not None


def _module_available(name: str) -> bool:
    """Return whether a Python tool can run through the active interpreter."""
    import importlib.util
    return importlib.util.find_spec(name) is not None


def _project_python(project_dir: Path) -> Optional[Path]:
    """Return a project-owned interpreter without falling back to global Python."""
    candidates = (
        project_dir / ".venv" / "Scripts" / "python.exe",
        project_dir / ".venv" / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    try:
        prefix = Path(sys.prefix).resolve()
        root = project_dir.resolve()
        if prefix == root or root in prefix.parents:
            return Path(sys.executable)
    except OSError:
        pass
    return None


# --- Step runners ---

def _run_step(
    name: str,
    cmd_str: Optional[str],
    cwd: Path,
    timeout: int = 120,
    python_executable: Optional[Path] = None,
) -> dict[str, Any]:
    """Run a single smoketest step. Returns structured result."""
    if not cmd_str:
        return {
            "step": name,
            "status": "skip",
            "message": "No command configured for this step",
            "duration_ms": 0,
        }
    start = time.time()
    try:
        import shlex

        args = shlex.split(cmd_str)
        if args and args[0].lower() in {"python", "python3"}:
            args[0] = str(python_executable or sys.executable)
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, cwd=str(cwd),
            env={**os.environ, "CI": "true", "NODE_ENV": "test"},
        )
        payload: dict[str, Any] = {
            "step": name,
            "status": "pass" if result.returncode == 0 else "fail",
            "command": cmd_str,
            "duration_ms": int((time.time() - start) * 1000),
            "stdout": truncate_output(result.stdout) if result.stdout else "",
        }
        if result.returncode != 0:
            payload["exit_code"] = result.returncode
            payload["stderr"] = truncate_output(result.stderr) if result.stderr else ""
        return payload
    except subprocess.TimeoutExpired:
        return {
            "step": name, "status": "fail", "command": cmd_str,
            "duration_ms": int((time.time() - start) * 1000),
            "message": f"Timed out after {timeout}s",
        }
    except (FileNotFoundError, OSError) as exc:
        return {
            "step": name, "status": "fail", "command": cmd_str,
            "duration_ms": int((time.time() - start) * 1000),
            "message": f"{type(exc).__name__}: {exc}",
        }


def _isolated_install(project_dir: Path) -> dict[str, Any]:
    """Build and import the project wheel without mutating the active Python."""
    if not (project_dir / "pyproject.toml").is_file():
        return {
            "step": "isolated-install",
            "status": "skip",
            "message": "No pyproject.toml; wheel verification is not applicable",
            "duration_ms": 0,
        }

    start = time.time()
    try:
        with tempfile.TemporaryDirectory(prefix="nexus-smoketest-") as raw:
            root = Path(raw)
            wheels = root / "wheels"
            wheels.mkdir()
            build = subprocess.run(
                [sys.executable, "-m", "pip", "wheel", str(project_dir), "--no-deps", "--wheel-dir", str(wheels)],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if build.returncode != 0:
                return {
                    "step": "isolated-install",
                    "status": "fail",
                    "exit_code": build.returncode,
                    "duration_ms": int((time.time() - start) * 1000),
                    "stderr": truncate_output(build.stderr),
                }
            wheel_files = sorted(wheels.glob("*.whl"))
            if not wheel_files:
                return {
                    "step": "isolated-install",
                    "status": "fail",
                    "duration_ms": int((time.time() - start) * 1000),
                    "message": "Wheel build succeeded but produced no wheel",
                }
            env_dir = root / "venv"
            venv.EnvBuilder(with_pip=True).create(env_dir)
            env_python = env_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            install = subprocess.run(
                [str(env_python), "-m", "pip", "install", str(wheel_files[0])],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if install.returncode != 0:
                return {
                    "step": "isolated-install",
                    "status": "fail",
                    "exit_code": install.returncode,
                    "duration_ms": int((time.time() - start) * 1000),
                    "stderr": truncate_output(install.stderr),
                }
            verify = subprocess.run(
                [str(env_python), "-m", "nexus.cli.bs_cli", "--version"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return {
                "step": "isolated-install",
                "status": "pass" if verify.returncode == 0 else "fail",
                "exit_code": verify.returncode,
                "duration_ms": int((time.time() - start) * 1000),
                "wheel": wheel_files[0].name,
                "stdout": truncate_output(verify.stdout),
                "stderr": truncate_output(verify.stderr),
            }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "step": "isolated-install",
            "status": "fail",
            "duration_ms": int((time.time() - start) * 1000),
            "message": f"{type(exc).__name__}: {exc}",
        }

# --- Server health check ---

def _check_server_health(
    cmd_str: str,
    cwd: Path,
    port: int = 3000,
    wait_secs: int = 15,
) -> dict[str, Any]:
    """Start a dev server, wait for health, then stop it."""
    import shlex

    start = time.time()
    args = shlex.split(cmd_str)

    try:
        proc = subprocess.Popen(
            args,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "PORT": str(port)},
        )

        # Wait for server to come up
        import socket
        healthy = False
        for _ in range(wait_secs * 2):
            time.sleep(0.5)
            if proc.poll() is not None:
                # Process exited
                break
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    healthy = True
                    break
            except (ConnectionRefusedError, OSError, socket.timeout):
                continue

        duration_ms = int((time.time() - start) * 1000)

        # Kill the server
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

        if healthy:
            return {
                "step": "server-health",
                "status": "pass",
                "command": cmd_str,
                "port": port,
                "duration_ms": duration_ms,
                "message": f"Server healthy on port {port}",
            }
        else:
            stdout = proc.stdout.read() if proc.stdout else ""
            stderr = proc.stderr.read() if proc.stderr else ""
            return {
                "step": "server-health",
                "status": "fail",
                "command": cmd_str,
                "port": port,
                "duration_ms": duration_ms,
                "message": f"Server did not respond on port {port} within {wait_secs}s",
                "stderr": truncate_output(stderr),
            }

    except Exception as e:
        return {
            "step": "server-health",
            "status": "fail",
            "command": cmd_str,
            "duration_ms": int((time.time() - start) * 1000),
            "message": str(e),
        }


# --- Main runner ---

def run_smoketest(
    output_format: str = "json",
    level: str = "quick",
    project_dir: str = ".",
    isolated_install: bool = False,
) -> dict[str, Any]:
    """Run smoketest pipeline."""
    fmt = OutputFormat(output_format)
    proj_path = Path(project_dir).resolve()

    # Detect project
    detection = _detect_project(proj_path)
    cmds = detection["commands"]

    steps: list[dict[str, Any]] = []
    total_start = time.time()

    if isolated_install:
        steps.append(_isolated_install(proj_path))

    project_python = _project_python(proj_path)

    # Step 1: Dependency verification must not inspect an unrelated global
    # interpreter. Setup standardizes Python projects on `<project>/.venv`.
    dependency_cmd = cmds.get("install")
    if dependency_cmd and dependency_cmd.startswith(("python ", "python3 ")) and project_python is None:
        steps.append({
            "step": "deps-verify",
            "status": "skip",
            "message": "No project-local .venv; run Nexus setup or use --isolated-install",
            "duration_ms": 0,
        })
    else:
        steps.append(
            _run_step(
                "deps-verify",
                dependency_cmd,
                proj_path,
                timeout=180,
                python_executable=project_python,
            )
        )

    # Step 2: Lint / typecheck
    lint_result = _run_step(
        "lint", cmds.get("lint"), proj_path, timeout=60, python_executable=project_python
    )
    steps.append(lint_result)
    tc_result = _run_step(
        "typecheck", cmds.get("typecheck"), proj_path, timeout=60,
        python_executable=project_python,
    )
    steps.append(tc_result)

    # Step 3: Unit tests
    steps.append(
        _run_step(
            "test", cmds.get("test"), proj_path, timeout=180,
            python_executable=project_python,
        )
    )

    if level == "full":
        # Step 4: Build
        steps.append(
            _run_step(
                "build", cmds.get("build"), proj_path, timeout=300,
                python_executable=project_python,
            )
        )

        # Step 5: Server start + health check
        start_cmd = cmds.get("start")
        if start_cmd:
            steps.append(_check_server_health(start_cmd, proj_path))
        else:
            steps.append({
                "step": "server-health",
                "status": "skip",
                "message": "No start command configured",
                "duration_ms": 0,
            })

    total_duration = int((time.time() - total_start) * 1000)

    # Summarize
    passed = sum(1 for s in steps if s["status"] == "pass")
    failed = sum(1 for s in steps if s["status"] == "fail")
    skipped = sum(1 for s in steps if s["status"] == "skip")

    if failed > 0:
        overall = Status.FAIL
        msg = f"{failed} step(s) failed, {passed} passed, {skipped} skipped"
    elif skipped == len(steps):
        overall = Status.SKIP
        msg = "All steps skipped — no commands detected"
    else:
        overall = Status.PASS
        msg = f"All {passed} step(s) passed ({skipped} skipped)"

    result = make_result("smoketest", overall, msg, duration_ms=total_duration)
    result["level"] = level
    result["project"] = {
        "type": detection["type"],
        "package_manager": detection.get("package_manager"),
        "has_dockerfile": detection["has_dockerfile"],
    }
    result["steps"] = steps

    emit(result, fmt)
    return result
