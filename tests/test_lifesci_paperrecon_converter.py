"""Harbor wrapping of the biology corpus.

These tests pin the behaviour that Phase 2 depends on: the *same* converter
produces LifeSci-PaperRecon tasks from biology identity metadata, without
forking the module and without changing anything for PaperWrite-Bench.
"""

from __future__ import annotations

import json
from pathlib import Path

from paperbench_harbor.adapters.lifesci_paperrecon.harbor import (
    BENCHMARK,
    TASK_ID_PREFIX,
    lifesci_paperrecon_conversion_config,
)
from paperbench_harbor.adapters.paperwrite_bench.converter import (
    DEFAULT_TAGS,
    PaperWriteBenchConversionConfig,
    convert_paperwrite_bench,
)

PAPERS = ("paper_1", "paper_2", "paper_3")
FORBIDDEN_ENV_NAMES = {
    "main.tex",
    "main.pdf",
    "config.yaml",
    "eval_points.json",
    "provenance.json",
    "source_manifest.json",
}


def _make_bio_paper(source: Path, paper_id: str, paper_type: str = "computational") -> None:
    """A minimal corpus in the layout the construction pipeline emits.

    Deliberately has **no** `eval_points.json`: the pilot ships the binary
    Harbor smoke check only.
    """
    paper_dir = source / paper_id
    original = paper_dir / "original"
    resources = paper_dir / "resources"
    original.mkdir(parents=True)
    resources.mkdir(parents=True)
    (original / "config.yaml").write_text(
        f"type: {paper_type}\nnum_page: 16\ncolumn: 1column\nconference: arXiv q-bio.PE\n",
        encoding="utf-8",
    )
    (original / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nGround truth\\end{document}\n",
        encoding="utf-8",
    )
    (original / "main.pdf").write_bytes(b"%PDF-1.4 fake")
    (original / "provenance.json").write_text(
        json.dumps({"arxiv_id": "2606.27607", "license_label": "CC BY 4.0"}),
        encoding="utf-8",
    )
    (resources / "template.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\section{Introduction}\n\\end{document}\n",
        encoding="utf-8",
    )
    (resources / "research_overview_short.md").write_text("# Short\n", encoding="utf-8")
    (resources / "research_overview_long.md").write_text("# Long\n", encoding="utf-8")
    (resources / "references.bib").write_text("@article{k1, title={T}}\n", encoding="utf-8")
    (resources / "figure_summary.txt").write_text(
        "figures/tree.png: A phylogenetic tree.\n", encoding="utf-8"
    )
    (resources / "table_summary.txt").write_text("(this paper has no tables)\n", encoding="utf-8")
    (resources / "figures").mkdir()
    (resources / "figures" / "tree.png").write_bytes(b"\x89PNG fake")
    (resources / "code").mkdir()
    (resources / "code" / "sim.py").write_text("x = 1\n", encoding="utf-8")


def _make_source(tmp_path: Path) -> Path:
    source = tmp_path / "bio-source"
    for paper_id in PAPERS:
        _make_bio_paper(source, paper_id)
    return source


def _convert(tmp_path: Path, **kwargs) -> Path:
    output = tmp_path / "out"
    config = lifesci_paperrecon_conversion_config(
        source=_make_source(tmp_path),
        output_dir=output,
        upstream_revision="test-rev",
        **kwargs,
    )
    assert convert_paperwrite_bench(config) == kwargs.get("limit", 3)
    return output


def test_bio_tasks_use_their_own_task_id_prefix(tmp_path: Path) -> None:
    output = _convert(tmp_path)
    for index in range(1, 4):
        assert (output / f"{TASK_ID_PREFIX}-{index:04d}").is_dir()
    assert not (output / "pwb-0001").exists()


def test_bio_task_has_the_expected_contract(tmp_path: Path) -> None:
    task_dir = _convert(tmp_path) / "lspr-0001"
    for relative in (
        "task.toml",
        "instruction.md",
        "environment/Dockerfile",
        "environment/materials/research_overview.md",
        "environment/materials/template.tex",
        "environment/materials/references.bib",
        "environment/materials/AGENTS.md",
        "environment/texmf/.keep",
        "solution/solve.sh",
        "solution/normalize.py",
        "solution/private/main.tex",
        "tests/test.sh",
        "tests/test_state.py",
        "tests/private/source_manifest.json",
        "tests/private/ground_truth.tex",
        "tests/private/ground_truth_sources/main.tex",
    ):
        assert (task_dir / relative).is_file(), relative


def test_bio_task_metadata_is_biology_flavoured(tmp_path: Path) -> None:
    task_toml = (_convert(tmp_path) / "lspr-0001" / "task.toml").read_text(encoding="utf-8")
    assert '"biology"' in task_toml
    assert '"life-sciences"' in task_toml
    assert '"lifesci-paperrecon"' in task_toml
    assert '"paperwrite-bench",' not in task_toml, (
        "bio tasks are a distinct benchmark and must not claim the "
        "paperwrite-bench tag, which would make the two datasets "
        "indistinguishable when filtering by tag"
    )
    assert 'category = "research-writing"' in task_toml


def test_bio_manifest_records_the_new_benchmark_name(tmp_path: Path) -> None:
    manifest = json.loads(
        (_convert(tmp_path) / "lspr-0002" / "tests" / "private" / "source_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["benchmark"] == BENCHMARK
    assert manifest["upstream_id"] == "paper_2"
    assert manifest["extra"]["task_id"] == "lspr-0002"
    assert manifest["extra"]["paper_type"] == "computational"
    assert manifest["extra"]["conference"] == "arXiv q-bio.PE"
    assert "source_archive_locator" in manifest["extra"]["release_provenance_requirements"]


def test_bio_uses_biology_writing_instructions(tmp_path: Path) -> None:
    agents = (
        _convert(tmp_path) / "lspr-0001" / "environment" / "materials" / "AGENTS.md"
    ).read_text(encoding="utf-8")
    assert "computational paper" in agents
    assert "Materials and Methods" in agents
    assert "life-sciences journal" in agents
    assert "top-tier ML conference" not in agents
    # The Harbor submission contract is identical to PaperWrite-Bench's.
    for phrase in (
        "`/workspace/materials/template.tex` and `/workspace/materials/references.bib` are read-only",
        "Write the completed document to `/workspace/submission/main.tex`",
        "Copy `/workspace/materials/references.bib` unchanged to `/workspace/submission/references.bib`",
        "Compile from `/workspace/submission/`; the verifier recompiles `main.tex` independently.",
    ):
        assert phrase in agents


def test_bio_ships_no_rubric_evaluator(tmp_path: Path) -> None:
    """The pilot is smoke-check only; no eval_points, grader or vendored code."""
    task_dir = _convert(tmp_path) / "lspr-0001"
    assert not (task_dir / "tests" / "grader_pwb.py").exists()
    assert not (task_dir / "tests" / "vendor").exists()
    assert not (task_dir / "tests" / "private" / "eval_points.json").exists()
    assert not (task_dir / "solution" / "private" / "eval_points.json").exists()
    test_sh = (task_dir / "tests" / "test.sh").read_text(encoding="utf-8")
    assert "grader" not in test_sh
    assert "reward.txt" in test_sh, "the binary smoke check still runs"


def test_bio_keeps_private_material_out_of_the_environment(tmp_path: Path) -> None:
    output = _convert(tmp_path)
    for index in range(1, 4):
        environment = output / f"lspr-{index:04d}" / "environment"
        names = {path.name for path in environment.rglob("*") if path.is_file()}
        assert names.isdisjoint(FORBIDDEN_ENV_NAMES)
        assert "research_overview_long.md" not in names


def test_bio_provenance_stays_verifier_only(tmp_path: Path) -> None:
    task_dir = _convert(tmp_path) / "lspr-0001"
    assert (task_dir / "tests" / "private" / "ground_truth_sources" / "provenance.json").is_file()
    assert not (task_dir / "environment" / "materials" / "provenance.json").exists()


def test_bio_redacts_direct_paper_pointers_but_keeps_local_style_bytes(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    paper = source / "paper_1"
    resources = paper / "resources"
    (resources / "template.tex").write_text(
        "\\documentclass{article}\n\\usepackage{arxiv}\n\\begin{document}\n\\end{document}\n",
        encoding="utf-8",
    )
    local_style = resources / "arxiv.sty"
    local_style.write_text(
        "\\NeedsTeXFormat{LaTeX2e}\n\\RequirePackage{natbib}\n",
        encoding="utf-8",
    )
    (resources / "code" / "README.md").write_text(
        "Paper: [arXiv:2606.27607](https://arxiv.org/abs/2606.27607)\n"
        "DOI: https://doi.org/10.48550/arXiv.2606.27607\n",
        encoding="utf-8",
    )
    (resources / "code" / "nested").mkdir()
    (resources / "code" / "nested" / "README.md").write_text(
        "Public implementation notes.\n", encoding="utf-8"
    )

    output = tmp_path / "out"
    convert_paperwrite_bench(
        lifesci_paperrecon_conversion_config(
            source=source,
            output_dir=output,
            upstream_revision="test-rev",
            limit=1,
        )
    )

    task = output / "lspr-0001"
    assert (task / "environment" / "texmf" / "arxiv.sty").read_bytes() == local_style.read_bytes()
    readme = (task / "environment" / "materials" / "code" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "2606.27607" not in readme
    assert "arxiv.org/abs" not in readme
    assert "doi.org/10.48550" not in readme
    assert "source-paper-url-withheld" in readme
    assert (task / "environment" / "materials" / "code" / "nested" / "README.md").is_file()


def test_bio_conversion_is_deterministic(tmp_path: Path) -> None:
    source = _make_source(tmp_path)

    def digest(output: Path) -> list[tuple[str, int]]:
        return sorted(
            (path.relative_to(output).as_posix(), path.stat().st_size)
            for path in output.rglob("*")
            if path.is_file()
        )

    first, second = tmp_path / "a", tmp_path / "b"
    for output in (first, second):
        convert_paperwrite_bench(
            lifesci_paperrecon_conversion_config(
                source=source, output_dir=output, upstream_revision="rev", overwrite=True
            )
        )
    assert digest(first) == digest(second)


# --------------------------------------------------------------------------- #
# regression guard: PaperWrite-Bench defaults are untouched
# --------------------------------------------------------------------------- #


def test_paperwrite_bench_defaults_are_unchanged() -> None:
    config = PaperWriteBenchConversionConfig(source=Path("."), output_dir=Path("."))
    assert config.benchmark == "PaperWrite-Bench"
    assert config.task_id_prefix == "pwb"
    assert config.tags == DEFAULT_TAGS
    assert config.include_official_grader is True
    assert config.agents_md_dir.name == "agents_md"
    assert "paperwrite_bench" in config.agents_md_dir.as_posix()


def test_bio_config_differs_from_the_defaults_where_it_should() -> None:
    config = lifesci_paperrecon_conversion_config(
        source=Path("."), output_dir=Path("."), upstream_revision="rev"
    )
    assert config.benchmark == "LifeSci-PaperRecon"
    assert config.task_id_prefix == "lspr"
    assert config.include_official_grader is False
    assert "lifesci_paperrecon" in config.agents_md_dir.as_posix()
    assert config.overview == "short"
