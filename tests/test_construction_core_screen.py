"""Screening proposes; it does not decide. These tests hold that line.

Two things could quietly break stage 1, and neither would show up as a crash.

* **A proposal that was never really checked.** `candidates.json` comes from an
  LLM with network access, and a malformed or unfiltered entry that parsed
  anyway would put a paper in front of a human wearing the authority of a
  verified one. Every shape and policy violation below must raise, including
  the ones the prompt already asked the agent to avoid — "we told it not to" is
  not a check.
* **A prompt that quietly asks for the wrong thing.** The criteria live in a
  `ScreeningPolicy`, so the tests assert the policy actually reaches the prompt
  and that the core invariants (license list, exclusions, record-don't-block on
  the code repo) are present regardless of what a domain supplied.

As in the review tests, `run_agent_session` is stubbed: no network, no
`opencode`, no arXiv.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperbench_harbor.construction.core import screen as screen_module
from paperbench_harbor.construction.core.opencode_agent import AgentRun
from paperbench_harbor.construction.core.screen import (
    REQUIRED_CANDIDATE_FIELDS,
    Candidate,
    ScreeningError,
    ScreeningPolicy,
    SeedCandidate,
    build_screening_prompt,
    parse_candidates,
    run_screening,
)
from paperbench_harbor.construction.core.spec import ACCEPTED_LICENSES
from paperbench_harbor.construction.lifesci_paperrecon.plugin import LIFESCI_PLUGIN
from paperbench_harbor.construction.lifesci_paperrecon.screening import (
    LIFESCI_EXCLUDE_IDS,
    LIFESCI_SCREENING_POLICY,
    LIFESCI_SEED_CANDIDATES,
)

#: An in-test policy, deliberately not biology, so a hard-coded `q-bio` in the
#: core would show up as a failure here rather than as silence.
GEOLOGY_POLICY = ScreeningPolicy(
    name="geology",
    search_scope="arXiv `physics.geo-ph`, and the EarthArXiv mirror.",
    selection_criteria="Field studies with a public data-processing repository.",
    paper_types=("field", "modelling"),
    prior_findings="Seismology preprints rarely ship LaTeX source.",
)


def _candidate(**overrides: object) -> dict:
    record = {
        "arxiv_id": "2503.19375",
        "expected_version": "v2",
        "code_repo": "https://github.com/owner/repo",
        "expected_license": "CC BY 4.0",
        "code_license": "none declared",
        "expected_category": "q-bio.CB",
        "paper_type": "computational",
        "note": "Morphogenesis simulation study.",
        "rationale": "LaTeX source present, bibliography inline, repo checkable out.",
    }
    record.update(overrides)
    return record


def _write(directory: Path, payload: object) -> Path:
    path = directory / "candidates.json"
    text = payload if isinstance(payload, str) else json.dumps(payload)
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# prompt building
# --------------------------------------------------------------------------- #


def test_the_policy_reaches_the_prompt() -> None:
    prompt = build_screening_prompt(
        GEOLOGY_POLICY, target_count=10, output_path=Path("/scratch/candidates.json")
    )
    assert "physics.geo-ph" in prompt
    assert "Field studies with a public data-processing repository." in prompt
    assert "Seismology preprints rarely ship LaTeX source." in prompt
    assert "`field`" in prompt and "`modelling`" in prompt
    assert "/scratch/candidates.json" in prompt
    assert "10" in prompt
    # No biology leaks into another domain's screening prompt.
    assert "q-bio" not in prompt


def test_the_core_invariants_are_present_whatever_the_policy_says() -> None:
    prompt = build_screening_prompt(
        GEOLOGY_POLICY, target_count=10, output_path=Path("/scratch/candidates.json")
    )
    for license_name in ACCEPTED_LICENSES:
        assert license_name in prompt
    assert "PDF-only submission is disqualified" in prompt
    # Record-don't-block: the repo license is read, not filtered on.
    assert "is **not** a filter" in prompt
    assert "none declared" in prompt
    assert "GET /repos/{owner}/{repo}" in prompt


def test_seeds_are_listed_for_re_verification_not_trusted() -> None:
    prompt = build_screening_prompt(
        GEOLOGY_POLICY,
        seed_candidates=(
            SeedCandidate(arxiv_id="2401.00001", title="Basalt weathering rates"),
        ),
        target_count=10,
        output_path=Path("/scratch/candidates.json"),
    )
    assert "2401.00001" in prompt
    assert "Basalt weathering rates" in prompt
    assert "Treat every one as unverified" in prompt


def test_an_empty_seed_list_asks_for_a_fresh_search() -> None:
    """The lifesci case: nothing machine-readable survived Phase 0."""

    prompt = build_screening_prompt(
        GEOLOGY_POLICY, target_count=10, output_path=Path("/scratch/candidates.json")
    )
    assert "searching from scratch" in prompt
    assert "Step 1 — re-verify" not in prompt


def test_excluded_ids_appear_in_the_prompt() -> None:
    prompt = build_screening_prompt(
        GEOLOGY_POLICY,
        target_count=10,
        exclude_ids=("2606.27607", "2503.19375"),
        output_path=Path("/scratch/candidates.json"),
    )
    assert "2606.27607" in prompt and "2503.19375" in prompt


# --------------------------------------------------------------------------- #
# candidates.json parsing
# --------------------------------------------------------------------------- #


def test_parses_a_well_formed_proposal(tmp_path: Path) -> None:
    path = _write(tmp_path, [_candidate(), _candidate(arxiv_id="2601.02265")])
    candidates = parse_candidates(path, policy=LIFESCI_SCREENING_POLICY)
    assert len(candidates) == 2
    assert isinstance(candidates[0], Candidate)
    assert candidates[0].code_license == "none declared"
    assert candidates[0].as_dict()["arxiv_id"] == "2503.19375"


def test_an_empty_proposal_is_valid(tmp_path: Path) -> None:
    """"I found nothing" is an honest answer, not a malformed file."""

    assert parse_candidates(_write(tmp_path, [])) == []


def test_a_missing_file_is_a_failure(tmp_path: Path) -> None:
    with pytest.raises(ScreeningError, match="wrote no candidates.json"):
        parse_candidates(tmp_path / "candidates.json")


def test_malformed_json_is_a_failure(tmp_path: Path) -> None:
    with pytest.raises(ScreeningError, match="not valid JSON"):
        parse_candidates(_write(tmp_path, '[{"arxiv_id": "x"'))


def test_an_object_is_not_a_candidate_list(tmp_path: Path) -> None:
    with pytest.raises(ScreeningError, match="not a JSON array"):
        parse_candidates(_write(tmp_path, {"candidates": []}))


@pytest.mark.parametrize("missing", REQUIRED_CANDIDATE_FIELDS)
def test_every_field_is_required(tmp_path: Path, missing: str) -> None:
    record = _candidate()
    del record[missing]
    with pytest.raises(ScreeningError, match=f"missing the '{missing}' key"):
        parse_candidates(_write(tmp_path, [record]))


def test_a_non_string_field_is_a_failure(tmp_path: Path) -> None:
    with pytest.raises(ScreeningError, match="'expected_version' is int"):
        parse_candidates(_write(tmp_path, [_candidate(expected_version=2)]))


def test_an_unrecorded_code_license_is_a_failure(tmp_path: Path) -> None:
    """Record-don't-block only works if the finding is actually recorded.

    An unlicensed repo no longer blocks construction, so a blank `code_license`
    is the one thing that would make an unlicensed repo indistinguishable from
    a licensed one by the time the dataset card is written.
    """

    with pytest.raises(ScreeningError, match="'code_license' is empty"):
        parse_candidates(_write(tmp_path, [_candidate(code_license="  ")]))


def test_an_empty_note_is_allowed(tmp_path: Path) -> None:
    assert parse_candidates(_write(tmp_path, [_candidate(note="")]))[0].note == ""


def test_a_non_permissive_license_is_rejected(tmp_path: Path) -> None:
    """The paper's own license is still a hard filter, unlike the repo's."""

    with pytest.raises(ScreeningError, match="not redistribution-permissive"):
        parse_candidates(_write(tmp_path, [_candidate(expected_license="CC BY-NC-ND 4.0")]))


def test_a_duplicate_arxiv_id_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ScreeningError, match="repeats arxiv_id"):
        parse_candidates(_write(tmp_path, [_candidate(), _candidate()]))


def test_an_excluded_paper_is_rejected(tmp_path: Path) -> None:
    """The agent was told to exclude it; being told is not being checked."""

    with pytest.raises(ScreeningError, match="was on the exclusion list"):
        parse_candidates(
            _write(tmp_path, [_candidate(arxiv_id="2606.27607")]),
            exclude_ids=("2606.27607",),
        )


def test_a_paper_type_outside_the_domains_taxonomy_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ScreeningError, match="paper_type 'ethnography' is not one of"):
        parse_candidates(
            _write(tmp_path, [_candidate(paper_type="ethnography")]),
            policy=LIFESCI_SCREENING_POLICY,
        )


# --------------------------------------------------------------------------- #
# run_screening
# --------------------------------------------------------------------------- #


def _stub_agent(monkeypatch: pytest.MonkeyPatch, behaviour) -> list[dict]:
    calls: list[dict] = []

    def fake(*, paper_id, prompt, workspace, log_dir, model, turn, continue_session,
             timeout, dry_run) -> AgentRun:
        calls.append({"workspace": Path(workspace), "model": model, "prompt": prompt})
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
            finished_at="2026-08-31T00:10:00+00:00",
        )

    monkeypatch.setattr(screen_module, "run_agent_session", fake)
    return calls


def test_run_screening_returns_validated_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def behaviour(workspace: Path) -> int:
        _write(workspace, [_candidate()])
        return 0

    calls = _stub_agent(monkeypatch, behaviour)
    candidates = run_screening(
        LIFESCI_SCREENING_POLICY,
        build_root=tmp_path / "build",
        target_count=5,
        log_dir=tmp_path / "logs",
    )
    assert [candidate.arxiv_id for candidate in candidates] == ["2503.19375"]
    # Its own scratch dir under build_root, like every other --auto session here.
    assert calls[0]["workspace"] == (tmp_path / "build" / "screening-lifesci").resolve()


def test_a_stale_proposal_is_never_read_back_as_a_fresh_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worst failure here looks exactly like a successful run."""

    build_root = tmp_path / "build"
    screening_dir = build_root / "screening-lifesci"
    screening_dir.mkdir(parents=True)
    _write(screening_dir, [_candidate(arxiv_id="9999.99999")])

    _stub_agent(monkeypatch, lambda workspace: 0)
    with pytest.raises(ScreeningError, match="wrote no candidates.json"):
        run_screening(
            LIFESCI_SCREENING_POLICY,
            build_root=build_root,
            target_count=5,
            log_dir=tmp_path / "logs",
        )


def test_a_crashed_screening_agent_reports_the_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_agent(monkeypatch, lambda workspace: 1)
    with pytest.raises(ScreeningError, match="exited 1"):
        run_screening(
            LIFESCI_SCREENING_POLICY,
            build_root=tmp_path / "build",
            target_count=5,
            log_dir=tmp_path / "logs",
        )


def test_a_dry_run_spends_no_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _stub_agent(monkeypatch, lambda workspace: 0)
    assert run_screening(
        LIFESCI_SCREENING_POLICY,
        build_root=tmp_path / "build",
        target_count=5,
        log_dir=tmp_path / "logs",
        dry_run=True,
    ) == []
    assert calls == []


# --------------------------------------------------------------------------- #
# the lifesci policy itself
# --------------------------------------------------------------------------- #


def test_the_lifesci_seed_list_is_honestly_empty() -> None:
    """Phase 0's 27 candidates left no machine-readable record beyond the pilots.

    Pinned as a test because the tempting fix — reconstructing plausible arXiv
    IDs from the category breakdown — produces a list that looks like recovered
    data and is not.
    """

    assert LIFESCI_SEED_CANDIDATES == ()


def test_the_built_pilots_are_excluded_from_the_next_pass() -> None:
    assert set(LIFESCI_EXCLUDE_IDS) == {"2606.27607", "2503.19375", "2601.02265"}


def test_the_policy_agrees_with_the_domain_plugin_on_paper_types() -> None:
    """A candidate typed outside the plugin's taxonomy fails at construction."""

    assert LIFESCI_SCREENING_POLICY.paper_types == LIFESCI_PLUGIN.paper_types


def test_the_lifesci_policy_carries_the_phase_0_findings() -> None:
    prompt = build_screening_prompt(
        LIFESCI_SCREENING_POLICY,
        seed_candidates=LIFESCI_SEED_CANDIDATES,
        target_count=40,
        exclude_ids=LIFESCI_EXCLUDE_IDS,
        output_path=Path("/scratch/candidates.json"),
    )
    assert "q-bio.SC" in prompt, "the dead-end category must reach the agent"
    assert "license filter bound hardest" in prompt
    for category in ("q-bio.BM", "q-bio.QM", "q-bio.GN", "q-bio.MN",
                     "q-bio.CB", "q-bio.PE", "q-bio.NC", "q-bio.TO"):
        assert category in prompt
    for arxiv_id in LIFESCI_EXCLUDE_IDS:
        assert arxiv_id in prompt
