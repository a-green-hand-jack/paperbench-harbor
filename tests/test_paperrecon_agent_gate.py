from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from paperbench_harbor.construction.lifesci_paperrecon.screening import LIFESCI_SCREENING_POLICY
from scripts.consolidate_paperrecon_candidates import ConsolidationError, consolidate
from scripts.promote_lifesci_paperrecon_candidates import read_candidates
from scripts.verify_paperrecon_candidates import VerifierError, read_agent_approval


def _record(arxiv_id: str, **overrides: object) -> dict[str, object]:
    value = {
        "arxiv_id": arxiv_id,
        "expected_version": "v1",
        "code_status": "available",
        "code_repo": "https://github.com/owner/repo",
        "expected_license": "CC BY 4.0",
        "code_license": "MIT",
        "code_not_applicable_reason": "",
        "expected_category": "q-bio.GN",
        "paper_type": "computational",
        "note": "A paper.",
        "rationale": "Source and repository verified.",
    }
    value.update(overrides)
    return value


def _report(path: Path, records: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps({"schema_version": 1, "domain": "lifesci", "candidates": records}), encoding="utf-8")
    return path


def test_consolidation_is_sorted_and_deduplicates_exact_records(tmp_path: Path) -> None:
    one = _report(tmp_path / "one.json", [_record("2504.22222"), _record("2504.11111")])
    two = _report(tmp_path / "two.json", [_record("2504.11111")])
    output = tmp_path / "candidate-set.json"
    result = consolidate([one, two], domain_name="lifesci", output=output, minimum=2)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert [item["arxiv_id"] for item in payload["candidates"]] == ["2504.11111", "2504.22222"]
    assert result["candidate_set_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()


def test_consolidation_rejects_conflicting_duplicate(tmp_path: Path) -> None:
    one = _report(tmp_path / "one.json", [_record("2504.11111")])
    two = _report(tmp_path / "two.json", [_record("2504.11111", expected_version="v2")])
    with pytest.raises(ConsolidationError, match="conflicting records"):
        consolidate([one, two], domain_name="lifesci", output=tmp_path / "out.json", minimum=1)


def test_consolidation_enforces_reserve(tmp_path: Path) -> None:
    one = _report(tmp_path / "one.json", [_record("2504.11111")])
    with pytest.raises(ConsolidationError, match="need at least 2"):
        consolidate([one], domain_name="lifesci", output=tmp_path / "out.json", minimum=1, reserve=1)


def test_agent_approval_is_sha_bound_and_independent(tmp_path: Path) -> None:
    candidate_path = _report(tmp_path / "candidate.json", [_record("2504.11111")])
    candidates = read_candidates(candidate_path, policy=LIFESCI_SCREENING_POLICY, exclude_ids=())
    approval = tmp_path / "agent-approval.json"
    approval.write_text(json.dumps({
        "schema_version": 1,
        "candidate_sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
        "screening_model": "openai/gpt-5.6-terra",
        "verifiers": [{"model": "openai/gpt-5.5"}, {"model": "apex/gpt-5.6-sol"}],
        "approved_arxiv_ids": ["2504.11111"],
    }), encoding="utf-8")
    parsed = read_agent_approval(approval, candidates_path=candidate_path, candidates=candidates)
    assert parsed["approved_arxiv_ids"] == frozenset({"2504.11111"})

    approval.write_text(approval.read_text(encoding="utf-8").replace("openai/gpt-5.5", "openai/gpt-5.6-terra"), encoding="utf-8")
    with pytest.raises(VerifierError, match="not independent"):
        read_agent_approval(approval, candidates_path=candidate_path, candidates=candidates)
