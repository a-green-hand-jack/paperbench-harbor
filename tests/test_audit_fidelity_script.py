from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from paperbench_harbor.fidelity.audit import TaskReport
from scripts import audit_fidelity


def test_audit_report_captures_pinned_and_semantic_evidence(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    source = tmp_path / "source"
    dataset = tmp_path / "dataset"
    source.mkdir()
    dataset.mkdir()
    (source / "paper.txt").write_text("upstream", encoding="utf-8")
    (dataset / "task.txt").write_text("task", encoding="utf-8")
    args = argparse.Namespace(
        output=tmp_path / "report",
        source=source,
        dataset=dataset,
        upstream_revision="upstream-rev",
        semantic_review=True,
        reviewer_model="reviewer/model",
    )
    report = TaskReport(
        benchmark="PaperWrite-Bench",
        task_id="pwb-0001",
        upstream_paper_id="paper-1",
        ok=True,
        semantic_reviewed=True,
        semantic_verdict={"ok": True, "reasoning": "checked", "concerns": []},
    )
    monkeypatch.setattr(audit_fidelity, "_code_revision", lambda: "converter-rev")

    result = audit_fidelity._write_reports(
        args,
        [report],
        lambda _args, summary: summary.update(determinism_ok=True),
    )

    assert result == 0
    summary = json.loads((args.output / "summary.json").read_text(encoding="utf-8"))
    assert summary["semantic_reviews"] == 1
    assert summary["evidence"] == {
        "schema_version": 1,
        "benchmark": "PaperWrite-Bench",
        "upstream_revision": "upstream-rev",
        "upstream_tree_sha256": audit_fidelity._tree_digest(source),
        "dataset_tree_sha256": audit_fidelity._tree_digest(dataset),
        "converter_revision": "converter-rev",
        "semantic_review_required": True,
        "reviewer_model": "reviewer/model",
    }
    assert '"semantic_reviews": 1' in capsys.readouterr().out


def test_audit_discards_evidence_when_the_source_changes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dataset = tmp_path / "dataset"
    source.mkdir()
    dataset.mkdir()
    (source / "paper.txt").write_text("before", encoding="utf-8")
    args = argparse.Namespace(
        output=tmp_path / "report",
        source=source,
        dataset=dataset,
        upstream_revision="upstream-rev",
        semantic_review=True,
        reviewer_model="reviewer/model",
    )
    report = TaskReport(
        benchmark="PaperWrite-Bench",
        task_id="pwb-0001",
        upstream_paper_id="paper-1",
        ok=True,
    )
    original_digest = audit_fidelity._tree_digest(source)

    def mutate_source(_args, summary) -> None:
        (source / "paper.txt").write_text("after", encoding="utf-8")
        summary.update(determinism_ok=True)

    with pytest.raises(RuntimeError, match="source tree changed during fidelity audit"):
        audit_fidelity._write_reports(
            args,
            [report],
            mutate_source,
            source_tree_sha256=original_digest,
        )
    assert not (args.output / "pwb-0001.json").exists()
    assert not (args.output / "summary.json").exists()
