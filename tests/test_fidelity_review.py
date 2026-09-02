from __future__ import annotations

import json
from pathlib import Path

from paperbench_harbor.adapters.paperwrite_bench.converter import (
    PaperWriteBenchConversionConfig,
    convert_paperwrite_bench,
)
from paperbench_harbor.construction.core.opencode_agent import AgentRun
from paperbench_harbor.construction.core.review import ReviewVerdict
from paperbench_harbor.fidelity import review as review_module
from paperbench_harbor.fidelity.audit import run_fidelity_audit
from paperbench_harbor.fidelity.review import (
    DEFAULT_CONVERSION_REVIEWER_MODEL,
    prepare_conversion_review_dir,
    run_conversion_review,
)
from tests.test_paperwrite_bench_converter import _make_source


def _converted_sample(tmp_path: Path) -> tuple[Path, Path]:
    source = _make_source(tmp_path)
    output = tmp_path / "out"
    convert_paperwrite_bench(
        PaperWriteBenchConversionConfig(
            source=source,
            output_dir=output,
            overview="short",
            upstream_revision="deadbeef",
        )
    )
    return source / "paper_1", output / "pwb-0001"


def test_conversion_review_stages_only_upstream_and_writer_evidence(tmp_path: Path) -> None:
    paper_dir, task_dir = _converted_sample(tmp_path)
    staged = prepare_conversion_review_dir(paper_dir, task_dir, tmp_path / "review")

    assert sorted(path.name for path in staged.iterdir()) == ["task", "upstream"]
    assert (staged / "upstream" / "original" / "main.tex").is_file()
    assert (staged / "task" / "instruction.md").is_file()
    assert (staged / "task" / "task.toml").is_file()
    assert (staged / "task" / "materials" / "research_overview.md").is_file()
    assert not (staged / "task" / "solution").exists()
    assert not (staged / "task" / "tests").exists()


def test_conversion_review_runs_in_a_throwaway_directory(tmp_path: Path, monkeypatch) -> None:
    paper_dir, task_dir = _converted_sample(tmp_path)
    calls: list[dict] = []

    def fake_run_agent_session(**kwargs) -> AgentRun:
        calls.append(kwargs)
        workspace = Path(kwargs["workspace"])
        (workspace / "verdict.json").write_text(
            json.dumps({"ok": True, "reasoning": "Checked protocol and materials.", "concerns": []}),
            encoding="utf-8",
        )
        log_path = Path(kwargs["log_dir"]) / "paper_1.turn1.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("stub\n", encoding="utf-8")
        return AgentRun(
            paper_id="paper_1",
            turn=1,
            command=("opencode", "run"),
            returncode=0,
            log_path=log_path,
            started_at="2026-09-03T00:00:00+00:00",
            finished_at="2026-09-03T00:00:01+00:00",
        )

    monkeypatch.setattr(review_module, "run_agent_session", fake_run_agent_session)
    verdict = run_conversion_review(
        benchmark="PaperWrite-Bench",
        paper_id="paper_1",
        paper_dir=paper_dir,
        task_dir=task_dir,
        log_dir=tmp_path / "logs",
    )

    assert verdict.ok
    assert calls[0]["model"] == DEFAULT_CONVERSION_REVIEWER_MODEL
    assert not Path(calls[0]["workspace"]).is_relative_to(task_dir)
    assert (task_dir / "solution" / "private" / "main.tex").is_file()


def test_semantic_rejection_fails_the_task_audit(tmp_path: Path, monkeypatch) -> None:
    paper_dir, task_dir = _converted_sample(tmp_path)

    monkeypatch.setattr(
        "paperbench_harbor.fidelity.audit.run_conversion_review",
        lambda **_: ReviewVerdict(
            ok=False,
            reasoning="The instruction says a dense idea is public, but it is not.",
            concerns=["Correct the public/private protocol description."],
        ),
    )
    report = run_fidelity_audit(
        benchmark="PaperWrite-Bench",
        task_id="pwb-0001",
        upstream_paper_id="paper_1",
        upstream_root=paper_dir.parent,
        task_dir=task_dir,
        protocol="short",
        venue=None,
        semantic_review=True,
    )

    assert not report.ok
    assert report.semantic_reviewed
    assert report.semantic_verdict == {
        "ok": False,
        "reasoning": "The instruction says a dense idea is public, but it is not.",
        "concerns": ["Correct the public/private protocol description."],
    }
    assert any(error.startswith("semantic review failed") for error in report.errors)
