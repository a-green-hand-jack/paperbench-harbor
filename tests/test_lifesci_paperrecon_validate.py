"""The construction gate's job is to be un-negotiable, so it is tested directly.

These tests deliberately do **not** compile anything (`run_compile=False`):
LaTeX availability is a property of the build host, not of the contract, and a
structural check that only runs where TeX Live is installed would stop being
run at all. The compile path is exercised for real by the pilot build, which
reproduces the oracle rather than approximating it.

Each test breaks exactly one thing about an otherwise-valid sample, so a
failure names the check that regressed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperbench_harbor.construction.core.spec import PaperSpec
from paperbench_harbor.construction.core.validate import validate_paper
from paperbench_harbor.construction.lifesci_paperrecon.papers import PILOT_BY_ID
from paperbench_harbor.construction.lifesci_paperrecon.plugin import LIFESCI_PLUGIN

SPEC = PILOT_BY_ID["paper_1"]

_MAIN_TEX = r"""
\documentclass{article}
\usepackage{graphicx}
\begin{document}
\section{Introduction}
Phylogenetic inference is expensive~\cite{felsenstein1981}.
\begin{figure}\includegraphics{figures/tree.png}\caption{A tree.}\end{figure}
\section{Materials and Methods}
We implemented the peeling algorithm on GPUs, following \cite{ayres2012}.
\section{Results}
Throughput improved by a factor of eleven on the benchmark alignments.
\section{Discussion}
The speedup holds for large state spaces.
\bibliographystyle{plain}
\bibliography{references}
\end{document}
"""

_TEMPLATE_TEX = r"""
\documentclass{article}
\begin{document}
\section{Introduction}
\section{Materials and Methods}
\section{Results}
\section{Discussion}
\bibliographystyle{plain}
\bibliography{references}
\end{document}
"""

_BIB = """
@article{felsenstein1981, title={Evolutionary trees from DNA sequences}, year={1981}}
@article{ayres2012, title={BEAGLE}, year={2012}}
"""


def _overview(scale: int) -> str:
    body = "Each simulated alignment was replicated to convergence. " * scale
    return (
        "# Title\n\nBEAGLE 4.1\n\n"
        "## Research Question or Hypothesis\n\n" + body +
        "\n## Approach\n\n" + body +
        "\n## Key Findings\n\n" + body +
        "\n## Biological Significance\n\n" + body +
        "\n## Takeaway\n\n" + body
    )


def _provenance(**overrides: object) -> dict:
    record = {
        "title": "BEAGLE 4.1",
        "arxiv_id": SPEC.arxiv_id,
        "arxiv_version": SPEC.expected_version,
        "arxiv_category": SPEC.expected_category,
        "license_label": SPEC.expected_license,
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "source_url": SPEC.arxiv_eprint_url,
        "fetch_date": "2026-08-30",
        "code_repo": SPEC.code_repo,
        "code_commit": "0123456789abcdef0123456789abcdef01234567",
        "code_license": "MIT License",
    }
    record.update(overrides)
    return record


@pytest.fixture
def paper(tmp_path: Path) -> Path:
    """A sample that passes every structural check."""
    root = tmp_path / "paper_1"
    original = root / "original"
    resources = root / "resources"
    original.mkdir(parents=True)
    (resources / "figures").mkdir(parents=True)
    (resources / "code").mkdir(parents=True)

    (original / "main.tex").write_text(_MAIN_TEX, encoding="utf-8")
    (original / "main.pdf").write_bytes(b"%PDF-1.5 fake")
    (original / "config.yaml").write_text(
        "type: computational\nnum_page: 14\ncolumn: 1column\nconference: arXiv q-bio.PE\n",
        encoding="utf-8",
    )
    (original / "provenance.json").write_text(json.dumps(_provenance()), encoding="utf-8")

    (resources / "template.tex").write_text(_TEMPLATE_TEX, encoding="utf-8")
    (resources / "research_overview_short.md").write_text(_overview(4), encoding="utf-8")
    (resources / "research_overview_long.md").write_text(_overview(20), encoding="utf-8")
    (resources / "references.bib").write_text(_BIB, encoding="utf-8")
    (resources / "figures" / "tree.png").write_bytes(b"\x89PNG fake")
    (resources / "figure_summary.txt").write_text(
        "figures/tree.png: Maximum-likelihood phylogeny of the 64 taxa.\n", encoding="utf-8"
    )
    (resources / "table_summary.txt").write_text(
        "This paper has no table assets; its tables are inline.\n", encoding="utf-8"
    )
    (resources / "code" / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (resources / "code" / "peel.c").write_text("int main(void){return 0;}\n", encoding="utf-8")
    return root


def _validate(paper: Path, spec: PaperSpec = SPEC):
    return validate_paper(
        paper, spec, LIFESCI_PLUGIN, build_root=paper.parent / "build", run_compile=False
    )


def _codes(paper: Path) -> set[str]:
    return {issue.code for issue in _validate(paper).issues}


def test_a_well_formed_sample_passes(paper: Path) -> None:
    report = _validate(paper)
    assert report.ok, report.summary()


def test_skipping_compilation_is_recorded_not_silent(paper: Path) -> None:
    """"Not checked" must never read as "passed"."""
    assert _validate(paper).compile_skipped_reason


def test_a_missing_contract_file_fails(paper: Path) -> None:
    (paper / "resources" / "references.bib").unlink()
    assert "missing-resource" in _codes(paper)


def test_an_empty_code_tree_fails(paper: Path) -> None:
    """Public code is a selection criterion, so its absence is a hard failure."""
    for path in (paper / "resources" / "code").iterdir():
        path.unlink()
    assert "missing-resource-dir" in _codes(paper)


def test_ground_truth_in_the_public_tree_fails(paper: Path) -> None:
    (paper / "resources" / "main.tex").write_text("leak", encoding="utf-8")
    assert "leakage" in _codes(paper)


def test_ground_truth_inside_the_code_checkout_is_tolerated(paper: Path) -> None:
    """A third-party repo may legitimately contain a file called main.tex."""
    (paper / "resources" / "code" / "main.tex").write_text("upstream file", encoding="utf-8")
    assert "leakage" not in _codes(paper)


def test_a_substituted_paper_fails(paper: Path) -> None:
    provenance = paper / "original" / "provenance.json"
    provenance.write_text(json.dumps(_provenance(arxiv_id="1234.56789")), encoding="utf-8")
    assert "provenance-mismatch" in _codes(paper)


def test_a_non_redistributable_license_fails(paper: Path) -> None:
    provenance = paper / "original" / "provenance.json"
    provenance.write_text(
        json.dumps(_provenance(license_label="arXiv perpetual, non-exclusive license")),
        encoding="utf-8",
    )
    assert "provenance-license" in _codes(paper)


def test_a_missing_provenance_field_fails(paper: Path) -> None:
    record = _provenance()
    del record["code_commit"]
    (paper / "original" / "provenance.json").write_text(json.dumps(record), encoding="utf-8")
    assert "provenance-field" in _codes(paper)


def test_an_unlicensed_code_repo_is_recorded_but_does_not_block(paper: Path) -> None:
    """Owner decision, 2026-08-31: an unlicensed code repo no longer stops a build.

    The paper's *own* license is still enforced; only the code repository's is
    now advisory. Since nothing blocks on it any more, the one remaining
    guarantee is that the finding is written down — Phase 5's dataset card
    reads `code_license` to state per-sample redistribution terms, and a
    silently-absent field would make an unlicensed repo indistinguishable from
    a licensed one.
    """
    (paper / "original" / "provenance.json").write_text(
        json.dumps(_provenance(code_license="none declared")), encoding="utf-8"
    )
    report = _validate(paper)
    assert report.ok, report.summary()


def test_an_unrecorded_code_license_fails(paper: Path) -> None:
    record = _provenance()
    del record["code_license"]
    (paper / "original" / "provenance.json").write_text(json.dumps(record), encoding="utf-8")
    assert "provenance-field" in _codes(paper)


def test_the_wrong_paper_type_fails(paper: Path) -> None:
    (paper / "original" / "config.yaml").write_text(
        "type: experimental\nnum_page: 14\ncolumn: 1column\nconference: arXiv q-bio.PE\n",
        encoding="utf-8",
    )
    assert "config-type" in _codes(paper)


def test_a_malformed_column_fails(paper: Path) -> None:
    (paper / "original" / "config.yaml").write_text(
        "type: computational\nnum_page: 14\ncolumn: two\nconference: arXiv q-bio.PE\n",
        encoding="utf-8",
    )
    assert "config-column" in _codes(paper)


def test_a_template_carrying_the_paper_text_fails(paper: Path) -> None:
    (paper / "resources" / "template.tex").write_text(_MAIN_TEX, encoding="utf-8")
    codes = _codes(paper)
    assert "template-leaks-citations" in codes
    assert "template-leaks-prose" in codes


def test_a_template_without_a_skeleton_fails(paper: Path) -> None:
    (paper / "resources" / "template.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\end{document}\n", encoding="utf-8"
    )
    assert "template-no-skeleton" in _codes(paper)


def test_an_overview_missing_the_biology_skeleton_fails(paper: Path) -> None:
    (paper / "resources" / "research_overview_short.md").write_text(
        "# Title\n\n## Motivation\n\n## Proposed Method\n\n## Contributions\n" + "x " * 500,
        encoding="utf-8",
    )
    assert "overview-skeleton" in _codes(paper)


def test_an_overview_that_is_really_the_paper_fails(paper: Path) -> None:
    (paper / "resources" / "research_overview_short.md").write_text(
        _overview(4) + "\n" + _MAIN_TEX, encoding="utf-8"
    )
    assert "overview-is-latex" in _codes(paper)


def test_a_long_overview_that_is_not_longer_fails(paper: Path) -> None:
    (paper / "resources" / "research_overview_long.md").write_text(_overview(4), encoding="utf-8")
    assert "overview-ordering" in _codes(paper)


def test_an_uncaptioned_figure_fails(paper: Path) -> None:
    (paper / "resources" / "figures" / "gel.png").write_bytes(b"\x89PNG fake")
    assert "summary-incomplete" in _codes(paper)


def test_a_citation_absent_from_the_bibliography_fails(paper: Path) -> None:
    """The exact check the verifier runs; the oracle cannot pass without it."""
    (paper / "resources" / "references.bib").write_text(
        "@article{felsenstein1981, title={T}, year={1981}}\n", encoding="utf-8"
    )
    assert "citations-unresolved" in _codes(paper)


def test_citations_hidden_behind_an_input_are_still_checked(paper: Path) -> None:
    original = paper / "original"
    (original / "body.tex").write_text("Text \\cite{nowhere2026}.\n", encoding="utf-8")
    (original / "main.tex").write_text(
        _MAIN_TEX.replace("\\section{Results}", "\\input{body}\n\\section{Results}"),
        encoding="utf-8",
    )
    assert "citations-unresolved" in _codes(paper)


def test_a_failing_report_renders_actionable_feedback(paper: Path) -> None:
    (paper / "resources" / "references.bib").write_text("", encoding="utf-8")
    report = _validate(paper)
    feedback = report.agent_feedback()
    assert "bib-empty" in feedback
    assert "->" in feedback, "the agent is told what to do, not only what broke"
