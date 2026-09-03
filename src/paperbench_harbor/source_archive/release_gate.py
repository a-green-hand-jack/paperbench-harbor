"""The non-bypassable pre-upload gate for a task release and source archive."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from paperbench_harbor.source_archive.registry import (
    SourceArchiveError,
    load_plan,
    validate_source_archive,
)


def _pinned_revision(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def _summary(path: Path) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SourceArchiveError(f"fidelity audit summary not found: {path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise SourceArchiveError(f"cannot read fidelity audit summary {path}: {error}") from error
    if not isinstance(record, dict):
        raise SourceArchiveError(f"fidelity audit summary must be an object: {path}")
    return record


def _require_equal(record: dict[str, Any], field: str, expected: object, *, config: str) -> None:
    if record.get(field) != expected:
        raise SourceArchiveError(
            f"fidelity audit for {config} has {field}={record.get(field)!r}, expected {expected!r}"
        )


def validate_release_provenance(
    *,
    plan_path: Path,
    dataset_root: Path,
    archive_root: Path,
    audit_summaries: dict[str, Path],
) -> dict[str, Any]:
    """Require full deterministic semantic evidence before a release can upload.

    The gate intentionally consumes report files rather than calling a model or
    a converter itself.  That keeps the evidence attributable to the exact
    audited tree and makes it impossible for an archive-only refresh to alter a
    runnable task tree.
    """
    plan = load_plan(plan_path)
    archive = validate_source_archive(
        plan_path=plan_path,
        dataset_root=dataset_root,
        archive_root=archive_root,
    )
    expected_counts: dict[str, int] = {}
    for task in plan["tasks"]:
        expected_counts[task["config"]] = expected_counts.get(task["config"], 0) + 1
    if set(audit_summaries) != set(expected_counts):
        raise SourceArchiveError(
            "fidelity audit summaries must cover exactly the archive plan configs; "
            f"expected {sorted(expected_counts)}, got {sorted(audit_summaries)}"
        )

    for config, path in sorted(audit_summaries.items()):
        summary = _summary(path)
        total = expected_counts[config]
        _require_equal(summary, "total_tasks", total, config=config)
        _require_equal(summary, "passed_tasks", total, config=config)
        _require_equal(summary, "failed_tasks", 0, config=config)
        _require_equal(summary, "determinism_ok", True, config=config)
        _require_equal(summary, "semantic_reviews", total, config=config)
        _require_equal(summary, "semantic_review_failures", 0, config=config)
        evidence = summary.get("evidence")
        if not isinstance(evidence, dict):
            raise SourceArchiveError(f"fidelity audit for {config} has no version-bound evidence")
        _require_equal(evidence, "semantic_review_required", True, config=config)
        # An audit can be rerun by a newer fixed audit implementation against
        # an older immutable release. Its code revision must be recorded, but
        # it need not equal the converter revision that originally built the
        # task tree (which the archive plan records separately).
        if not _pinned_revision(evidence.get("converter_revision")):
            raise SourceArchiveError(f"fidelity audit for {config} has no pinned audit revision")
        if (
            not isinstance(evidence.get("upstream_revision"), str)
            or not evidence["upstream_revision"]
        ):
            raise SourceArchiveError(f"fidelity audit for {config} has no pinned upstream revision")
        if (
            not isinstance(evidence.get("dataset_tree_sha256"), str)
            or len(evidence["dataset_tree_sha256"]) != 64
        ):
            raise SourceArchiveError(f"fidelity audit for {config} has no dataset tree digest")

    return {**archive, "release_gate": "passed", "configs": sorted(expected_counts)}
