"""The non-benchmark-specific half of a Harbor conversion.

Adapters own the parts that are facts about their upstream benchmark: parsing an
unusual metadata file, normalising a known malformed material, or selecting a
venue kit. This module owns the mechanical task lifecycle shared by every
adapter: stable task ids, task directory scaffolding, strict template rendering,
and deterministic dataset-manifest updates.

Keeping these operations here is intentionally more modest than forcing every
adapter into one giant callback object. A generic converter should remove
duplicated plumbing without turning real benchmark differences into opaque
configuration language.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from paperbench_harbor.common.manifest import sha256_file


@dataclass(frozen=True)
class TaskDirectories:
    """The standard Harbor task directories created for one conversion."""

    task: Path
    environment: Path
    solution: Path
    solution_private: Path
    tests: Path
    tests_private: Path


def source_tree_sha256(source_root: Path) -> str:
    """Return a stable digest of every input byte an adapter can consume."""

    if not source_root.is_dir():
        raise FileNotFoundError(f"source directory not found: {source_root}")
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in source_root.rglob("*") if candidate.is_file()):
        digest.update(path.relative_to(source_root).as_posix().encode())
        digest.update(b"\0")
        digest.update(sha256_file(path).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def assert_source_tree_unchanged(source_root: Path, expected_digest: str) -> None:
    """Reject a conversion whose input changed before its task bytes were complete."""

    actual_digest = source_tree_sha256(source_root)
    if actual_digest != expected_digest:
        raise RuntimeError(
            "source tree changed during conversion; discard the generated output and retry from "
            "an immutable input snapshot"
        )


def task_id_for(prefix: str, index: int) -> str:
    """Return the stable, one-based task id used in dataset manifests."""

    if not prefix:
        raise ValueError("task id prefix must be non-empty")
    if index < 1:
        raise ValueError("task index must be one-based")
    return f"{prefix}-{index:04d}"


def prepare_task_output(task_dir: Path, *, overwrite: bool) -> bool:
    """Prepare one task location and say whether conversion should proceed.

    Existing tasks are deliberately skipped unless the caller explicitly opts
    into replacement. The function is shared so every adapter has the same
    overwrite behaviour and no adapter quietly accumulates stale generated
    files from an earlier conversion.
    """

    if not task_dir.exists():
        return True
    if not overwrite:
        return False
    shutil.rmtree(task_dir)
    return True


def prepare_task_directories(task_dir: Path) -> TaskDirectories:
    """Create the standard task skeleton, including an empty environment texmf.

    The shared environment Dockerfile always copies ``texmf/``. Keeping a
    tracked sentinel when an upstream sample has no additional styles makes the
    generated Dockerfile valid without giving any adapter a special case.
    """

    environment = task_dir / "environment"
    solution = task_dir / "solution"
    solution_private = solution / "private"
    tests = task_dir / "tests"
    tests_private = tests / "private"
    for path in (environment, solution, solution_private, tests, tests_private):
        path.mkdir(parents=True, exist_ok=True)
    texmf = environment / "texmf"
    texmf.mkdir(exist_ok=True)
    (texmf / ".keep").touch()
    return TaskDirectories(
        task=task_dir,
        environment=environment,
        solution=solution,
        solution_private=solution_private,
        tests=tests,
        tests_private=tests_private,
    )


def create_template_environment(templates_dir: Path) -> Environment:
    """Load Harbor task templates with the same strict rendering contract."""

    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )


def render_templates(
    environment: Environment,
    task_dir: Path,
    *,
    templates: Mapping[str, str],
    context: Mapping[str, object],
) -> None:
    """Render named templates to task-relative destinations deterministically."""

    for target, template_name in templates.items():
        destination = task_dir / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            environment.get_template(template_name).render(**context), encoding="utf-8"
        )


def load_dataset_manifest(path: Path) -> dict[tuple[str, str], dict]:
    """Read the keyed manifest so overwrite updates preserve other samples."""

    entries: dict[tuple[str, str], dict] = {}
    if not path.is_file():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        entries[(entry["task_id"], entry["upstream_paper_id"])] = entry
    return entries


def write_dataset_manifest(path: Path, entries: Mapping[tuple[str, str], dict]) -> None:
    """Write a stable manifest ordering independent of conversion order."""

    path.write_text(
        "".join(
            json.dumps(entry, sort_keys=True) + "\n"
            for _, entry in sorted(entries.items())
        ),
        encoding="utf-8",
    )
