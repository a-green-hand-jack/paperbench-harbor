from __future__ import annotations

from pathlib import Path

import pytest

from paperbench_harbor.adapters.paperwrite_bench.converter import (
    PaperWriteBenchConversionConfig,
    convert_paperwrite_bench,
)

PAPERS = ("paper_1", "paper_2", "paper_3")
FORBIDDEN_ENV_NAMES = {"main.tex", "main.pdf", "config.yaml", "eval_points.json"}


def _make_paper(source: Path, paper_id: str) -> None:
    paper_dir = source / paper_id
    original = paper_dir / "original"
    resources = paper_dir / "resources"
    original.mkdir(parents=True)
    resources.mkdir(parents=True)
    (original / "config.yaml").write_text(
        "type: method\nnum_page: 9\ncolumn: 2column\nconference: NeurIPS25\n",
        encoding="utf-8",
    )
    (original / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\nHello world\\end{document}\n",
        encoding="utf-8",
    )
    (original / "main.pdf").write_bytes(b"%PDF-1.4 fake")
    (resources / "template.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\end{document}\n",
        encoding="utf-8",
    )
    (resources / "research_overview_short.md").write_text("# Overview short\n", encoding="utf-8")
    (resources / "research_overview_long.md").write_text("# Overview long\n", encoding="utf-8")
    (resources / "references.bib").write_text("@article{key1, title={T}}\n", encoding="utf-8")
    (resources / "figure_summary.txt").write_text("figures/a.png: A\n", encoding="utf-8")
    (resources / "table_summary.txt").write_text("tables/a.tex: A\n", encoding="utf-8")
    (resources / "eval_points.json").write_text('{"sections": []}', encoding="utf-8")
    (resources / "figures").mkdir()
    (resources / "figures" / "a.png").write_bytes(b"\x89PNG fake")
    (resources / "tables").mkdir()
    (resources / "tables" / "a.tex").write_text("\\begin{table}\\end{table}\n", encoding="utf-8")
    (resources / "code").mkdir()
    (resources / "code" / "x.py").write_text("x = 1\n", encoding="utf-8")


def _make_source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    for paper_id in PAPERS:
        _make_paper(source, paper_id)
    return source


def _environment_names(task_dir: Path) -> set[str]:
    names = set()
    for path in (task_dir / "environment").rglob("*"):
        if path.is_file():
            names.add(path.name)
    return names


def test_convert_creates_expected_structure(tmp_path: Path) -> None:
    config = PaperWriteBenchConversionConfig(
        source=_make_source(tmp_path), output_dir=tmp_path / "out", overview="short"
    )
    assert convert_paperwrite_bench(config) == 3

    for index, paper_id in enumerate(PAPERS, start=1):
        task_dir = tmp_path / "out" / f"pwb-{index:04d}"
        assert (task_dir / "task.toml").is_file()
        assert (task_dir / "instruction.md").is_file()
        assert (task_dir / "environment" / "Dockerfile").is_file()
        assert (task_dir / "environment" / "materials" / "research_overview.md").is_file()
        assert (task_dir / "environment" / "materials" / "template.tex").is_file()
        assert (task_dir / "environment" / "materials" / "references.bib").is_file()
        assert (task_dir / "solution" / "solve.sh").is_file()
        assert (task_dir / "solution" / "private" / "main.tex").is_file()
        assert (task_dir / "tests" / "test.sh").is_file()
        assert (task_dir / "tests" / "test_state.py").is_file()
        assert (task_dir / "tests" / "private" / "eval_points.json").is_file()
        assert (task_dir / "tests" / "private" / "source_manifest.json").is_file()

        manifest = task_dir / "tests" / "private" / "source_manifest.json"
        assert f'"upstream_id": "{paper_id}"' in manifest.read_text(encoding="utf-8")

    dataset_manifest = (tmp_path / "out" / "dataset-manifest.jsonl").read_text(encoding="utf-8")
    assert '"task_id": "pwb-0003"' in dataset_manifest
    assert '"upstream_paper_id": "paper_3"' in dataset_manifest


def test_conversion_is_idempotent(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    output = tmp_path / "out"
    config = PaperWriteBenchConversionConfig(source=source, output_dir=output, overview="short")
    assert convert_paperwrite_bench(config) == 3
    assert convert_paperwrite_bench(config) == 0
    assert convert_paperwrite_bench(
        PaperWriteBenchConversionConfig(source=source, output_dir=output, overwrite=True)
    ) == 3


def test_no_private_material_in_environment(tmp_path: Path) -> None:
    config = PaperWriteBenchConversionConfig(
        source=_make_source(tmp_path), output_dir=tmp_path / "out", overview="short"
    )
    convert_paperwrite_bench(config)
    for index in range(1, 4):
        task_dir = tmp_path / "out" / f"pwb-{index:04d}"
        names = _environment_names(task_dir)
        assert names.isdisjoint(FORBIDDEN_ENV_NAMES)
        assert "research_overview_long.md" not in names


def test_limit_selects_first_papers(tmp_path: Path) -> None:
    config = PaperWriteBenchConversionConfig(
        source=_make_source(tmp_path), output_dir=tmp_path / "out", overview="short", limit=2
    )
    assert convert_paperwrite_bench(config) == 2
    assert (tmp_path / "out" / "pwb-0001").is_dir()
    assert (tmp_path / "out" / "pwb-0002").is_dir()
    assert not (tmp_path / "out" / "pwb-0003").exists()


def test_unsupported_overview_raises(tmp_path: Path) -> None:
    config = PaperWriteBenchConversionConfig(
        source=_make_source(tmp_path), output_dir=tmp_path / "out", overview="medium"
    )
    with pytest.raises(ValueError, match="Unsupported overview"):
        convert_paperwrite_bench(config)
