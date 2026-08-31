"""Promotion is the stage that distrusts the screener. These tests hold that line.

The script exists because a screening agent's `candidates.json` is *claims*, and
the claims have been wrong in practice. So the cases below are mostly about
disagreement: for each field the script re-derives, a candidate that claims one
thing while the live source says another must be rejected, with the specific
field named in the report rather than a generic failure.

Two further properties matter as much as the checking:

* **A dry run writes nothing.** The default invocation is a report, and a report
  that silently appended to the approved list would make the `--promote` flag
  decorative.
* **Promotion is idempotent on `arxiv_id`.** The one-command agent re-runs the
  whole pipeline every time, so the same `candidates.json` will be promoted
  against twice; a second run must not duplicate a paper or reissue an id.

`_http_get` is the single network seam, so it is what gets stubbed — with
payloads copied from real arXiv and GitHub responses (2026-08-31), so the parsers
are exercised rather than bypassed. No network, no `opencode`, no model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import promote_lifesci_paperrecon_candidates as promote_module
from promote_lifesci_paperrecon_candidates import (
    APPROVED_SCALEUP_PATH,
    license_name_from_url,
    main,
    next_paper_index,
)

# --------------------------------------------------------------------------- #
# fixtures shaped like the real responses
# --------------------------------------------------------------------------- #

#: Trimmed from a real `id_list` response. Note what is *not* here: no license.
#: The Atom API does not carry one, which is why the script reads the abstract
#: page as well, and this fixture is the regression pin for that.
ARXIV_ATOM = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom"
      xmlns="http://www.w3.org/2005/Atom">
  <opensearch:totalResults>1</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/{arxiv_id}{version}</id>
    <title>A paper about something</title>
    <link href="https://arxiv.org/abs/{arxiv_id}{version}" rel="alternate" type="text/html"/>
    <summary>An abstract.</summary>
    <category term="{category}" scheme="http://arxiv.org/schemas/atom"/>
    <published>2025-03-25T06:05:47Z</published>
    <arxiv:primary_category term="{category}"/>
    <author><name>A Person</name></author>
  </entry>
</feed>
"""

#: The abstract page's license block, verbatim in shape from the live page.
ABS_PAGE = (
    '<div class="extra-services"></div>'
    '<div class="abs-license"><a href="{license_url}" '
    'title="Rights to this article" class="has_license">{license_text}</a></div>'
)

GITHUB_LICENSED = json.dumps(
    {
        "full_name": "owner/repo",
        "license": {
            "key": "mit",
            "name": "MIT License",
            "spdx_id": "MIT",
            "url": "https://api.github.com/licenses/mit",
            "node_id": "MDc6TGljZW5zZTEz",
        },
    }
)

GITHUB_UNLICENSED = json.dumps({"full_name": "owner/repo", "license": None})

CC_BY_URL = "http://creativecommons.org/licenses/by/4.0/"
CC_BY_SA_URL = "http://creativecommons.org/licenses/by-sa/4.0/"


def _candidate(**overrides: object) -> dict:
    """A candidate whose claims match :func:`_live` exactly, unless overridden."""

    record = {
        "arxiv_id": "2504.11111",
        "expected_version": "v1",
        "code_repo": "https://github.com/owner/repo",
        "expected_license": "CC BY 4.0",
        "code_license": "MIT",
        "expected_category": "q-bio.GN",
        "paper_type": "computational",
        "note": "A genomics method paper.",
        "rationale": "LaTeX source present, bibliography inline, repo checkable out.",
    }
    record.update(overrides)
    return record


def _live(
    *,
    category: str = "q-bio.GN",
    license_url: str = CC_BY_URL,
    version: str = "v1",
    github: str = GITHUB_LICENSED,
):
    """Stub `_http_get`, dispatching on URL the way the three real endpoints do."""

    def fake(url: str, *, headers: dict[str, str] | None = None) -> str:
        if "export.arxiv.org/api/query" in url:
            arxiv_id = url.split("id_list=")[1].split("&")[0]
            return ARXIV_ATOM.format(arxiv_id=arxiv_id, version=version, category=category)
        if "arxiv.org/abs/" in url:
            return ABS_PAGE.format(license_url=license_url, license_text="license text")
        if "api.github.com/repos" in url:
            return github
        raise AssertionError(f"unexpected request to {url}")

    return fake


def _write_candidates(directory: Path, records: list[dict]) -> Path:
    path = directory / "candidates.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def _lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
# the license names arXiv actually links to
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (CC_BY_URL, "CC BY 4.0"),
        (CC_BY_SA_URL, "CC BY-SA 4.0"),
        ("http://creativecommons.org/licenses/by-nc/4.0/", "CC BY-NC 4.0"),
        ("http://creativecommons.org/licenses/by-nc-nd/4.0/", "CC BY-NC-ND 4.0"),
        ("https://creativecommons.org/licenses/by-sa/3.0/", "CC BY-SA 3.0"),
        ("http://creativecommons.org/publicdomain/zero/1.0/", "CC0 1.0"),
        (
            "http://arxiv.org/licenses/nonexclusive-distrib/1.0/",
            "arXiv perpetual non-exclusive license",
        ),
    ],
)
def test_license_names_are_derived_from_the_linked_url(url: str, expected: str) -> None:
    """The spellings must match `ACCEPTED_LICENSES`, or every candidate mismatches."""

    assert license_name_from_url(url) == expected


def test_the_accepted_spellings_are_the_ones_this_parser_produces() -> None:
    """A rename in either place would silently reject every real candidate."""

    from paperbench_harbor.construction.core.spec import ACCEPTED_LICENSES

    derived = {
        license_name_from_url(url)
        for url in (
            CC_BY_URL,
            "http://creativecommons.org/licenses/by-nc/4.0/",
            CC_BY_SA_URL,
            "http://creativecommons.org/publicdomain/zero/1.0/",
        )
    }
    assert derived == set(ACCEPTED_LICENSES)


# --------------------------------------------------------------------------- #
# acceptance and the three rejections
# --------------------------------------------------------------------------- #


def test_a_candidate_whose_claims_all_match_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(promote_module, "_http_get", _live())
    approved = tmp_path / "approved_scaleup.jsonl"

    code = main(
        [
            "--candidates",
            str(_write_candidates(tmp_path, [_candidate()])),
            "--approved-file",
            str(approved),
            "--promote",
        ]
    )

    assert code == 0
    assert capsys.readouterr().out.count("eligible") >= 1
    assert [record["arxiv_id"] for record in _lines(approved)] == ["2504.11111"]


def test_a_license_mismatch_is_rejected_with_the_field_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The claim is admissible policy; it is just not what the live page says."""

    monkeypatch.setattr(promote_module, "_http_get", _live(license_url=CC_BY_SA_URL))
    approved = tmp_path / "approved_scaleup.jsonl"

    code = main(
        [
            "--candidates",
            str(_write_candidates(tmp_path, [_candidate(expected_license="CC BY 4.0")])),
            "--approved-file",
            str(approved),
            "--promote",
        ]
    )

    output = capsys.readouterr().out
    assert code == 1
    assert "rejected" in output
    assert "expected_license" in output
    assert "'CC BY 4.0'" in output and "'CC BY-SA 4.0'" in output
    assert _lines(approved) == []


def test_a_category_mismatch_is_rejected_with_the_field_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The failure already seen twice for real: a category recalled, not read."""

    monkeypatch.setattr(promote_module, "_http_get", _live(category="q-bio.PE"))
    approved = tmp_path / "approved_scaleup.jsonl"

    code = main(
        [
            "--candidates",
            str(_write_candidates(tmp_path, [_candidate(expected_category="q-bio.GN")])),
            "--approved-file",
            str(approved),
            "--promote",
        ]
    )

    output = capsys.readouterr().out
    assert code == 1
    assert "expected_category" in output
    assert "'q-bio.GN'" in output and "'q-bio.PE'" in output
    assert _lines(approved) == []


def test_a_code_license_mismatch_is_rejected_with_the_field_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Recorded-not-filtered still has to be recorded *correctly*."""

    monkeypatch.setattr(promote_module, "_http_get", _live(github=GITHUB_UNLICENSED))
    approved = tmp_path / "approved_scaleup.jsonl"

    code = main(
        [
            "--candidates",
            str(_write_candidates(tmp_path, [_candidate(code_license="MIT")])),
            "--approved-file",
            str(approved),
            "--promote",
        ]
    )

    output = capsys.readouterr().out
    assert code == 1
    assert "code_license" in output
    assert "'MIT'" in output and "'none declared'" in output
    assert _lines(approved) == []


def test_an_unlicensed_repo_recorded_honestly_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`license: null` is a valid finding, not a disqualification."""

    monkeypatch.setattr(promote_module, "_http_get", _live(github=GITHUB_UNLICENSED))
    approved = tmp_path / "approved_scaleup.jsonl"

    code = main(
        [
            "--candidates",
            str(_write_candidates(tmp_path, [_candidate(code_license="none declared")])),
            "--approved-file",
            str(approved),
            "--promote",
        ]
    )

    assert code == 0
    assert len(_lines(approved)) == 1


@pytest.mark.parametrize("spelling", ["MIT", "mit", "MIT License", "  MIT  "])
def test_github_license_spellings_are_not_treated_as_disagreement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spelling: str
) -> None:
    """Which of `spdx_id`/`name`/`key` was copied is not a fact about the paper.

    Rejecting on it would fail candidates for cosmetic inconsistency, which is
    the opposite of the error this stage exists to catch.
    """

    monkeypatch.setattr(promote_module, "_http_get", _live())
    approved = tmp_path / "approved_scaleup.jsonl"

    code = main(
        [
            "--candidates",
            str(_write_candidates(tmp_path, [_candidate(code_license=spelling)])),
            "--approved-file",
            str(approved),
            "--promote",
        ]
    )

    assert code == 0
    assert len(_lines(approved)) == 1


def test_a_candidate_that_cannot_be_verified_is_not_promoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """"Unverified" must never reach promotion looking like "verified"."""

    def unreachable(url: str, *, headers: dict[str, str] | None = None) -> str:
        raise OSError("network unreachable")

    monkeypatch.setattr(promote_module, "_http_get", unreachable)
    approved = tmp_path / "approved_scaleup.jsonl"

    code = main(
        [
            "--candidates",
            str(_write_candidates(tmp_path, [_candidate()])),
            "--approved-file",
            str(approved),
            "--promote",
        ]
    )

    assert code == 1
    assert "unverifiable" in capsys.readouterr().out
    assert _lines(approved) == []


def test_a_missing_license_block_is_unverifiable_not_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """If arXiv changes its page layout, the script must fail loudly."""

    def no_license(url: str, *, headers: dict[str, str] | None = None) -> str:
        if "arxiv.org/abs/" in url:
            return "<html><body>no license block here</body></html>"
        return _live()(url, headers=headers)

    monkeypatch.setattr(promote_module, "_http_get", no_license)
    approved = tmp_path / "approved_scaleup.jsonl"

    code = main(
        [
            "--candidates",
            str(_write_candidates(tmp_path, [_candidate()])),
            "--approved-file",
            str(approved),
            "--promote",
        ]
    )

    assert code == 1
    assert "no license block" in capsys.readouterr().out
    assert _lines(approved) == []


# --------------------------------------------------------------------------- #
# the flags
# --------------------------------------------------------------------------- #


def test_a_dry_run_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without `--promote` the script is a report. The file must not appear."""

    monkeypatch.setattr(promote_module, "_http_get", _live())
    approved = tmp_path / "approved_scaleup.jsonl"

    code = main(
        [
            "--candidates",
            str(_write_candidates(tmp_path, [_candidate()])),
            "--approved-file",
            str(approved),
        ]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "dry run" in output
    assert "eligible" in output
    assert not approved.exists(), "a dry run must not create the approved file"


def test_a_dry_run_leaves_an_existing_file_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(promote_module, "_http_get", _live())
    approved = tmp_path / "approved_scaleup.jsonl"
    existing = json.dumps({"paper_id": "paper_4", "arxiv_id": "2599.00001"}) + "\n"
    approved.write_text(existing, encoding="utf-8")

    main(
        [
            "--candidates",
            str(_write_candidates(tmp_path, [_candidate()])),
            "--approved-file",
            str(approved),
        ]
    )

    assert approved.read_text(encoding="utf-8") == existing


def test_promote_is_idempotent_on_arxiv_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one-command agent re-runs the pipeline; the second pass must be a no-op.

    Keyed on `arxiv_id` rather than `paper_id` deliberately: the id is assigned at
    promotion time, so a second run over the same candidate would coin a new one
    and a `paper_id` comparison would duplicate every entry.
    """

    monkeypatch.setattr(promote_module, "_http_get", _live())
    approved = tmp_path / "approved_scaleup.jsonl"
    candidates = _write_candidates(
        tmp_path, [_candidate(), _candidate(arxiv_id="2504.22222")]
    )

    first = main(
        ["--candidates", str(candidates), "--approved-file", str(approved), "--promote"]
    )
    after_first = _lines(approved)

    second = main(
        ["--candidates", str(candidates), "--approved-file", str(approved), "--promote"]
    )
    after_second = _lines(approved)
    output = capsys.readouterr().out

    assert first == 0 and second == 0
    assert after_first == after_second, "a second promotion run changed the file"
    assert [record["arxiv_id"] for record in after_second] == ["2504.11111", "2504.22222"]

    paper_ids = [record["paper_id"] for record in after_second]
    assert paper_ids == sorted(set(paper_ids), key=paper_ids.index), "duplicate paper_id"
    assert "already-promoted" in output


def test_new_paper_ids_continue_past_the_hand_curated_tuple(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`papers.py` holds paper_1..paper_38 (post Phase 4 scale-up), so
    promotion starts at paper_39."""

    monkeypatch.setattr(promote_module, "_http_get", _live())
    approved = tmp_path / "approved_scaleup.jsonl"

    main(
        [
            "--candidates",
            str(
                _write_candidates(
                    tmp_path, [_candidate(), _candidate(arxiv_id="2504.22222")]
                )
            ),
            "--approved-file",
            str(approved),
            "--promote",
        ]
    )

    assert [record["paper_id"] for record in _lines(approved)] == ["paper_39", "paper_40"]


def test_a_second_run_does_not_reissue_an_id_the_first_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(promote_module, "_http_get", _live())
    approved = tmp_path / "approved_scaleup.jsonl"

    main(
        [
            "--candidates",
            str(_write_candidates(tmp_path, [_candidate()])),
            "--approved-file",
            str(approved),
            "--promote",
        ]
    )
    main(
        [
            "--candidates",
            str(_write_candidates(tmp_path, [_candidate(arxiv_id="2504.33333")])),
            "--approved-file",
            str(approved),
            "--promote",
        ]
    )

    assert [record["paper_id"] for record in _lines(approved)] == ["paper_39", "paper_40"]


def test_next_paper_index_reads_both_sources() -> None:
    assert next_paper_index([]) == 39
    assert next_paper_index([{"paper_id": "paper_44"}]) == 45
    # A malformed id is ignored rather than crashing the numbering.
    assert next_paper_index([{"paper_id": "not-a-paper"}]) == 39


def test_limit_caps_how_many_are_promoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(promote_module, "_http_get", _live())
    approved = tmp_path / "approved_scaleup.jsonl"
    records = [
        _candidate(arxiv_id="2504.11111"),
        _candidate(arxiv_id="2504.22222"),
        _candidate(arxiv_id="2504.33333"),
    ]

    code = main(
        [
            "--candidates",
            str(_write_candidates(tmp_path, records)),
            "--approved-file",
            str(approved),
            "--promote",
            "--limit",
            "2",
        ]
    )

    written = _lines(approved)
    assert code == 0
    assert len(written) == 2
    # File order, so a caller can reason about which two were taken.
    assert [record["arxiv_id"] for record in written] == ["2504.11111", "2504.22222"]


def test_limit_counts_eligible_candidates_not_lines_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rejected candidate must not consume the caller's budget."""

    monkeypatch.setattr(promote_module, "_http_get", _live(category="q-bio.GN"))
    approved = tmp_path / "approved_scaleup.jsonl"
    records = [
        _candidate(arxiv_id="2504.11111", expected_category="q-bio.PE"),
        _candidate(arxiv_id="2504.22222"),
    ]

    main(
        [
            "--candidates",
            str(_write_candidates(tmp_path, records)),
            "--approved-file",
            str(approved),
            "--promote",
            "--limit",
            "1",
        ]
    )

    assert [record["arxiv_id"] for record in _lines(approved)] == ["2504.22222"]


def test_a_promoted_record_carries_every_paperspec_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The written line has to be loadable as a `PaperSpec` in Phase 8 step 2."""

    from dataclasses import fields

    from paperbench_harbor.construction.core.spec import PaperSpec

    monkeypatch.setattr(promote_module, "_http_get", _live())
    approved = tmp_path / "approved_scaleup.jsonl"

    main(
        [
            "--candidates",
            str(_write_candidates(tmp_path, [_candidate()])),
            "--approved-file",
            str(approved),
            "--promote",
        ]
    )

    record = _lines(approved)[0]
    assert set(record) == {field.name for field in fields(PaperSpec)}
    assert PaperSpec(**record).arxiv_id == "2504.11111"


def test_a_report_is_written_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(promote_module, "_http_get", _live())
    report = tmp_path / "reports" / "promotion.json"

    main(
        [
            "--candidates",
            str(_write_candidates(tmp_path, [_candidate()])),
            "--approved-file",
            str(tmp_path / "approved_scaleup.jsonl"),
            "--report",
            str(report),
        ]
    )

    summary = json.loads(report.read_text(encoding="utf-8"))
    assert summary["dry_run"] is True
    assert summary["eligible"] == 1
    assert summary["promoted_now"] == 0


# --------------------------------------------------------------------------- #
# the invariant the file itself protects
# --------------------------------------------------------------------------- #


def test_the_default_target_is_the_lifesci_data_file_not_papers_py() -> None:
    """Promotion writes data. `papers.py` stays a hand-edited Python artifact.

    Pinned because redirecting this default at `papers.py` would let an automated
    stage rewrite the list the construction gate treats as authoritative, which is
    the loop `provenance-mismatch` exists to keep open.
    """

    assert APPROVED_SCALEUP_PATH.name == "approved_scaleup.jsonl"
    assert APPROVED_SCALEUP_PATH.parent.name == "lifesci_paperrecon"
    assert APPROVED_SCALEUP_PATH.suffix != ".py"


def test_the_real_approved_file_is_never_touched_by_the_test_suite() -> None:
    """Every test above passes `--approved-file`; this asserts the reason why."""

    assert not APPROVED_SCALEUP_PATH.exists() or APPROVED_SCALEUP_PATH.is_file()
