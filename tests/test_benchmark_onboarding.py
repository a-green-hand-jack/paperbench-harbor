"""The generic onboarding path must remain human-gated and independently checked."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import screen_benchmark_candidate as screen
import verify_benchmark_candidate as verify

from paperbench_harbor.onboarding.candidate import (
    OnboardingError,
    parse_candidate,
    read_layout_approval,
)

COMMIT = "a" * 40
MANIFEST = json.dumps({"samples": [{"id": "one"}, {"id": "two"}]}).encode()


def _proposal(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "benchmark_id": "survey-eval",
        "source_repository": "https://github.com/example/survey-eval",
        "source_revision": COMMIT,
        "source_license": "MIT",
        "dataset_manifest_url": (
            f"https://raw.githubusercontent.com/example/survey-eval/{COMMIT}/samples.json"
        ),
        "dataset_manifest_sha256": hashlib.sha256(MANIFEST).hexdigest(),
        "benchmark_license": "CC BY 4.0",
        "sample_count": 2,
        "writer_deliverable": True,
        "requires_experiments": False,
        "requires_code": False,
        "input_protocol": "prepared source materials to manuscript",
        "evaluator": "official evaluator at commit " + COMMIT,
        "selection_record_url": "https://github.com/a-green-hand-jack/paperbench-harbor/issues/2",
        "rationale": "Fixed public dataset and official manuscript evaluator.",
    }
    record.update(overrides)
    return record


def _write(path: Path, record: dict[str, object]) -> None:
    path.write_text(json.dumps(record), encoding="utf-8")


def test_screening_canonicalizes_but_does_not_promote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proposal = tmp_path / "proposal.json"
    output = tmp_path / "benchmark_candidate.json"
    _write(proposal, _proposal())

    monkeypatch.setattr(
        sys, "argv", ["screen", "--proposal", str(proposal), "--output", str(output)]
    )
    assert screen.main() == 0
    assert parse_candidate(output).benchmark_id == "survey-eval"
    assert output.read_bytes() != proposal.read_bytes()


def test_screening_rejects_research_agent_candidate(tmp_path: Path) -> None:
    proposal = tmp_path / "proposal.json"
    _write(proposal, _proposal(requires_code=True))
    with pytest.raises(OnboardingError, match="research agent"):
        parse_candidate(proposal)


def test_verifier_rederives_revision_license_manifest_and_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proposal = tmp_path / "candidate.json"
    _write(proposal, _proposal())

    def fake_get(url: str) -> bytes:
        if url == "https://api.github.com/repos/example/survey-eval":
            return json.dumps(
                {"private": False, "license": {"spdx_id": "MIT", "name": "MIT License"}}
            ).encode()
        if url == f"https://api.github.com/repos/example/survey-eval/commits/{COMMIT}":
            return json.dumps({"sha": COMMIT}).encode()
        if url == f"https://raw.githubusercontent.com/example/survey-eval/{COMMIT}/samples.json":
            return MANIFEST
        raise AssertionError(url)

    monkeypatch.setattr(verify, "_http_get", fake_get)
    report = verify.verify(parse_candidate(proposal))
    assert report["sample_count"] == 2
    assert report["source_revision"] == COMMIT


def test_candidate_rejects_a_movable_sample_manifest_url(tmp_path: Path) -> None:
    proposal = tmp_path / "proposal.json"
    _write(proposal, _proposal(dataset_manifest_url="https://example.invalid/samples.json"))

    with pytest.raises(OnboardingError, match="immutable GitHub or Hugging Face revision"):
        parse_candidate(proposal)


def test_human_layout_approval_is_bound_to_candidate_and_layout_bytes(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.json"
    layout = tmp_path / "layout.json"
    approval = tmp_path / "approval.json"
    _write(candidate, _proposal())
    layout.write_text('{"identity": "survey-eval"}\n', encoding="utf-8")
    approval.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                "layout_spec_sha256": hashlib.sha256(layout.read_bytes()).hexdigest(),
                "reviewer": "Jieke",
            }
        ),
        encoding="utf-8",
    )

    assert (
        read_layout_approval(approval, candidate_path=candidate, layout_spec_path=layout).reviewer
        == "Jieke"
    )
    layout.write_text('{"identity": "changed"}\n', encoding="utf-8")
    with pytest.raises(OnboardingError, match="layout spec"):
        read_layout_approval(approval, candidate_path=candidate, layout_spec_path=layout)


def test_benchmark_onboard_policy_cannot_edit_or_bypass_required_audits() -> None:
    text = (REPO_ROOT / ".opencode" / "agent" / "benchmark-onboard.md").read_text(encoding="utf-8")
    assert "mode: primary" in text
    assert '  "*": deny' in text
    assert "  write: deny" in text
    assert "  edit: deny" in text
    assert "  task: deny" in text
    assert '    "* --no-audit": deny' in text
    assert '    "* --no-semantic-review": deny' in text
    assert "hostname && pwd && git rev-parse --show-toplevel" in text
    assert "git rev-parse --is-inside-work-tree && git status --short" in text
    assert "screen_benchmark_candidate.py" in text
    assert "verify_benchmark_candidate.py" in text
    assert "human approval" in text
    assert "source-archive plan" in text
