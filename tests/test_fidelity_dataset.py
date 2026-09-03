"""The audit as a step of conversion, rather than a command to remember.

`audit_dataset` is the loop `scripts/audit_fidelity.py` used to spell out three
times, and the loop the converter CLI now runs on its own success path. These
tests cover the loop and the CLI wiring; the per-task checks it drives are
covered by the converter and network-policy tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paperbench_harbor.cli import app
from paperbench_harbor.fidelity.audit import TaskReport
from paperbench_harbor.fidelity.dataset import (
    DatasetAuditError,
    audit_dataset,
    format_failures,
    load_dataset_manifest,
)
from tests.test_paperwrite_bench_converter import _make_source

runner = CliRunner()


def _write_manifest(dataset: Path, entries: list[dict]) -> None:
    dataset.mkdir(parents=True, exist_ok=True)
    (dataset / "dataset-manifest.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8"
    )


def test_missing_manifest_is_reported_as_unauditable(tmp_path: Path) -> None:
    with pytest.raises(DatasetAuditError, match="dataset manifest not found"):
        load_dataset_manifest(tmp_path)


def test_empty_manifest_is_reported_as_unauditable(tmp_path: Path) -> None:
    _write_manifest(tmp_path, [])
    with pytest.raises(DatasetAuditError, match="empty"):
        load_dataset_manifest(tmp_path)


def test_missing_task_dir_is_reported_as_unauditable(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    _write_manifest(dataset, [{"task_id": "pwb-0001", "upstream_paper_id": "paper_1"}])
    with pytest.raises(DatasetAuditError, match="task dir missing"):
        audit_dataset(
            benchmark="PaperWrite-Bench",
            source=tmp_path / "source",
            dataset=dataset,
            protocol="short",
        )


def test_venue_comes_from_the_manifest_entry(tmp_path: Path, monkeypatch) -> None:
    """Reading venue per entry is what lets one loop serve all three benchmarks."""
    dataset = tmp_path / "dataset"
    _write_manifest(
        dataset,
        [{"task_id": "pwbw-0001", "upstream_paper_id": "paper_1", "venue": "cvpr2025"}],
    )
    (dataset / "pwbw-0001").mkdir(parents=True)

    seen: dict = {}

    def _fake(**kwargs):
        seen.update(kwargs)
        return TaskReport(
            benchmark=kwargs["benchmark"],
            task_id=kwargs["task_id"],
            upstream_paper_id=kwargs["upstream_paper_id"],
            ok=True,
        )

    monkeypatch.setattr("paperbench_harbor.fidelity.dataset.run_fidelity_audit", _fake)
    audit_dataset(
        benchmark="PaperWritingBench",
        source=tmp_path / "source",
        dataset=dataset,
        protocol="sparse-plotoff",
    )
    assert seen["venue"] == "cvpr2025"


def test_dataset_audit_passes_an_explicit_review_log_directory(tmp_path: Path, monkeypatch) -> None:
    dataset = tmp_path / "dataset"
    _write_manifest(dataset, [{"task_id": "pwb-0001", "upstream_paper_id": "paper_1"}])
    (dataset / "pwb-0001").mkdir()

    seen: dict = {}

    def _fake(**kwargs):
        seen.update(kwargs)
        return TaskReport(
            benchmark=kwargs["benchmark"],
            task_id=kwargs["task_id"],
            upstream_paper_id=kwargs["upstream_paper_id"],
            ok=True,
        )

    monkeypatch.setattr("paperbench_harbor.fidelity.dataset.run_fidelity_audit", _fake)
    review_logs = tmp_path / "review-logs"
    audit_dataset(
        benchmark="PaperWrite-Bench",
        source=tmp_path / "source",
        dataset=dataset,
        protocol="short",
        review_log_dir=review_logs,
    )
    assert seen["review_log_dir"] == review_logs


def test_dataset_audit_can_bound_concurrency_without_reordering_reports(
    tmp_path: Path, monkeypatch
) -> None:
    dataset = tmp_path / "dataset"
    entries = [
        {"task_id": "pwb-0002", "upstream_paper_id": "paper_2"},
        {"task_id": "pwb-0001", "upstream_paper_id": "paper_1"},
    ]
    _write_manifest(dataset, entries)
    for entry in entries:
        (dataset / entry["task_id"]).mkdir()

    def _fake(**kwargs):
        return TaskReport(
            benchmark=kwargs["benchmark"],
            task_id=kwargs["task_id"],
            upstream_paper_id=kwargs["upstream_paper_id"],
            ok=True,
        )

    monkeypatch.setattr("paperbench_harbor.fidelity.dataset.run_fidelity_audit", _fake)
    reports = audit_dataset(
        benchmark="PaperWrite-Bench",
        source=tmp_path / "source",
        dataset=dataset,
        protocol="short",
        workers=2,
    )
    assert [report.task_id for report in reports] == ["pwb-0002", "pwb-0001"]
    with pytest.raises(ValueError, match="workers"):
        audit_dataset(
            benchmark="PaperWrite-Bench",
            source=tmp_path / "source",
            dataset=dataset,
            protocol="short",
            workers=0,
        )


def _report(task_id: str, errors: list[str]) -> TaskReport:
    return TaskReport(
        benchmark="PaperWrite-Bench",
        task_id=task_id,
        upstream_paper_id="paper_1",
        ok=not errors,
        errors=errors,
    )


def test_format_failures_is_empty_when_everything_passed() -> None:
    assert format_failures([_report("pwb-0001", [])]) == ""


def test_format_failures_truncates_a_dataset_wide_failure() -> None:
    reports = [_report(f"pwb-{i:04d}", ["content mismatch"]) for i in range(1, 21)]
    text = format_failures(reports, limit=2)
    assert "failed for 20 of 20 task(s)" in text
    assert "and 18 more task(s)" in text
    assert text.count("content mismatch") == 2


def test_format_failures_truncates_a_long_error_list() -> None:
    text = format_failures([_report("pwb-0001", [f"error {i}" for i in range(10)])])
    assert "and 7 more" in text


def test_conversion_audits_by_default(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    result = runner.invoke(
        app,
        [
            "paperwrite-bench",
            "--source", str(source),
            "--output-dir", str(tmp_path / "out"),
            "--upstream-revision", "deadbeef",
            "--no-semantic-review",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Fidelity audit passed" in result.output


def test_conversion_enables_semantic_review_by_default(tmp_path: Path, monkeypatch) -> None:
    source = _make_source(tmp_path)
    seen: dict = {}

    def _fake(**kwargs):
        seen.update(kwargs)
        return [_report("pwb-0001", [])]

    monkeypatch.setattr("paperbench_harbor.cli.audit_dataset", _fake)
    result = runner.invoke(
        app,
        [
            "paperwrite-bench",
            "--source", str(source),
            "--output-dir", str(tmp_path / "out"),
            "--upstream-revision", "deadbeef",
        ],
    )
    assert result.exit_code == 0, result.output
    assert seen["semantic_review"] is True


def test_no_audit_skips_it(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    result = runner.invoke(
        app,
        [
            "paperwrite-bench",
            "--source", str(source),
            "--output-dir", str(tmp_path / "out"),
            "--upstream-revision", "deadbeef",
            "--no-audit",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Fidelity audit skipped by explicit --no-audit." in result.output


def test_conversion_fails_when_the_audit_fails(tmp_path: Path, monkeypatch) -> None:
    """The point of the wiring: a bad conversion must not exit 0."""
    source = _make_source(tmp_path)
    monkeypatch.setattr(
        "paperbench_harbor.cli.audit_dataset",
        lambda **_: [_report("pwb-0001", ["content mismatch: environment/x"])],
    )
    result = runner.invoke(
        app,
        [
            "paperwrite-bench",
            "--source", str(source),
            "--output-dir", str(tmp_path / "out"),
            "--upstream-revision", "deadbeef",
        ],
    )
    assert result.exit_code == 1
    assert "content mismatch" in result.output
