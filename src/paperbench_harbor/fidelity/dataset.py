"""Auditing a whole generated dataset, rather than one task at a time.

The per-task audit in :mod:`paperbench_harbor.fidelity.audit` needs a task id,
an upstream paper id and (for PaperWritingBench) a venue. All three are already
recorded in the generated `dataset-manifest.jsonl`, so walking a dataset is the
same loop for every benchmark -- it was written out three times in
`scripts/audit_fidelity.py`, differing only in the benchmark name it passed.

Determinism deliberately lives elsewhere. It is a property of the *converter*
(convert the same fixed input twice, get the same bytes), it costs two full
conversions to establish, and it says nothing about any individual task. The
standalone audit script still runs it; a converter that has just produced a
tree does not re-convert it twice to check.
"""

from __future__ import annotations

import json
from pathlib import Path

from paperbench_harbor.fidelity.audit import TaskReport, run_fidelity_audit


class DatasetAuditError(RuntimeError):
    """Raised when a dataset cannot be audited at all.

    Distinct from a failing audit: this means the tree is not in a shape the
    audit can even read, so there is no report to write.
    """


def load_dataset_manifest(dataset: Path) -> list[dict]:
    manifest = dataset / "dataset-manifest.jsonl"
    if not manifest.is_file():
        raise DatasetAuditError(f"dataset manifest not found: {manifest}")
    entries = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    if not entries:
        raise DatasetAuditError(f"dataset manifest is empty: {manifest}")
    return entries


def audit_dataset(
    *,
    benchmark: str,
    source: Path,
    dataset: Path,
    protocol: str,
    semantic_review: bool = False,
    reviewer_model: str | None = None,
) -> list[TaskReport]:
    """Run the per-task fidelity audit across one generated dataset.

    `venue` is read from the manifest entry rather than passed in: only
    PaperWritingBench records one, and reading it per entry is what lets this
    loop be shared instead of branching on the benchmark.
    """
    reports = []
    for entry in load_dataset_manifest(dataset):
        task_id = entry["task_id"]
        task_dir = dataset / task_id
        if not task_dir.is_dir():
            raise DatasetAuditError(f"task dir missing: {task_dir}")
        reports.append(
            run_fidelity_audit(
                benchmark=benchmark,
                task_id=task_id,
                upstream_paper_id=entry["upstream_paper_id"],
                upstream_root=source,
                task_dir=task_dir,
                protocol=protocol,
                venue=entry.get("venue"),
                semantic_review=semantic_review,
                reviewer_model=reviewer_model,
            )
        )
    return reports


def format_failures(reports: list[TaskReport], *, limit: int = 5) -> str:
    """A short operator-facing summary of what failed, for a CLI to print.

    Truncated on purpose. A conversion that breaks a shared invariant fails
    every task in the dataset, and printing 273 identical error lists buries
    the one fact the operator needs.
    """
    failed = [report for report in reports if not report.ok]
    if not failed:
        return ""
    lines = [f"fidelity audit failed for {len(failed)} of {len(reports)} task(s):"]
    for report in failed[:limit]:
        for error in report.errors[:3]:
            lines.append(f"  {report.task_id}: {error}")
        if len(report.errors) > 3:
            lines.append(f"  {report.task_id}: ... and {len(report.errors) - 3} more")
    if len(failed) > limit:
        lines.append(f"  ... and {len(failed) - limit} more task(s)")
    return "\n".join(lines)
