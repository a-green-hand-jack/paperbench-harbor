"""The reviewer is an LLM, so everything it returns is treated as hostile input.

Stage 3's whole value is that it catches what the structural gate cannot see.
That value is entirely undone by two failure modes, and both are tested here
rather than trusted:

* **A verdict that was never really read.** If a malformed, truncated or
  wrong-typed `verdict.json` could be coerced into `ok: true`, review would
  silently degrade into a no-op that costs a model call per paper. Every shape
  violation below must raise.
* **A reviewer that can edit its own exhibit.** `opencode run --auto` grants
  unsupervised writes to `--dir`. The tests assert the agent is pointed at a
  throwaway copy and that the live sample is untouched, because a reviewer that
  can fix what it dislikes reports on a paper that no longer exists.

Nothing here invokes `opencode` or the network: `run_agent_session` is stubbed,
so the suite runs on a laptop with no build host.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperbench_harbor.adapters.paperwrite_bench.converter import OVERVIEW_FILENAMES
from paperbench_harbor.construction.core import review as review_module
from paperbench_harbor.construction.core.opencode_agent import (
    DEFAULT_MODEL,
    AgentRun,
)
from paperbench_harbor.construction.core.review import (
    DEFAULT_REVIEWER_MODEL,
    ReviewError,
    ReviewVerdict,
    build_review_prompt,
    default_reviewer_model,
    parse_verdict,
    prepare_review_dir,
    run_review,
    write_review_record,
)
from paperbench_harbor.construction.core.validate import ValidationReport
from paperbench_harbor.construction.lifesci_paperrecon.papers import APPROVED_BY_ID
from paperbench_harbor.construction.lifesci_paperrecon.plugin import LIFESCI_PLUGIN

SPEC = APPROVED_BY_ID["paper_1"]
SHORT = OVERVIEW_FILENAMES["short"]
LONG = OVERVIEW_FILENAMES["long"]


def _write_verdict(directory: Path, payload: object) -> Path:
    path = directory / "verdict.json"
    text = payload if isinstance(payload, str) else json.dumps(payload)
    path.write_text(text, encoding="utf-8")
    return path


def _built_sample(root: Path) -> Path:
    """A minimal already-built sample: only the files review is allowed to read."""

    paper_dir = root / "paper_1"
    (paper_dir / "original").mkdir(parents=True)
    (paper_dir / "resources").mkdir(parents=True)
    (paper_dir / "original" / "main.tex").write_text("\\section{Results}\n", encoding="utf-8")
    (paper_dir / "original" / "provenance.json").write_text("{}", encoding="utf-8")
    (paper_dir / "resources" / SHORT).write_text("# Title\n\nBEAGLE\n", encoding="utf-8")
    (paper_dir / "resources" / LONG).write_text("# Title\n\nBEAGLE, at length\n", encoding="utf-8")
    (paper_dir / "resources" / "template.tex").write_text("\\documentclass{article}", encoding="utf-8")
    return paper_dir


# --------------------------------------------------------------------------- #
# verdict parsing: shape is checked, never assumed
# --------------------------------------------------------------------------- #


def test_parses_a_passing_verdict(tmp_path: Path) -> None:
    path = _write_verdict(
        tmp_path,
        {"ok": True, "reasoning": "  Checked the 11x speedup claim.  ", "concerns": []},
    )
    verdict = parse_verdict(path)
    assert verdict.ok is True
    assert verdict.reasoning == "Checked the 11x speedup claim."
    assert verdict.concerns == []


def test_parses_a_failing_verdict_and_keeps_its_concerns(tmp_path: Path) -> None:
    path = _write_verdict(
        tmp_path,
        {
            "ok": False,
            "reasoning": "The overview states a 20x speedup; the paper says 11x.",
            "concerns": ["Speedup figure disagrees with Table 2.", "  ", "No dataset named."],
        },
    )
    verdict = parse_verdict(path)
    assert verdict.ok is False
    # Blank entries are dropped: an empty concern would reach the retry turn as
    # an instruction to fix nothing.
    assert verdict.concerns == [
        "Speedup figure disagrees with Table 2.",
        "No dataset named.",
    ]


def test_a_missing_verdict_file_is_a_failure(tmp_path: Path) -> None:
    with pytest.raises(ReviewError, match="no verdict.json"):
        parse_verdict(tmp_path / "verdict.json")


def test_malformed_json_is_a_failure(tmp_path: Path) -> None:
    path = _write_verdict(tmp_path, '{"ok": true, "reasoning": "cut off"')
    with pytest.raises(ReviewError, match="not valid JSON"):
        parse_verdict(path)


def test_a_json_array_is_not_a_verdict(tmp_path: Path) -> None:
    path = _write_verdict(tmp_path, [{"ok": True}])
    with pytest.raises(ReviewError, match="not a JSON object"):
        parse_verdict(path)


@pytest.mark.parametrize("missing", ["ok", "reasoning", "concerns"])
def test_every_required_key_is_required(tmp_path: Path, missing: str) -> None:
    payload = {"ok": True, "reasoning": "Fine.", "concerns": []}
    del payload[missing]
    path = _write_verdict(tmp_path, payload)
    with pytest.raises(ReviewError, match=f"missing the '{missing}' key"):
        parse_verdict(path)


@pytest.mark.parametrize("value", ["true", 1, None])
def test_ok_must_be_a_real_boolean(tmp_path: Path, value: object) -> None:
    """`1` is the interesting case: `bool` subclasses `int`, so a naive check passes it."""

    path = _write_verdict(tmp_path, {"ok": value, "reasoning": "x", "concerns": []})
    with pytest.raises(ReviewError, match="'ok' is"):
        parse_verdict(path)


def test_concerns_must_be_a_list_of_strings(tmp_path: Path) -> None:
    path = _write_verdict(
        tmp_path, {"ok": False, "reasoning": "x", "concerns": [{"issue": "wrong"}]}
    )
    with pytest.raises(ReviewError, match="list of strings"):
        parse_verdict(path)


def test_empty_reasoning_is_a_failure(tmp_path: Path) -> None:
    path = _write_verdict(tmp_path, {"ok": True, "reasoning": "   ", "concerns": []})
    with pytest.raises(ReviewError, match="'reasoning' is empty"):
        parse_verdict(path)


def test_a_rejection_without_concerns_is_a_failure(tmp_path: Path) -> None:
    """A "no" the construction agent cannot act on is not a usable verdict."""

    path = _write_verdict(tmp_path, {"ok": False, "reasoning": "Not good.", "concerns": []})
    with pytest.raises(ReviewError, match="lists no concerns"):
        parse_verdict(path)


# --------------------------------------------------------------------------- #
# staging: the reviewer sees a copy, and only three files of it
# --------------------------------------------------------------------------- #


def test_only_the_three_reviewable_files_are_staged(tmp_path: Path) -> None:
    paper_dir = _built_sample(tmp_path)
    review_dir = prepare_review_dir(paper_dir, tmp_path / "build" / "review")

    assert sorted(path.name for path in review_dir.iterdir()) == sorted(
        ["main.tex", SHORT, LONG]
    )
    # provenance.json would tell the reviewer what the constructor claims, and
    # template.tex is a different question entirely.
    assert not (review_dir / "provenance.json").exists()
    assert not (review_dir / "template.tex").exists()


def test_the_review_dir_is_rebuilt_from_scratch(tmp_path: Path) -> None:
    """A stale copy would let the reviewer grade the previous turn's overview."""

    paper_dir = _built_sample(tmp_path)
    review_dir = tmp_path / "build" / "review"
    prepare_review_dir(paper_dir, review_dir)
    (review_dir / "verdict.json").write_text('{"ok": true}', encoding="utf-8")
    (review_dir / SHORT).write_text("last turn's overview", encoding="utf-8")

    prepare_review_dir(paper_dir, review_dir)
    assert not (review_dir / "verdict.json").exists()
    assert (review_dir / SHORT).read_text(encoding="utf-8") == "# Title\n\nBEAGLE\n"


def test_a_sample_missing_an_overview_cannot_be_reviewed(tmp_path: Path) -> None:
    paper_dir = _built_sample(tmp_path)
    (paper_dir / "resources" / LONG).unlink()
    with pytest.raises(ReviewError, match=LONG):
        prepare_review_dir(paper_dir, tmp_path / "build" / "review")


# --------------------------------------------------------------------------- #
# run_review: the agent is stubbed, the containment is not
# --------------------------------------------------------------------------- #


def _stub_agent(monkeypatch: pytest.MonkeyPatch, behaviour) -> list[dict]:
    """Replace the opencode call with `behaviour(workspace)`, recording the call."""

    calls: list[dict] = []

    def fake(*, paper_id, prompt, workspace, log_dir, model, turn, continue_session,
             timeout, dry_run) -> AgentRun:
        calls.append(
            {
                "paper_id": paper_id,
                "prompt": prompt,
                "workspace": Path(workspace),
                "model": model,
                "continue_session": continue_session,
            }
        )
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{paper_id}.turn{turn}.log"
        log_path.write_text("stub run\n", encoding="utf-8")
        returncode = behaviour(Path(workspace))
        return AgentRun(
            paper_id=paper_id,
            turn=turn,
            command=("opencode", "run"),
            returncode=returncode,
            log_path=log_path,
            started_at="2026-08-31T00:00:00+00:00",
            finished_at="2026-08-31T00:01:00+00:00",
        )

    monkeypatch.setattr(review_module, "run_agent_session", fake)
    return calls


def test_run_review_returns_the_agents_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper_dir = _built_sample(tmp_path)

    def behaviour(workspace: Path) -> int:
        _write_verdict(
            workspace,
            {"ok": True, "reasoning": "The 352-genome dengue set is named.", "concerns": []},
        )
        return 0

    calls = _stub_agent(monkeypatch, behaviour)
    verdict = run_review(
        SPEC,
        LIFESCI_PLUGIN,
        paper_dir,
        build_root=tmp_path / "build",
        log_dir=tmp_path / "logs",
    )

    assert verdict.ok is True
    assert "dengue" in verdict.reasoning
    assert calls[0]["continue_session"] is False, "review is single-shot, never a continuation"


def test_the_reviewer_is_never_pointed_at_the_live_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The safety property: `--auto` writes land in the scratch copy, not the corpus."""

    paper_dir = _built_sample(tmp_path)
    build_root = tmp_path / "build"

    def behaviour(workspace: Path) -> int:
        # A reviewer under `--auto` can write anywhere it is pointed. Simulate
        # exactly that, then assert the blast radius was the throwaway copy.
        (workspace / SHORT).write_text("I rewrote the overview I was grading.", encoding="utf-8")
        _write_verdict(workspace, {"ok": True, "reasoning": "Looks fine now.", "concerns": []})
        return 0

    calls = _stub_agent(monkeypatch, behaviour)
    run_review(
        SPEC,
        LIFESCI_PLUGIN,
        paper_dir,
        build_root=build_root,
        log_dir=tmp_path / "logs",
    )

    workspace = calls[0]["workspace"]
    assert workspace == (build_root / SPEC.paper_id / "review").resolve()
    assert not workspace.is_relative_to(paper_dir)
    assert (paper_dir / "resources" / SHORT).read_text(encoding="utf-8") == "# Title\n\nBEAGLE\n"


def test_a_reviewer_that_writes_nothing_fails_the_paper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper_dir = _built_sample(tmp_path)
    _stub_agent(monkeypatch, lambda workspace: 0)

    verdict = run_review(
        SPEC,
        LIFESCI_PLUGIN,
        paper_dir,
        build_root=tmp_path / "build",
        log_dir=tmp_path / "logs",
    )
    assert verdict.ok is False
    assert "unusable verdict" in verdict.reasoning
    assert verdict.concerns


def test_a_crashed_reviewer_reports_the_crash_not_the_symptom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper_dir = _built_sample(tmp_path)
    _stub_agent(monkeypatch, lambda workspace: 1)

    verdict = run_review(
        SPEC,
        LIFESCI_PLUGIN,
        paper_dir,
        build_root=tmp_path / "build",
        log_dir=tmp_path / "logs",
    )
    assert verdict.ok is False
    assert "exited 1" in verdict.reasoning


def test_a_dry_run_does_not_reject_the_paper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper_dir = _built_sample(tmp_path)
    calls = _stub_agent(monkeypatch, lambda workspace: 0)

    verdict = run_review(
        SPEC,
        LIFESCI_PLUGIN,
        paper_dir,
        build_root=tmp_path / "build",
        log_dir=tmp_path / "logs",
        dry_run=True,
    )
    assert verdict.ok is True
    assert "dry run" in verdict.reasoning
    assert calls == [], "a dry run must not spend a model call"


# --------------------------------------------------------------------------- #
# model selection
# --------------------------------------------------------------------------- #


def test_the_reviewer_defaults_to_a_different_model_than_the_constructor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same-model self-grading is the bias this whole stage exists to avoid."""

    monkeypatch.delenv("REVIEWER_MODEL", raising=False)
    assert default_reviewer_model() == DEFAULT_REVIEWER_MODEL
    assert DEFAULT_REVIEWER_MODEL != DEFAULT_MODEL
    assert DEFAULT_REVIEWER_MODEL.split("/")[0] != DEFAULT_MODEL.split("/")[0]


def test_the_reviewer_model_is_overridable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper_dir = _built_sample(tmp_path)
    monkeypatch.setenv("REVIEWER_MODEL", "deepseek-priority/deepseek-v4-pro")
    assert default_reviewer_model() == "deepseek-priority/deepseek-v4-pro"

    def behaviour(workspace: Path) -> int:
        _write_verdict(workspace, {"ok": True, "reasoning": "Fine.", "concerns": []})
        return 0

    calls = _stub_agent(monkeypatch, behaviour)
    run_review(
        SPEC, LIFESCI_PLUGIN, paper_dir,
        build_root=tmp_path / "build", log_dir=tmp_path / "logs",
    )
    assert calls[0]["model"] == "deepseek-priority/deepseek-v4-pro"

    # An explicit argument outranks the environment.
    calls.clear()
    run_review(
        SPEC, LIFESCI_PLUGIN, paper_dir,
        build_root=tmp_path / "build", log_dir=tmp_path / "logs",
        model="apex-claude/claude-opus-4-8",
    )
    assert calls[0]["model"] == "apex-claude/claude-opus-4-8"


# --------------------------------------------------------------------------- #
# the prompt, and the report integration
# --------------------------------------------------------------------------- #


def test_the_prompt_names_the_files_and_the_verdict_shape() -> None:
    prompt = build_review_prompt(SPEC, LIFESCI_PLUGIN, Path("/scratch/review"))
    for needle in ("main.tex", SHORT, LONG, "verdict.json", "/scratch/review"):
        assert needle in prompt
    assert '"concerns"' in prompt
    # Domain-driven, not hardcoded: the skeleton comes off the plugin.
    assert "Biological Significance" in prompt
    assert SPEC.arxiv_id in prompt
    # The prompt must not make passing the path of least resistance.
    assert "Passing is not the default" in prompt


def test_a_failing_verdict_flips_the_report_and_reaches_the_next_turn() -> None:
    """The integration the design turns on: no parallel report, no new retry loop."""

    report = ValidationReport(paper_id="paper_1", paper_dir=Path("/nowhere"))
    assert report.ok

    verdict = ReviewVerdict(
        ok=False,
        reasoning="The overview reports a 20x speedup the paper never claims.",
        concerns=["Correct the speedup figure to match Table 2.", "Name the benchmark alignments."],
    )
    report.fail("reconstructability-review", verdict.reasoning, remedy=verdict.remedy())

    assert not report.ok
    feedback = report.agent_feedback()
    assert "reconstructability-review" in feedback
    assert "20x speedup" in feedback
    # Both concerns must survive into the retry text, or the agent fixes half of it.
    assert "Correct the speedup figure to match Table 2." in feedback
    assert "Name the benchmark alignments." in feedback


def test_a_passing_verdict_leaves_the_report_alone() -> None:
    report = ValidationReport(paper_id="paper_1", paper_dir=Path("/nowhere"))
    verdict = ReviewVerdict(ok=True, reasoning="Faithful and sufficient.", concerns=[])
    if not verdict.ok:  # pragma: no cover - documents the pipeline's guard
        report.fail("reconstructability-review", verdict.reasoning)
    assert report.ok
    assert report.agent_feedback() == ""


def test_the_audit_record_is_verifier_only(tmp_path: Path) -> None:
    """`resources/` is copied into the writer's environment; a review is not for it."""

    paper_dir = _built_sample(tmp_path)
    verdict = ReviewVerdict(ok=True, reasoning="Faithful.", concerns=["Minor: units."])
    destination = write_review_record(paper_dir, verdict)

    assert destination == paper_dir / "original" / "reconstructability_review.json"
    assert not (paper_dir / "resources" / "reconstructability_review.json").exists()
    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "ok": True,
        "reasoning": "Faithful.",
        "concerns": ["Minor: units."],
    }
