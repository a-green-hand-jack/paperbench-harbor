from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperbench_harbor.adapters.paperwrite_bench.converter import (
    PaperWriteBenchConversionConfig,
    convert_paperwrite_bench,
)
from paperbench_harbor.adapters.paperwritingbench.converter import (
    PaperWritingBenchConversionConfig,
    convert_paperwritingbench,
)
from paperbench_harbor.fidelity.audit import run_fidelity_audit, summarize

PWB_PAPERS = ("paper_1", "paper_2", "paper_3")


def _make_pwb_paper(source: Path, paper_id: str) -> None:
    paper_dir = source / paper_id
    original = paper_dir / "original"
    resources = paper_dir / "resources"
    original.mkdir(parents=True)
    resources.mkdir(parents=True)
    (original / "config.yaml").write_text(
        "type: method\nnum_page: 9\ncolumn: 2column\nconference: NeurIPS25\n", encoding="utf-8"
    )
    (original / "main.tex").write_text("\\documentclass{article}\\begin{document}GT\\end{document}", encoding="utf-8")
    (original / "main.pdf").write_bytes(b"%PDF-1.4 fake")
    (resources / "template.tex").write_text("\\documentclass{article}\\begin{document}\\end{document}", encoding="utf-8")
    (resources / "research_overview_short.md").write_text("# Overview short\n", encoding="utf-8")
    (resources / "research_overview_long.md").write_text("# Overview long\n", encoding="utf-8")
    (resources / "references.bib").write_text("@article{key1, title={T}}\n", encoding="utf-8")
    (resources / "figure_summary.txt").write_text("figures/a.png: A\n", encoding="utf-8")
    (resources / "table_summary.txt").write_text("tables/a.tex: A\n", encoding="utf-8")
    (resources / "eval_points.json").write_text('{"sections": []}', encoding="utf-8")
    (resources / "figures").mkdir()
    (resources / "figures" / "a.png").write_bytes(b"\x89PNG fake")
    (resources / "tables").mkdir()
    (resources / "tables" / "a.tex").write_text("\\begin{table}\\end{table}\n", encoding="utf-8")
    (resources / "code").mkdir()
    (resources / "code" / "x.py").write_text("x = 1\n", encoding="utf-8")


def _make_pwbw_paper(source: Path, venue: str, paper_id: str) -> None:
    paper_dir = source / venue / "papers" / paper_id
    raw = paper_dir / "raw_materials"
    raw.mkdir(parents=True)
    (paper_dir / f"{paper_id}.pdf").write_bytes(b"%PDF-1.4 fake")
    (raw / "idea_sparse.md").write_text("# idea sparse\n", encoding="utf-8")
    (raw / "idea_dense.md").write_text("# idea dense\n", encoding="utf-8")
    (raw / "experimental_log.md").write_text("# log\n", encoding="utf-8")
    (raw / "original_paper_gt_citations_gpt-5-2025-08-07.json").write_text('{"cites": []}', encoding="utf-8")
    figures = raw / "figures"
    figures.mkdir()
    (figures / "figure_1.png").write_bytes(b"\x89PNG figure1")
    (figures / "info.json").write_text('{"figures": 1}', encoding="utf-8")


@pytest.fixture()
def pwb_source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    for paper_id in PWB_PAPERS:
        _make_pwb_paper(source, paper_id)
    return source


@pytest.fixture()
def pwbw_source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    _make_pwbw_paper(source, "cvpr2025", "cvpr2025_0b62029e18")
    _make_pwbw_paper(source, "iclr2025", "iclr2025_ffb6b76b86")
    return source


def _pwb_dataset(pwb_source: Path, tmp_path: Path, revision: str = "test-rev") -> Path:
    out = tmp_path / "out-pwb"
    convert_paperwrite_bench(
        PaperWriteBenchConversionConfig(
            source=pwb_source, output_dir=out, overview="short", upstream_revision=revision
        )
    )
    return out


def _pwbw_dataset(pwbw_source: Path, tmp_path: Path, revision: str = "test-rev") -> Path:
    out = tmp_path / "out-pwbw"
    convert_paperwritingbench(
        PaperWritingBenchConversionConfig(
            source=pwbw_source, output_dir=out, protocol="sparse-plotoff", upstream_revision=revision
        )
    )
    return out


def test_pwb_manifest_records_revision(pwb_source: Path, tmp_path: Path) -> None:
    out = _pwb_dataset(pwb_source, tmp_path)
    lines = (out / "dataset-manifest.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    for line in lines:
        entry = json.loads(line)
        assert entry["upstream_revision"] == "test-rev"
        assert entry["overview"] == "short"


def test_pwbw_manifest_records_revision(pwbw_source: Path, tmp_path: Path) -> None:
    out = _pwbw_dataset(pwbw_source, tmp_path)
    lines = (out / "dataset-manifest.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        entry = json.loads(line)
        assert entry["upstream_revision"] == "test-rev"
        assert entry["protocol"] == "sparse-plotoff"


def test_pwb_fidelity_audit_passes(pwb_source: Path, tmp_path: Path) -> None:
    out = _pwb_dataset(pwb_source, tmp_path)
    for index, paper_id in enumerate(PWB_PAPERS, start=1):
        task_id = f"pwb-{index:04d}"
        report = run_fidelity_audit(
            benchmark="PaperWrite-Bench",
            task_id=task_id,
            upstream_paper_id=paper_id,
            upstream_root=pwb_source,
            task_dir=out / task_id,
            protocol="short",
            venue=None,
        )
        assert report.ok, report.errors
        assert report.writer_hashes_matched > 0
        assert report.verifier_entries_checked > 0
        assert report.contract_checks >= 2


def test_pwbw_fidelity_audit_passes(pwbw_source: Path, tmp_path: Path) -> None:
    out = _pwbw_dataset(pwbw_source, tmp_path)
    cases = [
        ("pwbw-0001", "cvpr2025_0b62029e18", "cvpr2025"),
        ("pwbw-0002", "iclr2025_ffb6b76b86", "iclr2025"),
    ]
    for task_id, paper_id, venue in cases:
        report = run_fidelity_audit(
            benchmark="PaperWritingBench",
            task_id=task_id,
            upstream_paper_id=paper_id,
            upstream_root=pwbw_source,
            task_dir=out / task_id,
            protocol="sparse-plotoff",
            venue=venue,
        )
        assert report.ok, report.errors
        assert report.writer_hashes_matched > 0
        assert report.verifier_entries_checked > 0


def test_pwb_audit_detects_content_edit(pwb_source: Path, tmp_path: Path) -> None:
    out = _pwb_dataset(pwb_source, tmp_path)
    task_dir = out / "pwb-0001"
    (task_dir / "environment" / "materials" / "references.bib").write_text(
        "@article{other, title={X}}\n", encoding="utf-8"
    )
    report = run_fidelity_audit(
        benchmark="PaperWrite-Bench",
        task_id="pwb-0001",
        upstream_paper_id="paper_1",
        upstream_root=pwb_source,
        task_dir=task_dir,
        protocol="short",
        venue=None,
    )
    assert not report.ok
    assert any("content mismatch" in e for e in report.errors)


def test_pwb_audit_detects_undeclared_writer_file(pwb_source: Path, tmp_path: Path) -> None:
    out = _pwb_dataset(pwb_source, tmp_path)
    task_dir = out / "pwb-0001"
    (task_dir / "environment" / "materials" / "sneaky.txt").write_text("boom", encoding="utf-8")
    report = run_fidelity_audit(
        benchmark="PaperWrite-Bench",
        task_id="pwb-0001",
        upstream_paper_id="paper_1",
        upstream_root=pwb_source,
        task_dir=task_dir,
        protocol="short",
        venue=None,
    )
    assert not report.ok
    assert any("undeclared writer-visible file" in e for e in report.errors)


def test_pwb_audit_detects_verifier_leakage(pwb_source: Path, tmp_path: Path) -> None:
    out = _pwb_dataset(pwb_source, tmp_path)
    task_dir = out / "pwb-0001"
    # Plant ground-truth content into the writer environment.
    gt = (pwb_source / "paper_1" / "original" / "main.tex").read_bytes()
    (task_dir / "environment" / "materials" / "copy_of_gt.tex").write_bytes(gt)
    report = run_fidelity_audit(
        benchmark="PaperWrite-Bench",
        task_id="pwb-0001",
        upstream_paper_id="paper_1",
        upstream_root=pwb_source,
        task_dir=task_dir,
        protocol="short",
        venue=None,
    )
    assert not report.ok
    assert any("leaked into writer environment" in e for e in report.errors)


def test_pwb_audit_ignores_generated_vendor_bytes_matching_private_source(
    pwb_source: Path, tmp_path: Path
) -> None:
    out = _pwb_dataset(pwb_source, tmp_path)
    task_dir = out / "pwb-0001"
    # A generated style can happen to have the same bytes as a private source;
    # it is not a writer-visible copy and must not become a false leakage finding.
    generated = task_dir / "environment" / "texmf" / "coincidental.sty"
    generated.write_bytes((pwb_source / "paper_1" / "original" / "main.tex").read_bytes())

    report = run_fidelity_audit(
        benchmark="PaperWrite-Bench",
        task_id="pwb-0001",
        upstream_paper_id="paper_1",
        upstream_root=pwb_source,
        task_dir=task_dir,
        protocol="short",
        venue=None,
    )

    assert report.ok, report.errors


def test_summarize_reports_failures() -> None:
    from paperbench_harbor.fidelity.audit import TaskReport

    ok = TaskReport(benchmark="PaperWrite-Bench", task_id="pwb-0001", upstream_paper_id="p1", ok=True)
    bad = TaskReport(benchmark="PaperWrite-Bench", task_id="pwb-0002", upstream_paper_id="p2", ok=False)
    bad.errors.append("boom")
    summary = summarize([ok, bad])
    assert summary["total_tasks"] == 2
    assert summary["passed_tasks"] == 1
    assert summary["failed_tasks"] == 1
    assert summary["failed_tasks_detail"][0]["task_id"] == "pwb-0002"
