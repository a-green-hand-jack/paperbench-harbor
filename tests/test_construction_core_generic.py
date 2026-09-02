"""Proof that the core is generic, not merely that lifesci still passes.

`test_lifesci_paperrecon_validate.py` shows the extraction changed no biology
behaviour. It cannot show the split is real: a "plugin" that the core quietly
ignores would pass every one of those tests. So this module builds a second,
deliberately unbiological `DomainPlugin` — different paper types, a different
overview skeleton, different bounds, different prose — and asserts that the
same `core.validate` / `core.prompt` code produces *that* domain's contract.

The two plugins are chosen to disagree on purpose. `PHYSICS_PLUGIN` is an
in-test fixture, not a real domain (a real second domain waits for a real
second paper set, per the approved plan): its only job here is to be different
enough that any hard-coded biology in the core shows up as a failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperbench_harbor.adapters.paperwrite_bench.converter import OVERVIEW_FILENAMES
from paperbench_harbor.construction.core.plugin import DomainPlugin
from paperbench_harbor.construction.core.prompt import build_prompt
from paperbench_harbor.construction.core.spec import PaperSpec
from paperbench_harbor.construction.core.validate import validate_paper
from paperbench_harbor.construction.lifesci_paperrecon.plugin import LIFESCI_PLUGIN

SHORT = OVERVIEW_FILENAMES["short"]
LONG = OVERVIEW_FILENAMES["long"]

#: The in-test second domain. Nothing about it is biology, and its skeleton
#: shares only the mandatory `Title` heading with lifesci's.
PHYSICS_PLUGIN = DomainPlugin(
    name="physics",
    domain_label="physics",
    paper_types=("theory", "instrument"),
    overview_headings=(
        ("title",),
        ("open problem",),
        ("formalism", "derivation"),
        ("results",),
        ("physical significance",),
        ("outlook",),
    ),
    overview_skeleton_headings=(
        "Title",
        "Open Problem",
        "Formalism",
        "Results",
        "Physical Significance",
        "Outlook",
    ),
    significance_heading="Physical Significance",
    overview_bounds={SHORT: (200, 900), LONG: (400, 2000)},
    overview_length_targets="roughly 300-800 characters short, 500-1,800 long",
    agents_md_dir=Path("/nonexistent/physics/agents_md"),
    benchmark_intro="You are building one sample of **Physics-PaperRecon**.",
    stop_condition_examples="",
    overview_skeleton_rationale=" — physics papers are not shaped like ML papers",
    overview_content_guidance="State the observable, the regime and the uncertainty.",
    caption_example="figures/spectrum.pdf: Energy spectrum with 1-sigma bands ...",
    imagery_guidance="Expect spectra, Feynman diagrams and detector schematics.",
)

_SPEC = PaperSpec(
    paper_id="phys_1",
    arxiv_id="2601.00001",
    paper_type="theory",
    code_repo="https://github.com/example/lattice",
    expected_license="CC BY 4.0",
    expected_version="v1",
    expected_category="hep-th",
)

_MAIN_TEX = r"""
\documentclass{article}
\begin{document}
\section{Introduction}
The coupling runs~\cite{wilson1974}.
\section{Formalism}
\section{Results}
\section{Discussion}
\bibliographystyle{plain}
\bibliography{references}
\end{document}
"""

_TEMPLATE_TEX = r"""
\documentclass{article}
\begin{document}
\section{Introduction}
\section{Formalism}
\section{Results}
\section{Discussion}
\bibliographystyle{plain}
\bibliography{references}
\end{document}
"""


def _overview(headings: tuple[str, ...], scale: int = 3) -> str:
    body = "The lattice spacing was extrapolated to the continuum. " * scale
    title, *sections = headings
    text = f"# {title}\n\nA lattice study\n\n"
    return text + "\n".join(f"## {heading}\n\n{body}\n" for heading in sections)


def _provenance(**overrides: object) -> dict:
    record = {
        "title": "A lattice study",
        "arxiv_id": _SPEC.arxiv_id,
        "arxiv_version": _SPEC.expected_version,
        "arxiv_category": _SPEC.expected_category,
        "license_label": _SPEC.expected_license,
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "source_url": _SPEC.arxiv_eprint_url,
        "fetch_date": "2026-08-30",
        "code_repo": _SPEC.code_repo,
        "code_commit": "0123456789abcdef0123456789abcdef01234567",
        "code_license": "MIT License",
    }
    record.update(overrides)
    return record


@pytest.fixture
def agents_md_dir(tmp_path: Path) -> Path:
    """The physics domain's writing instructions, one per declared paper type."""

    directory = tmp_path / "agents_md"
    directory.mkdir()
    for paper_type in PHYSICS_PLUGIN.paper_types:
        (directory / f"AGENTS_{paper_type}.md").write_text("instructions\n", encoding="utf-8")
    return directory


@pytest.fixture
def plugin(agents_md_dir: Path) -> DomainPlugin:
    from dataclasses import replace

    return replace(PHYSICS_PLUGIN, agents_md_dir=agents_md_dir)


@pytest.fixture
def paper(tmp_path: Path) -> Path:
    """A physics sample that satisfies the physics plugin's contract."""

    root = tmp_path / "phys_1"
    original = root / "original"
    resources = root / "resources"
    original.mkdir(parents=True)
    (resources / "figures").mkdir(parents=True)
    (resources / "code").mkdir(parents=True)

    (original / "main.tex").write_text(_MAIN_TEX, encoding="utf-8")
    (original / "main.pdf").write_bytes(b"%PDF-1.5 fake")
    (original / "config.yaml").write_text(
        "type: theory\nnum_page: 12\ncolumn: 1column\nconference: arXiv hep-th\n",
        encoding="utf-8",
    )
    (original / "provenance.json").write_text(json.dumps(_provenance()), encoding="utf-8")

    (resources / "template.tex").write_text(_TEMPLATE_TEX, encoding="utf-8")
    (resources / SHORT).write_text(
        _overview(PHYSICS_PLUGIN.overview_skeleton_headings, 1), encoding="utf-8"
    )
    (resources / LONG).write_text(
        _overview(PHYSICS_PLUGIN.overview_skeleton_headings, 3), encoding="utf-8"
    )
    (resources / "references.bib").write_text(
        "@article{wilson1974, title={Confinement of quarks}, year={1974}}\n", encoding="utf-8"
    )
    (resources / "figures" / "spectrum.pdf").write_bytes(b"%PDF fake")
    (resources / "figure_summary.txt").write_text(
        "figures/spectrum.pdf: Energy spectrum with 1-sigma bands.\n", encoding="utf-8"
    )
    (resources / "table_summary.txt").write_text("No separate table assets.\n", encoding="utf-8")
    (resources / "code" / "lattice.c").write_text("int main(void){return 0;}\n", encoding="utf-8")
    return root


def _codes(paper: Path, plugin: DomainPlugin) -> set[str]:
    report = validate_paper(
        paper, _SPEC, plugin, build_root=paper.parent / "build", run_compile=False
    )
    return {issue.code for issue in report.issues}


# --------------------------------------------------------------------------- #
# the validator follows the plugin it is handed
# --------------------------------------------------------------------------- #


def test_a_physics_sample_passes_the_physics_plugin(paper: Path, plugin: DomainPlugin) -> None:
    report = validate_paper(
        paper, _SPEC, plugin, build_root=paper.parent / "build", run_compile=False
    )
    assert report.ok, report.summary()


def test_the_same_sample_fails_the_lifesci_plugin(paper: Path) -> None:
    """The evidence that `plugin` is load-bearing rather than decorative.

    Identical bytes on disk, a different plugin, a different verdict: the
    physics overview has no biology skeleton, and `theory` is not a lifesci
    paper type.
    """

    codes = _codes(paper, LIFESCI_PLUGIN)
    assert "overview-skeleton" in codes
    assert "config-type" in codes


def test_a_missing_domain_heading_fails_that_domain(paper: Path, plugin: DomainPlugin) -> None:
    """Drop *physics'* significance heading; the physics plugin must object."""

    without = tuple(
        heading
        for heading in PHYSICS_PLUGIN.overview_skeleton_headings
        if heading != PHYSICS_PLUGIN.significance_heading
    )
    (paper / "resources" / SHORT).write_text(_overview(without, 1), encoding="utf-8")
    assert "overview-skeleton" in _codes(paper, plugin)


def test_the_other_domains_heading_is_irrelevant(paper: Path, plugin: DomainPlugin) -> None:
    """An overview with no "Biological Significance" is fine outside biology."""

    text = (paper / "resources" / SHORT).read_text(encoding="utf-8")
    assert LIFESCI_PLUGIN.significance_heading.lower() not in text.lower()
    assert "overview-skeleton" not in _codes(paper, plugin)


def test_overview_bounds_come_from_the_plugin(paper: Path, plugin: DomainPlugin) -> None:
    """A length legal for lifesci (700-7000) is far over the physics ceiling."""

    long_enough_for_biology = _overview(PHYSICS_PLUGIN.overview_skeleton_headings, 5)
    floor, ceiling = LIFESCI_PLUGIN.overview_bounds[SHORT]
    assert floor <= len(long_enough_for_biology) <= ceiling
    assert len(long_enough_for_biology) > PHYSICS_PLUGIN.overview_bounds[SHORT][1]
    (paper / "resources" / SHORT).write_text(long_enough_for_biology, encoding="utf-8")
    assert "overview-length" in _codes(paper, plugin)


def test_paper_types_come_from_the_plugin(paper: Path, plugin: DomainPlugin) -> None:
    """A lifesci type is not a physics type, and vice versa."""

    (paper / "original" / "config.yaml").write_text(
        "type: computational\nnum_page: 12\ncolumn: 1column\nconference: arXiv hep-th\n",
        encoding="utf-8",
    )
    assert "config-type" in _codes(paper, plugin)


def test_writing_instructions_are_looked_up_in_the_plugins_directory(paper: Path) -> None:
    """`agents_md_dir` is the plugin's, not a hard-coded lifesci path."""

    codes = _codes(paper, PHYSICS_PLUGIN)  # its agents_md_dir does not exist
    assert "config-type" in codes


def test_domain_agnostic_checks_still_apply(paper: Path, plugin: DomainPlugin) -> None:
    """Genericity is not permissiveness: the core contract binds every domain."""

    (paper / "resources" / "main.tex").write_text("leak", encoding="utf-8")
    (paper / "resources" / "references.bib").write_text("", encoding="utf-8")
    codes = _codes(paper, plugin)
    assert "leakage" in codes
    assert "bib-empty" in codes


# --------------------------------------------------------------------------- #
# the prompt follows the plugin it is handed
# --------------------------------------------------------------------------- #


def test_the_prompt_carries_the_plugins_skeleton_and_prose() -> None:
    prompt = build_prompt(_SPEC, "/scratch/phys_1", PHYSICS_PLUGIN)

    assert PHYSICS_PLUGIN.benchmark_intro in prompt
    assert PHYSICS_PLUGIN.overview_skeleton() in prompt
    assert PHYSICS_PLUGIN.imagery_guidance in prompt
    assert PHYSICS_PLUGIN.caption_example in prompt
    assert PHYSICS_PLUGIN.overview_content_guidance in prompt
    assert "## Physical Significance" in prompt
    assert f"type: {_SPEC.paper_type}" in prompt


def test_no_biology_leaks_into_another_domains_prompt() -> None:
    prompt = build_prompt(_SPEC, "/scratch/phys_1", PHYSICS_PLUGIN)

    for biological in ("biolog", "life-sciences", "micrograph", "Dose-response"):
        assert biological.lower() not in prompt.lower(), biological
    assert "table_inventory.json" not in prompt


def test_core_invariants_survive_any_plugin() -> None:
    """A domain supplies prose; it cannot soften the contract."""

    prompt = build_prompt(_SPEC, "/scratch/phys_1", PHYSICS_PLUGIN)

    assert "pdflatex -interaction=nonstopmode -halt-on-error -no-shell-escape main.tex" in prompt
    assert "The leakage rule" in prompt
    assert "provenance.json" in prompt
    assert "code_license" in prompt
    assert "\\usepackage{natbib}" in prompt
    assert "CC BY 4.0" in prompt


def test_an_empty_stop_condition_fragment_leaves_the_prompt_well_formed() -> None:
    """Physics declares no carve-outs; lifesci declares one."""

    physics = build_prompt(_SPEC, "/scratch/phys_1", PHYSICS_PLUGIN)
    assert (
        "4. The arXiv ID, version or category does not match the expectations above.\n"
        "\n"
        "Do **not** substitute a different paper"
    ) in physics

    lifesci = build_prompt(_SPEC, "/scratch/phys_1", LIFESCI_PLUGIN)
    assert LIFESCI_PLUGIN.stop_condition_examples in lifesci
    assert (
        "4. The arXiv ID, version or category does not match the expectations above.\n"
        "\n"
        f"{LIFESCI_PLUGIN.stop_condition_examples}\n"
        "\n"
        "Do **not** substitute a different paper"
    ) in lifesci


# --------------------------------------------------------------------------- #
# the plugin refuses to be self-contradictory
# --------------------------------------------------------------------------- #


def test_a_plugin_whose_skeleton_its_own_validator_would_reject_is_refused() -> None:
    from dataclasses import replace

    with pytest.raises(ValueError, match="overview_headings"):
        replace(
            PHYSICS_PLUGIN,
            overview_headings=tuple(
                variants
                for variants in PHYSICS_PLUGIN.overview_headings
                if "physical significance" not in variants
            ),
        )

    with pytest.raises(ValueError, match="overview_skeleton_headings"):
        replace(PHYSICS_PLUGIN, significance_heading="Nowhere To Be Found")
