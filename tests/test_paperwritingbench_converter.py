from __future__ import annotations

import re
from pathlib import Path

import pytest

from paperbench_harbor.adapters.paperwritingbench.converter import (
    PaperWritingBenchConversionConfig,
    convert_paperwritingbench,
)

FORBIDDEN_ENV_NAMES = {"idea_dense.md", "main.pdf", "source_manifest.json"}


def _make_paper(source: Path, venue: str, paper_id: str) -> None:
    paper_dir = source / venue / "papers" / paper_id
    raw = paper_dir / "raw_materials"
    raw.mkdir(parents=True)
    (paper_dir / f"{paper_id}.pdf").write_bytes(b"%PDF-1.4 fake")
    (raw / "idea_sparse.md").write_text("# Title\n## Problem Statement\nA problem.\n", encoding="utf-8")
    (raw / "idea_dense.md").write_text("# Dense idea\n", encoding="utf-8")
    (raw / "experimental_log.md").write_text(
        "## Experimental Setup\n| Metric | $P(a|b)$ |\n| :--- | :--- |\n| Result | 1 |\n",
        encoding="utf-8",
    )
    (raw / "figures").mkdir()
    (raw / "figures" / "figure_1.png").write_bytes(b"\x89PNG fake")
    (raw / "figures" / "info.json").write_text(
        '[{"name": "figure_1.png", "caption": "A caption."}]', encoding="utf-8"
    )
    (raw / "original_paper_gt_citations_gpt-5.json").write_text(
        '{"citation_info": [{"citation_text": "Alice. T. 2024.", '
        '"extracted_paper_title": "T", "fetched_paper_title": "T"}], "p0_ids": [], "p1_ids": []}',
        encoding="utf-8",
    )


def _make_source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    _make_paper(source, "cvpr2025", "cvpr2025_aaaa")
    _make_paper(source, "cvpr2025", "cvpr2025_bbbb")
    _make_paper(source, "iclr2025", "iclr2025_cccc")
    return source


def test_convert_creates_expected_structure(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    config = PaperWritingBenchConversionConfig(
        source=source, output_dir=tmp_path / "out", protocol="sparse-plotoff"
    )
    assert convert_paperwritingbench(config) == 3

    task_dir = tmp_path / "out" / "pwbw-0001"
    assert (task_dir / "task.toml").is_file()
    assert (task_dir / "instruction.md").is_file()
    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
    assert "`/workspace/materials/conference_template/template.tex` and the\n   supporting style/guideline files as read-only inputs" in instruction
    assert "write the completed document to\n   `/workspace/submission/main.tex`" in instruction
    assert "fill it" not in instruction
    assert "main.tex` is the\nauthoritative compilation entry point, not necessarily the only LaTeX source\nfile" in instruction
    assert "braced `\\input{...}` or `\\include{...}` commands to\nreference files inside `/workspace/submission/`, using paths relative to the\nsubmission root" in instruction
    assert "every source dependency\nrequired by `main.tex` into `/workspace/submission/`" in instruction
    assert "Do not rely on absolute\npaths, parent-directory paths, or files under `/workspace/materials/`" in instruction
    assert "2024-10-01" in instruction
    assert "credential-free Semantic Scholar fallback" in instruction
    assert "Use every provided figure exactly once, without merging or grouping them" in instruction
    assert "Do not create, generate, or include any figures or plots\n   beyond the provided assets" in instruction
    materials = task_dir / "environment" / "materials"
    assert (materials / "idea_sparse.md").is_file()
    assert (materials / "experimental_log.md").is_file()
    assert (materials / "figures" / "figure_1.png").is_file()
    assert (materials / "experimental_log.md").read_text(encoding="utf-8") == (
        source
        / "cvpr2025"
        / "papers"
        / "cvpr2025_aaaa"
        / "raw_materials"
        / "experimental_log.md"
    ).read_text(encoding="utf-8")
    assert (task_dir / "environment" / "texmf" / ".keep").is_file()
    assert (materials / "conference_template" / "template.tex").is_file()
    conference_template = (materials / "conference_template" / "template.tex").read_text(
        encoding="utf-8"
    )
    assert "Anonymous Authors" in conference_template
    assert "Ambitious AI Researcher" not in conference_template
    assert "\\usepackage[review]{cvpr}" in conference_template
    upstream = task_dir / "environment" / "paper_orchestra"
    assert {
        path.relative_to(upstream).as_posix()
        for path in upstream.rglob("*")
        if path.is_file()
    } == {
        "LICENSE",
        "methods/agents/literature_review_agent.py",
        "methods/prompts/literature_review_agent.py",
        "utils/gemini_utils.py",
        "utils/prompt_utils.py",
        "utils/scholar_utils.py",
    }
    assert (task_dir / "environment" / "paper_orchestra_sidecar.py").is_file()
    assert (task_dir / "environment" / "entrypoint.sh").is_file()
    assert (task_dir / "solution" / "solve.sh").is_file()
    assert (task_dir / "solution" / "oracle_pwbw.py").is_file()
    assert (task_dir / "solution" / "private" / "cvpr2025_aaaa.pdf").is_file()
    assert (task_dir / "tests" / "private" / "idea_dense.md").is_file()
    assert (task_dir / "tests" / "private" / "source_manifest.json").is_file()

    names = {
        path.name
        for path in (task_dir / "environment").rglob("*")
        if path.is_file()
    }
    assert names.isdisjoint(FORBIDDEN_ENV_NAMES)
    assert not any(name.startswith("original_paper_gt_citations") for name in names)

    dockerfile = (task_dir / "environment" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY paper_orchestra/ /workspace/paper_orchestra/" in dockerfile
    assert "COPY paper_orchestra_sidecar.py /workspace/paper_orchestra_sidecar.py" in dockerfile
    sources = re.findall(r"^COPY\s+(\S+?)/?\s+/", dockerfile, flags=re.MULTILINE)
    environment = task_dir / "environment"
    assert all((environment / source).exists() for source in sources)

    grader = (
        Path(__file__).parents[1]
        / "src"
        / "paperbench_harbor"
        / "common"
        / "templates"
        / "grader_pwb.py.j2"
    ).read_text(encoding="utf-8")
    assert "hal_verification_dir=gt_root" in grader

    dataset_manifest = (tmp_path / "out" / "dataset-manifest.jsonl").read_text(encoding="utf-8")
    assert '"task_id": "pwbw-0003"' in dataset_manifest
    assert '"upstream_paper_id": "iclr2025_cccc"' in dataset_manifest


def test_venue_ordering_is_deterministic(tmp_path: Path) -> None:
    config = PaperWritingBenchConversionConfig(
        source=_make_source(tmp_path), output_dir=tmp_path / "out", protocol="sparse-plotoff"
    )
    assert convert_paperwritingbench(config) == 3
    assert convert_paperwritingbench(config) == 0
    assert convert_paperwritingbench(
        PaperWritingBenchConversionConfig(
            source=config.source,
            output_dir=config.output_dir,
            protocol="sparse-plotoff",
            overwrite=True,
        )
    ) == 3


def test_limit_selects_first_papers(tmp_path: Path) -> None:
    config = PaperWritingBenchConversionConfig(
        source=_make_source(tmp_path),
        output_dir=tmp_path / "out",
        protocol="sparse-plotoff",
        limit=2,
    )
    assert convert_paperwritingbench(config) == 2
    assert not (tmp_path / "out" / "pwbw-0003").exists()


def test_unsupported_protocol_is_not_advertised_as_supported(tmp_path: Path) -> None:
    config = PaperWritingBenchConversionConfig(
        source=_make_source(tmp_path),
        output_dir=tmp_path / "out",
        protocol="dense-plotoff",
    )
    with pytest.raises(ValueError, match="Unsupported protocol"):
        convert_paperwritingbench(config)


def test_unknown_protocol_raises(tmp_path: Path) -> None:
    config = PaperWritingBenchConversionConfig(
        source=_make_source(tmp_path), output_dir=tmp_path / "out", protocol="nope"
    )
    with pytest.raises(ValueError):
        convert_paperwritingbench(config)
