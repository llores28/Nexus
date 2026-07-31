"""
Generators -- project profile -> IDE-specific files.

Each generator module exports::

    def generate(profile: Profile, project_root: Path) -> list[GeneratedFile]: ...

The :func:`run_all` orchestrator collects from all registered generators,
writes each file (overwriting or upserting a managed block), and returns
``(file, action)`` pairs so callers can report what happened.

Managed-block pattern
---------------------
A file's Nexus-owned content lives between::

    <!-- nexus:<block-id>:begin -->
    ... body ...
    <!-- nexus:<block-id>:end -->

Anything outside is preserved verbatim. This is the same convention used by
``journal._upsert_agents_md`` (with the ``nexus:state:begin/end`` markers).

Each generated body's first line is a stamp::

    <!-- nexus: profile=<sha256:12> generator=<id> nexus_version=<v> -->

``nexus doctor`` reads this stamp to detect drift in O(1) without re-running
detection.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional

from nexus.cli.profile import (
    ALL_TARGETS,
    NEXUS_VERSION,
    Profile,
    Target,
    hash_profile,
    select_rules,
)

WriteMode = Literal["overwrite", "upsert"]


@dataclass
class GeneratedFile:
    """One file a generator wants to write."""

    path: Path
    content: str
    mode: WriteMode
    target: Target
    block_id: str


def begin_marker(block_id: str) -> str:
    return f"<!-- nexus:{block_id}:begin -->"


def end_marker(block_id: str) -> str:
    return f"<!-- nexus:{block_id}:end -->"


def stamp(profile_hash: str, generator: str) -> str:
    return f"<!-- nexus: profile={profile_hash} generator={generator} nexus_version={NEXUS_VERSION} -->"


def upsert_managed_block(path: Path, body: str, block_id: str) -> str:
    """Insert/replace the managed block in ``path``.

    Returns one of ``'created' | 'updated' | 'unchanged' | 'inserted'``.
    Existing user content outside the markers is preserved verbatim.
    """
    begin = begin_marker(block_id)
    end = end_marker(block_id)
    block = f"{begin}\n{body.rstrip()}\n{end}\n"

    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        path.write_text(block, encoding="utf-8")
        return "created"

    existing = path.read_text(encoding="utf-8")

    if begin in existing and end in existing:
        before, _, rest = existing.partition(begin)
        _, _, after = rest.partition(end)
        new_content = before + block.rstrip("\n") + ("\n" if after.startswith("\n") else "\n") + after.lstrip("\n")
        if new_content == existing:
            return "unchanged"
        path.write_text(new_content, encoding="utf-8")
        return "updated"

    sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    path.write_text(existing + sep + block, encoding="utf-8")
    return "inserted"


def overwrite_file(path: Path, content: str) -> str:
    """Write ``path`` with exactly ``content``. Returns 'created' | 'updated' | 'unchanged'."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") == content:
            return "unchanged"
        path.write_text(content, encoding="utf-8")
        return "updated"
    path.write_text(content, encoding="utf-8")
    return "created"


_GENERATORS: dict[Target, Callable[[Profile, Path], list[GeneratedFile]]] = {}


def _ensure_registered() -> None:
    if _GENERATORS:
        return
    from nexus.cli.generators.agents_md import generate as agents_gen
    from nexus.cli.generators.claude_md import generate as claude_gen
    from nexus.cli.generators.cursor_rules import generate as cursor_gen
    from nexus.cli.generators.copilot import generate as copilot_gen
    from nexus.cli.generators.review_md import generate as review_gen
    _GENERATORS["agents_md"] = agents_gen
    _GENERATORS["claude"] = claude_gen
    _GENERATORS["cursor"] = cursor_gen
    _GENERATORS["copilot"] = copilot_gen
    _GENERATORS["devin-review"] = review_gen


def run_all(
    profile: Profile,
    project_root: Path,
    targets: Optional[list[str]] = None,
    *,
    dry_run: bool = False,
    force: bool = False,  # reserved; current generators always overwrite/upsert idempotently
) -> list[tuple[GeneratedFile, str]]:
    """Generate files for the given targets. Returns list of ``(GeneratedFile, action)``.

    ``action`` is one of ``'created' | 'updated' | 'unchanged' | 'inserted' | 'dry-run'``.
    ``targets=None`` means all targets in :data:`ALL_TARGETS`.
    """
    _ensure_registered()
    selected: list[Target] = list(targets) if targets else list(ALL_TARGETS)

    files: list[GeneratedFile] = []
    for t in selected:
        gen = _GENERATORS.get(t)  # type: ignore[arg-type]
        if gen is None:
            continue
        files.extend(gen(profile, project_root))

    results: list[tuple[GeneratedFile, str]] = []
    for f in files:
        if dry_run:
            results.append((f, "dry-run"))
            continue
        if f.mode == "overwrite":
            action = overwrite_file(f.path, f.content)
        else:
            action = upsert_managed_block(f.path, f.content, f.block_id)
        results.append((f, action))
    return results


__all__ = [
    "GeneratedFile",
    "WriteMode",
    "ALL_TARGETS",
    "begin_marker",
    "end_marker",
    "stamp",
    "upsert_managed_block",
    "overwrite_file",
    "run_all",
    "select_rules",
    "hash_profile",
]
