"""Tests for `papers.py`'s additive `approved_scaleup.jsonl` loader (Phase 8 step 2).

`_load_scaleup_promotions` is exercised directly, with an explicit path, rather
than through the module-level `APPROVED_PAPERS` constant — that constant is
computed once at import time from the real `approved_scaleup.jsonl` next to
this module, and a test must not depend on whether that file happens to exist
on the machine running the suite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperbench_harbor.construction.core.spec import PaperSpec
from paperbench_harbor.construction.lifesci_paperrecon.papers import (
    APPROVED_PAPERS,
    _load_scaleup_promotions,
)


def _record(**overrides: str) -> dict:
    base = {
        "paper_id": "paper_39",
        "arxiv_id": "2609.00001",
        "paper_type": "computational",
        "code_repo": "https://github.com/example/repo",
        "expected_license": "CC BY 4.0",
        "expected_version": "v1",
        "expected_category": "q-bio.QM",
        "note": "A promoted example.",
    }
    base.update(overrides)
    return base


def test_a_missing_file_yields_nothing(tmp_path: Path) -> None:
    assert _load_scaleup_promotions(tmp_path / "does-not-exist.jsonl") == ()


def test_approved_papers_matches_the_hand_curated_tuple_when_the_file_is_absent() -> None:
    """The loader must be a no-op for a checkout that never ran promotion."""

    ids = [spec.paper_id for spec in APPROVED_PAPERS]
    assert ids == sorted(ids, key=lambda paper_id: int(paper_id.split("_")[1]))
    assert len(ids) == len(set(ids))


def test_one_record_round_trips_into_a_paper_spec(tmp_path: Path) -> None:
    path = tmp_path / "approved_scaleup.jsonl"
    path.write_text(json.dumps(_record()) + "\n", encoding="utf-8")

    specs = _load_scaleup_promotions(path)

    assert specs == (
        PaperSpec(
            paper_id="paper_39",
            arxiv_id="2609.00001",
            paper_type="computational",
            code_repo="https://github.com/example/repo",
            expected_license="CC BY 4.0",
            expected_version="v1",
            expected_category="q-bio.QM",
            note="A promoted example.",
        ),
    )


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "approved_scaleup.jsonl"
    path.write_text("\n" + json.dumps(_record()) + "\n\n", encoding="utf-8")

    assert len(_load_scaleup_promotions(path)) == 1


def test_multiple_records_preserve_file_order(tmp_path: Path) -> None:
    path = tmp_path / "approved_scaleup.jsonl"
    path.write_text(
        json.dumps(_record(paper_id="paper_39", arxiv_id="2609.00001"))
        + "\n"
        + json.dumps(_record(paper_id="paper_40", arxiv_id="2609.00002"))
        + "\n",
        encoding="utf-8",
    )

    specs = _load_scaleup_promotions(path)

    assert [spec.paper_id for spec in specs] == ["paper_39", "paper_40"]


def test_malformed_json_raises_rather_than_dropping_the_line(tmp_path: Path) -> None:
    path = tmp_path / "approved_scaleup.jsonl"
    path.write_text("{not valid json\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid JSON"):
        _load_scaleup_promotions(path)


def test_a_json_array_line_is_rejected_as_not_an_object(tmp_path: Path) -> None:
    path = tmp_path / "approved_scaleup.jsonl"
    path.write_text("[1, 2, 3]\n", encoding="utf-8")

    with pytest.raises(TypeError, match="not a JSON object"):
        _load_scaleup_promotions(path)


def test_a_missing_field_raises_by_name(tmp_path: Path) -> None:
    record = _record()
    del record["expected_category"]
    path = tmp_path / "approved_scaleup.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="expected_category"):
        _load_scaleup_promotions(path)
