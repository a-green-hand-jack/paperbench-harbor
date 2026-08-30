"""Fidelity audit: verify Harbor tasks against a fixed upstream source tree.

The audit checks, per task:

1. writer-visible files match their declared upstream sources byte-for-byte
   (SHA-256) for content-preserving transforms;
2. every writer-visible file is either a declared content-preserving copy or a
   declared generated/vendor artifact (no undeclared content);
3. verifier-only private copies are byte-identical to their upstream sources
   and none of that content appears in the writer environment;
4. task contract fields (network policy, venue, protocol, compile entrypoint)
   match the current specification.

Dataset-level determinism (repeated conversion produces an identical tree,
manifest, and hashes) is handled by the CLI, which converts the full fixed
input twice into scratch directories and compares digests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paperbench_harbor.common.audit import audit_forbidden_names
from paperbench_harbor.fidelity.transforms import (
    KIND_COPY,
    KIND_MOVE,
    KIND_RENAME,
    FileTransform,
    classify_generated_vendor,
    pwb_verifier_entries,
    pwb_writer_transforms,
    pwbw_verifier_entries,
    pwbw_writer_transforms,
    sha256,
)


class FidelityError(RuntimeError):
    """Raised when a fidelity check fails."""


@dataclass
class TaskReport:
    benchmark: str
    task_id: str
    upstream_paper_id: str
    ok: bool
    errors: list[str] = field(default_factory=list)
    writer_files_checked: int = 0
    writer_hashes_matched: int = 0
    verifier_entries_checked: int = 0
    contract_checks: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark": self.benchmark,
            "task_id": self.task_id,
            "upstream_paper_id": self.upstream_paper_id,
            "ok": self.ok,
            "errors": self.errors,
            "writer_files_checked": self.writer_files_checked,
            "writer_hashes_matched": self.writer_hashes_matched,
            "verifier_entries_checked": self.verifier_entries_checked,
            "contract_checks": self.contract_checks,
            "notes": self.notes,
        }


def _writer_visible_files(task_dir: Path) -> list[str]:
    root = task_dir / "environment"
    if not root.is_dir():
        return []
    return sorted(
        f"environment/{path.relative_to(root).as_posix()}"
        for path in root.rglob("*")
        if path.is_file()
    )


def _content_match(left: Path, right: Path, rel: str, report: TaskReport) -> None:
    if not left.is_file():
        report.errors.append(f"declared source missing: {left}")
        return
    if not right.is_file():
        report.errors.append(f"declared target missing: {right} ({rel})")
        return
    if sha256(left) != sha256(right):
        report.errors.append(f"content mismatch: {rel} (source={left})")
    else:
        report.writer_hashes_matched += 1


def _audit_writer_surface(
    task_dir: Path,
    upstream_root: Path,
    benchmark: str,
    paper_id: str,
    overview_or_protocol: str,
    venue: str | None,
    report: TaskReport,
) -> None:
    """Verify every writer-visible file against a declared transform."""
    if benchmark == "PaperWrite-Bench":
        transforms = pwb_writer_transforms(upstream_root, paper_id, task_dir, overview_or_protocol)
    else:
        assert venue is not None
        transforms = pwbw_writer_transforms(upstream_root, paper_id, task_dir, venue)

    declared: dict[str, FileTransform] = {}
    for transform in transforms:
        declared[transform.target] = transform

    actual = _writer_visible_files(task_dir)
    for rel in actual:
        transform = declared.get(rel)
        if transform is None and classify_generated_vendor(rel):
            report.notes.append(f"vendor/generated: {rel}")
            continue
        if transform is None:
            report.errors.append(f"undeclared writer-visible file: {rel}")
            continue
        report.writer_files_checked += 1
        if transform.kind in (KIND_COPY, KIND_RENAME, KIND_MOVE):
            if transform.source is None:
                report.errors.append(f"content-preserving transform without source: {rel}")
                continue
            _content_match(upstream_root / transform.source, task_dir / rel, rel, report)
        else:
            report.notes.append(f"{transform.kind}: {rel} ({transform.note})")

    # Every declared content-preserving target must exist on disk.
    for target, transform in declared.items():
        if transform.kind in (KIND_COPY, KIND_RENAME, KIND_MOVE) and not (task_dir / target).is_file():
            report.errors.append(f"declared target missing on disk: {target}")


def _audit_verifier(
    task_dir: Path,
    upstream_root: Path,
    benchmark: str,
    paper_id: str,
    overview_or_protocol: str,
    venue: str | None,
    report: TaskReport,
) -> None:
    """Verify private copies are byte-identical and leak nothing to the writer."""
    if benchmark == "PaperWrite-Bench":
        entries = pwb_verifier_entries(upstream_root, paper_id, task_dir, overview_or_protocol)
    else:
        assert venue is not None
        entries = pwbw_verifier_entries(upstream_root, paper_id, task_dir, venue)

    for entry in entries:
        source = upstream_root / entry.upstream
        for target in entry.targets:
            report.verifier_entries_checked += 1
            if not source.is_file():
                report.errors.append(f"verifier source missing: {source}")
                continue
            if not (task_dir / target).is_file():
                report.errors.append(f"verifier target missing: {target}")
                continue
            if sha256(source) != sha256(task_dir / target):
                report.errors.append(f"verifier content mismatch: {entry.upstream} -> {target}")

    # Leakage: writer environment must not contain any verifier-only content.
    env_files = _writer_visible_files(task_dir)
    env_hashes = {sha256(task_dir / rel) for rel in env_files}
    for entry in entries:
        if entry.expected_in_writer:
            continue
        source = upstream_root / entry.upstream
        if not source.is_file():
            continue
        if sha256(source) in env_hashes:
            report.errors.append(
                f"verifier-only content leaked into writer environment: {entry.upstream}"
            )

    # Forbidden-name check as a second, independent layer. It must mirror the
    # converter's exemptions: upstream PWB code repositories legitimately
    # contain files named like config.yaml, so materials/code/** is exempt.
    forbidden = {"main.tex", "main.pdf", "config.yaml", "eval_points.json", "source_manifest.json"}
    if benchmark == "PaperWritingBench":
        forbidden.add("idea_dense.md")
    try:
        audit_forbidden_names(
            task_dir / "environment",
            forbidden,
            ignore_globs=("materials/code/**",) if benchmark == "PaperWrite-Bench" else (),
        )
    except RuntimeError as exc:  # LeakageError
        report.errors.append(str(exc))


def _audit_contract(
    task_dir: Path,
    report: TaskReport,
) -> None:
    """Verify task contract fields against the current specification.

    The `protocol` / `venue` mapping is recorded in the dataset-level manifest,
    not in task.toml, so that mapping is checked by the CLI's mapping stage
    rather than here. Here we verify the fields task.toml and instruction.md
    actually declare.
    """
    task_toml = task_dir / "task.toml"
    if not task_toml.is_file():
        report.errors.append("task.toml missing")
        return
    text = task_toml.read_text(encoding="utf-8", errors="replace")

    # Network policy: current spec is allow_internet = true for both datasets.
    checks: list[tuple[str, bool]] = [
        ("allow_internet = true", "allow_internet = true" in text),
        ('environment_mode = "separate"', 'environment_mode = "separate"' in text),
    ]
    for name, passed in checks:
        report.contract_checks += 1
        if not passed:
            report.errors.append(f"contract check failed: {name}")

    instruction = task_dir / "instruction.md"
    if instruction.is_file():
        itext = instruction.read_text(encoding="utf-8", errors="replace")
        entry_checks = [
            ("main.tex entry", "main.tex" in itext),
            ("references.bib entry", "references.bib" in itext),
        ]
        for name, passed in entry_checks:
            report.contract_checks += 1
            if not passed:
                report.errors.append(f"instruction contract failed: {name}")


def run_fidelity_audit(
    *,
    benchmark: str,
    task_id: str,
    upstream_paper_id: str,
    upstream_root: Path,
    task_dir: Path,
    protocol: str,
    venue: str | None,
) -> TaskReport:
    """Run the full fidelity audit for a single task."""
    report = TaskReport(
        benchmark=benchmark,
        task_id=task_id,
        upstream_paper_id=upstream_paper_id,
        ok=True,
    )

    if benchmark == "PaperWrite-Bench":
        _audit_writer_surface(task_dir, upstream_root, benchmark, upstream_paper_id, protocol, None, report)
        _audit_verifier(task_dir, upstream_root, benchmark, upstream_paper_id, protocol, None, report)
        _audit_contract(task_dir, report)
    else:
        assert venue is not None
        _audit_writer_surface(task_dir, upstream_root, benchmark, upstream_paper_id, protocol, venue, report)
        _audit_verifier(task_dir, upstream_root, benchmark, upstream_paper_id, protocol, venue, report)
        _audit_contract(task_dir, report)

    report.ok = not report.errors
    return report


def summarize(reports: list[TaskReport]) -> dict[str, Any]:
    """Build an overall summary across tasks."""
    total = len(reports)
    passed = sum(1 for report in reports if report.ok)
    return {
        "total_tasks": total,
        "passed_tasks": passed,
        "failed_tasks": total - passed,
        "writer_files_checked": sum(r.writer_files_checked for r in reports),
        "writer_hashes_matched": sum(r.writer_hashes_matched for r in reports),
        "verifier_entries_checked": sum(r.verifier_entries_checked for r in reports),
        "contract_checks": sum(r.contract_checks for r in reports),
        "failed_tasks_detail": [
            {"task_id": r.task_id, "errors": r.errors} for r in reports if not r.ok
        ],
    }
