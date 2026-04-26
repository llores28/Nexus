"""
Security framework for the Bootstrap CLI Toolkit.
Input validation, path sanitization, URL validation, audit logging, secret detection.
"""

import ipaddress
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


# --- Path Sanitization ---

def validate_path(path_str: str, project_root: Optional[Path] = None) -> Path:
    """
    Validate a file path is safe: no traversal outside project root,
    no absolute paths outside boundary, no symlink escape.
    Returns resolved Path if safe, raises ValueError otherwise.
    """
    if project_root is None:
        from nexus.cli.utils import find_project_root
        project_root = find_project_root()

    project_root = project_root.resolve()
    target = (project_root / path_str).resolve()

    if not str(target).startswith(str(project_root)):
        raise ValueError(
            f"Path traversal blocked: '{path_str}' resolves outside project root "
            f"'{project_root}'"
        )

    return target


def validate_path_exists(path_str: str, project_root: Optional[Path] = None) -> Path:
    """Validate path is safe AND exists."""
    target = validate_path(path_str, project_root)
    if not target.exists():
        raise ValueError(f"Path does not exist: '{target}'")
    return target


# --- URL Validation ---

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fc00::/7"),
]

_BLOCKED_SCHEMES = {"file", "ftp", "data", "javascript"}


def validate_url(url: str, allow_private: bool = False) -> str:
    """
    Validate a URL is safe for fetching:
    - Must be http or https
    - Must not resolve to private/internal IP ranges (SSRF protection)
    - Must not use blocked schemes
    Returns the URL if safe, raises ValueError otherwise.
    """
    parsed = urlparse(url)

    if not parsed.scheme:
        raise ValueError(f"URL missing scheme: '{url}'. Use http:// or https://")

    if parsed.scheme.lower() in _BLOCKED_SCHEMES:
        raise ValueError(f"Blocked URL scheme: '{parsed.scheme}' in '{url}'")

    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"Only http/https URLs allowed, got: '{parsed.scheme}'")

    if not parsed.hostname:
        raise ValueError(f"URL missing hostname: '{url}'")

    if not allow_private:
        hostname = parsed.hostname
        try:
            import socket
            resolved = socket.getaddrinfo(hostname, None)
            for _, _, _, _, sockaddr in resolved:
                ip = ipaddress.ip_address(sockaddr[0])
                for network in _PRIVATE_NETWORKS:
                    if ip in network:
                        raise ValueError(
                            f"URL resolves to private/internal IP ({ip}): '{url}'. "
                            f"This is blocked for SSRF protection."
                        )
        except socket.gaierror:
            pass  # DNS resolution failed — will fail at fetch time

    return url


# --- Package Name Validation ---

_PACKAGE_NAME_RE = re.compile(r"^[@a-zA-Z0-9][\w.\-/]{0,213}$")


def validate_package_name(name: str) -> str:
    """Validate a package name is safe (no shell metacharacters)."""
    if not _PACKAGE_NAME_RE.match(name):
        raise ValueError(
            f"Invalid package name: '{name}'. "
            f"Must be alphanumeric with hyphens/dots/slashes, max 214 chars."
        )
    return name


# --- Command Safety ---

def safe_command_args(cmd: list[str]) -> list[str]:
    """
    Validate command arguments for subprocess calls.
    Ensures no shell metacharacters that could enable injection.
    Returns the args list if safe, raises ValueError otherwise.
    """
    shell_metachars = set(";|&$`\\!#(){}[]<>")
    for arg in cmd:
        dangerous = shell_metachars.intersection(arg)
        if dangerous:
            raise ValueError(
                f"Shell metacharacters detected in command arg: '{arg}' "
                f"(chars: {dangerous}). Use explicit args, not shell strings."
            )
    return cmd


# --- Secret Detection ---

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|apikey)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(secret|password|passwd|pwd)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(access[_-]?token|auth[_-]?token|bearer)\s*[:=]\s*\S+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),                          # AWS access key
    re.compile(r"sk_live_[0-9a-zA-Z]{24,}"),                  # Stripe secret key
    re.compile(r"sk-[0-9a-zA-Z]{20,}"),                       # OpenAI key pattern
    re.compile(r"ghp_[0-9a-zA-Z]{36}"),                       # GitHub personal token
    re.compile(r"gho_[0-9a-zA-Z]{36}"),                       # GitHub OAuth token
    re.compile(r"glpat-[0-9a-zA-Z\-_]{20,}"),                 # GitLab token
    re.compile(r"xox[bpors]-[0-9a-zA-Z\-]{10,}"),             # Slack token
    re.compile(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----"),
    re.compile(r"(?i)mongodb(\+srv)?://[^\s]+:[^\s]+@"),       # MongoDB connection string
    re.compile(r"(?i)postgres(ql)?://[^\s]+:[^\s]+@"),         # Postgres connection string
]

# Loose `name = value` patterns where the value alone may be a placeholder
# rather than a real secret. Indices into _SECRET_PATTERNS.
_LOOSE_PATTERN_INDICES = {0, 1, 2}

# Values that are obviously not real secrets: env-var passthrough syntax,
# template/example placeholders. Strict patterns (AWS/Stripe/OpenAI literal
# tokens) never match these forms, so this filter is only consulted for the
# loose name=value patterns above.
_PLACEHOLDER_VALUE_RE = re.compile(
    r"""^(?:
        \$\{[^}]+\}                # ${VAR}
      | \$[A-Z_][A-Z0-9_]*         # $VAR
      | <[^>]+>                    # <placeholder>
      | "(?:\$\{[^}]+\}|<[^>]+>|\.{2,}|)"   # quoted placeholder / empty
      | '(?:\$\{[^}]+\}|<[^>]+>|\.{2,}|)'
      | sk-(?:ant-|or-)?\.{2,}     # sk-..., sk-ant-..., sk-or-...
      | \.{2,}                     # bare ... or longer
      | (?:your|my|some|example|placeholder|changeme|todo)[\w_-]*
      | x{3,}                      # xxx, xxxxx
    )\s*(?:\#.*)?$""",
    re.VERBOSE | re.IGNORECASE,
)


def _value_after_assign(line: str) -> Optional[str]:
    """Return the value after the first `=` or `:` on a line, stripped."""
    m = re.search(r"[:=]\s*(.+?)\s*(?:#.*)?$", line)
    return m.group(1).strip() if m else None


def _is_placeholder_value(line: str) -> bool:
    """True when the assigned value is clearly a template/passthrough, not a real secret."""
    value = _value_after_assign(line)
    if value is None:
        return False
    return bool(_PLACEHOLDER_VALUE_RE.match(value))


def scan_text_for_secrets(text: str) -> list[dict]:
    """
    Scan text for common secret patterns.
    Returns list of findings with line number and pattern name — never the actual secret.
    Skips findings where the value is an env-var passthrough or template placeholder
    (e.g. `KEY=${KEY}`, `KEY=sk-...`, `KEY=<your-key>`).
    """
    findings = []
    for line_num, line in enumerate(text.splitlines(), 1):
        for idx, pattern in enumerate(_SECRET_PATTERNS):
            if pattern.search(line):
                if idx in _LOOSE_PATTERN_INDICES and _is_placeholder_value(line):
                    continue
                findings.append({
                    "line": line_num,
                    "pattern": pattern.pattern[:60],
                    "preview": _redact_line(line),
                })
    return findings


def _redact_line(line: str, max_len: int = 80) -> str:
    """Show line structure but redact potential secret values."""
    line = line.strip()
    if len(line) > max_len:
        line = line[:max_len] + "..."
    # Redact anything after = or : that looks like a value
    redacted = re.sub(r"([:=]\s*).+", r"\1[REDACTED]", line)
    return redacted


def sanitize_output(text: str) -> str:
    """Strip secret-like patterns from output before logging."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


# --- Config-file filtering for secret scanners ---
#
# Out-of-scope file classes for leak prevention:
#   - gitignored: secrets in untracked files can't leak via commits.
#   - template:  .env.example / .env.template etc. carry placeholder values
#                by convention (`KEY=change_me`, `KEY=<your-key>`).
# Both filters apply to the auto-glob path of secret scanners; staged-files
# scanning is unaffected because that's the actual leak hot path.

# Template-file suffix detection. We match BOTH:
#   - filename ends with the suffix:        ".env.example"
#   - filename has the suffix as a discrete segment, then more text:
#                                           ".env.template.json"  (rare but valid)
# We deliberately do NOT match the suffix as a free substring (the previous
# implementation did `s in name`, which falsely matched `redistribute.json`
# for `.dist`, `samplefoo.txt` for `.sample`, etc.).
_TEMPLATE_SUFFIXES = (".example", ".template", ".sample", ".dist", ".tmpl")


def is_template_file(fpath: Path) -> bool:
    """True if filename indicates a placeholder/template (e.g. .env.example).

    Matches `.example` / `.template` / `.sample` / `.dist` / `.tmpl` as a
    filename segment — either at the end of the name, or followed by another
    extension (`.env.template.json`). Rejects substring-only matches like
    `redistribute.json` (was a false positive in the prior implementation).
    """
    name = fpath.name.lower()
    for suffix in _TEMPLATE_SUFFIXES:
        if name.endswith(suffix):
            return True
        # `.template` followed by another extension (e.g. .env.template.json)
        if f"{suffix}." in name:
            return True
    return False


def gitignored_files(project_dir: Path, paths: list[Path]) -> set[str]:
    """Return relative POSIX paths that git considers ignored. Empty set if no
    git or no matches. Uses argv rather than `--stdin` (the latter has a
    flushing bug on Windows git ≤2.40 where exit/stdout disagree)."""
    if not paths:
        return set()
    try:
        rel = [Path(p).relative_to(project_dir).as_posix() for p in paths]
        result = subprocess.run(
            ["git", "check-ignore", *rel],
            capture_output=True, text=True, cwd=str(project_dir), timeout=10,
        )
        # exit 0: matches; exit 1: no matches (not an error). stdout = matched paths.
        return {ln.strip().replace("\\", "/") for ln in result.stdout.splitlines() if ln.strip()}
    except (subprocess.SubprocessError, OSError):
        return set()


# --- Audit Logging ---

_AUDIT_DIR = Path(".cache") / "bs-cli"
_AUDIT_FILE = _AUDIT_DIR / "audit.jsonl"
_AUDIT_MAX_BYTES = 5 * 1024 * 1024  # 5 MB cap; rotate to audit.jsonl.1 on overflow


def _rotate_log_if_needed(path: Path, max_bytes: int) -> None:
    """Rotate `path` to `path.1` when it exceeds `max_bytes`. Keeps one backup.

    Best-effort and silent: if rotation fails (permission, race), the caller
    will just keep appending to the original file rather than crash. Safe to
    call before every append.
    """
    try:
        if not path.exists():
            return
        if path.stat().st_size < max_bytes:
            return
    except OSError:
        return

    backup = path.with_suffix(path.suffix + ".1")
    try:
        if backup.exists():
            backup.unlink()
        path.rename(backup)
    except OSError:
        pass  # Can't rotate; appending will continue (file may grow until next call)


def audit_log(
    tool: str,
    args: dict,
    exit_code: int = 0,
    duration_ms: int = 0,
    project_root: Optional[Path] = None,
) -> None:
    """
    Append an audit entry to .cache/bs-cli/audit.jsonl.
    Sanitizes args to remove potential secret values.
    Rotates to audit.jsonl.1 when the file exceeds 5 MB so unbounded CLI
    usage doesn't accumulate without bound.
    """
    root = project_root or Path.cwd()
    audit_path = root / _AUDIT_FILE

    try:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_log_if_needed(audit_path, _AUDIT_MAX_BYTES)

        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tool": tool,
            "args": {k: sanitize_output(str(v)) for k, v in args.items()},
            "exit_code": exit_code,
            "duration_ms": duration_ms,
        }

        with open(audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # Don't fail the tool if audit logging fails
