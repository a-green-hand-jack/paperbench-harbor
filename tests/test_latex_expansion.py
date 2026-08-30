import sys
from pathlib import Path

VENDOR = Path(__file__).parents[1] / "src" / "paperbench_harbor" / "vendor"
sys.path.insert(0, str(VENDOR))

from paper_recon.common.latex import expand_latex_source, extract_figure_reference_labels
from paper_recon.evaluation.evaluate_citation import evaluate_citation_f1


def _submission(tmp_path: Path) -> Path:
    root = tmp_path / "submission"
    (root / "sections").mkdir(parents=True)
    (root / "figures").mkdir()
    (root / "main.tex").write_text(
        r"\documentclass{article}\begin{document}\input{sections/body}\end{document}",
        encoding="utf-8",
    )
    (root / "sections" / "body.tex").write_text(
        r"\input{sections/nested} \section{Body} Cited text \cite{nested-key}. "
        r"\begin{figure}\includegraphics{figures/result.png}\caption{Result}\end{figure}",
        encoding="utf-8",
    )
    (root / "sections" / "nested.tex").write_text(r"Nested source.", encoding="utf-8")
    (root / "references.bib").write_text("@article{nested-key, title={Nested}}\n", encoding="utf-8")
    return root


def test_expands_nested_sources_for_citation_smoke_test(tmp_path: Path) -> None:
    root = _submission(tmp_path)
    expanded = expand_latex_source(root / "main.tex")
    assert "nested-key" in expanded
    assert "\\section{Body}" in expanded
    assert "figures/result.png" in expanded
    assert "Nested source." in expanded

    gt = root / "gt.tex"
    gt.write_text(r"\documentclass{article}\begin{document}\cite{nested-key}\end{document}")
    result = evaluate_citation_f1(gt, root / "main.tex")
    assert result["common_keys"] == ["nested-key"]


def test_citation_evaluator_catches_broad_commands_and_invented_keys(tmp_path: Path) -> None:
    root = _submission(tmp_path)
    (root / "sections" / "body.tex").write_text(
        r"\citeauthor{nested-key} \citeyear[see][p. 2]{nested-key} "
        r"\citep{invented-key}",
        encoding="utf-8",
    )
    gt = root / "gt.tex"
    gt.write_text(r"\citeauthor{nested-key} \citeyear{nested-key}", encoding="utf-8")
    result = evaluate_citation_f1(gt, root / "main.tex")
    assert result["common_keys"] == ["nested-key"]
    assert result["hallucinated_keys"] == ["invented-key"]


def test_figure_references_support_subref_cref_and_comma_lists() -> None:
    text = r"\cref{fig:one,fig:two} and \subref{fig:three} \Cref{fig:four}."
    assert extract_figure_reference_labels(text) == [
        "fig:one",
        "fig:two",
        "fig:three",
        "fig:four",
    ]


def test_expander_does_not_read_outside_submission(tmp_path: Path) -> None:
    root = _submission(tmp_path)
    outside = tmp_path / "outside.tex"
    outside.write_text(r"\section{Secret}")
    (root / "main.tex").write_text(r"\input{../outside.tex}", encoding="utf-8")
    assert "Secret" not in expand_latex_source(root / "main.tex")
