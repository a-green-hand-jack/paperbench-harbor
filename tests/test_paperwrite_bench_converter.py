from __future__ import annotations

import re
from pathlib import Path

import pytest

from paperbench_harbor.adapters.paperwrite_bench.converter import (
    PaperWriteBenchConversionConfig,
    convert_paperwrite_bench,
)

PAPERS = ("paper_1", "paper_2", "paper_3")
FORBIDDEN_ENV_NAMES = {"main.tex", "main.pdf", "config.yaml", "eval_points.json"}


def _make_paper(source: Path, paper_id: str, paper_type: str = "method") -> None:
    paper_dir = source / paper_id
    original = paper_dir / "original"
    resources = paper_dir / "resources"
    original.mkdir(parents=True)
    resources.mkdir(parents=True)
    (original / "config.yaml").write_text(
        f"type: {paper_type}\nnum_page: 9\ncolumn: 2column\nconference: NeurIPS25\n",
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


def _make_source(tmp_path: Path, paper_type: str = "method") -> Path:
    source = tmp_path / "source"
    for paper_id in PAPERS:
        _make_paper(source, paper_id, paper_type)
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
        assert (task_dir / "environment" / "materials" / "AGENTS.md").is_file()
        assert (task_dir / "environment" / "texmf" / ".keep").is_file()
        agents = (task_dir / "environment" / "materials" / "AGENTS.md").read_text(encoding="utf-8")
        assert "Always include references within" not in agents
        assert "do not embed it with a `filecontents` environment" in agents
        assert "external `references.bib`" in agents
        assert "/workspace/materials/template.tex` and `/workspace/materials/references.bib` are read-only" in agents
        assert "Write the completed document to `/workspace/submission/main.tex`" in agents
        assert "Copy `/workspace/materials/references.bib` unchanged to `/workspace/submission/references.bib`" in agents
        assert "Copy referenced figure assets from `/workspace/materials/figures/` to `/workspace/submission/figures/`" in agents
        assert "Compile from `/workspace/submission/`; the verifier recompiles `main.tex` independently." in agents
        assert (task_dir / "solution" / "solve.sh").is_file()
        assert (task_dir / "solution" / "private" / "main.tex").is_file()
        assert (task_dir / "tests" / "test.sh").is_file()
        assert (task_dir / "tests" / "test_state.py").is_file()
        assert (task_dir / "tests" / "private" / "eval_points.json").is_file()
        assert (task_dir / "tests" / "private" / "source_manifest.json").is_file()
        assert (task_dir / "tests" / "private" / "ground_truth_sources" / "main.tex").is_file()
        assert (task_dir / "tests" / "private" / "ground_truth_sources" / "code" / "x.py").is_file()

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


def test_all_agent_instructions_use_external_references_file() -> None:
    agents_dir = (
        Path(__file__).parents[1]
        / "src"
        / "paperbench_harbor"
        / "adapters"
        / "paperwrite_bench"
        / "agents_md"
    )
    for paper_type in ("method", "benchmark", "both"):
        agents = (agents_dir / f"AGENTS_{paper_type}.md").read_text(encoding="utf-8")
        assert "Always include references within" not in agents
        assert "reference.bib" not in agents.replace("references.bib", "")
        assert "external `references.bib`" in agents
        assert "Update that file only when the task requires it" not in agents
        assert "Do not write `\\\\section`" in agents
        assert "Standard LaTeX table row endings (`\\\\`) are allowed" in agents


def test_rendered_instruction_declares_submission_workflow(tmp_path: Path) -> None:
    config = PaperWriteBenchConversionConfig(
        source=_make_source(tmp_path), output_dir=tmp_path / "out", overview="short", limit=1
    )
    convert_paperwrite_bench(config)
    instruction = (tmp_path / "out" / "pwb-0001" / "instruction.md").read_text(encoding="utf-8")

    assert "final.pdf" not in instruction
    assert "`/workspace/materials/template.tex` and `/workspace/materials/references.bib` are read-only" in instruction
    assert "write the completed document to `/workspace/submission/main.tex`" in instruction
    assert "Copy `/workspace/materials/references.bib` unchanged to `/workspace/submission/references.bib`" in instruction
    assert "copy every referenced figure asset from `/workspace/materials/figures/` to `/workspace/submission/figures/`" in instruction
    assert "Compile from `/workspace/submission/`; the verifier recompiles `main.tex` independently." in instruction
    assert "Update that file only when the task requires it" not in instruction
    assert "update it to produce" not in instruction
    assert "then edit it to incorporate" not in instruction
    assert "main.tex` is the authoritative compilation entry point, not necessarily the only LaTeX source file" in instruction
    assert "braced `\\input{...}` or `\\include{...}` commands to reference files inside `/workspace/submission/`, using paths relative to the submission root" in instruction
    assert "every source dependency required by `main.tex` into `/workspace/submission/`" in instruction
    assert "Do not rely on absolute paths, parent-directory paths, or files under `/workspace/materials/`" in instruction


def test_all_paper_types_render_submission_workflow(tmp_path: Path) -> None:
    workflow_phrases = (
        "`/workspace/materials/template.tex` and `/workspace/materials/references.bib` are read-only",
        "Write the completed document to `/workspace/submission/main.tex`",
        "Copy `/workspace/materials/references.bib` unchanged to `/workspace/submission/references.bib`",
        "Copy referenced figure assets from `/workspace/materials/figures/` to `/workspace/submission/figures/`",
        "Compile from `/workspace/submission/`; the verifier recompiles `main.tex` independently.",
    )
    for paper_type in ("method", "benchmark", "both"):
        output_dir = tmp_path / paper_type
        config = PaperWriteBenchConversionConfig(
            source=_make_source(tmp_path / paper_type),
            output_dir=output_dir,
            overview="short",
            limit=1,
        )
        convert_paperwrite_bench(config)
        agents = (output_dir / "pwb-0001" / "environment" / "materials" / "AGENTS.md").read_text(
            encoding="utf-8"
        )
        instruction = (output_dir / "pwb-0001" / "instruction.md").read_text(encoding="utf-8")
        assert all(phrase in agents for phrase in workflow_phrases[:3])
        assert workflow_phrases[1] in instruction
        assert workflow_phrases[2] in instruction
        assert "copy every referenced figure asset from `/workspace/materials/figures/` to `/workspace/submission/figures/`" in instruction
        assert "reference them with paths relative to the submission root (for example, `\\includegraphics{figures/foo.png}`)" in instruction
        assert workflow_phrases[4] in instruction
        assert "`\\graphicspath{{figures/}}`" not in agents
        assert "`\\includegraphics{figures/foo.png}`" in agents


def test_short_dockerfile_omits_paper_orchestra_sources(tmp_path: Path) -> None:
    config = PaperWriteBenchConversionConfig(
        source=_make_source(tmp_path), output_dir=tmp_path / "out", overview="short", limit=1
    )
    convert_paperwrite_bench(config)
    dockerfile = (tmp_path / "out" / "pwb-0001" / "environment" / "Dockerfile").read_text()
    assert "paper_orchestra" not in dockerfile
    assert "entrypoint.sh" not in dockerfile
    assert "ENTRYPOINT" not in dockerfile


def test_generated_dockerfile_copy_sources_exist(tmp_path: Path) -> None:
    config = PaperWriteBenchConversionConfig(
        source=_make_source(tmp_path), output_dir=tmp_path / "out", overview="short", limit=1
    )
    convert_paperwrite_bench(config)
    environment = tmp_path / "out" / "pwb-0001" / "environment"
    dockerfile = (environment / "Dockerfile").read_text(encoding="utf-8")
    sources = re.findall(r"^COPY\s+(\S+?)/?\s+/", dockerfile, flags=re.MULTILINE)
    assert sources
    assert all((environment / source).exists() for source in sources)
    grader = (tmp_path / "out" / "pwb-0001" / "tests" / "grader_pwb.py").read_text()
    assert "hal_verification_dir=gt_root" in grader


def test_existing_graphicspath_gets_consistent_guidance(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    for paper_id in PAPERS:
        template = source / paper_id / "resources" / "template.tex"
        template.write_text(
            "\\documentclass{article}\n\\graphicspath{{figures/}}\n"
            "\\begin{document}\n\\end{document}\n",
            encoding="utf-8",
        )
    convert_paperwrite_bench(
        PaperWriteBenchConversionConfig(source=source, output_dir=tmp_path / "out", limit=1)
    )
    instruction = (tmp_path / "out" / "pwb-0001" / "instruction.md").read_text(encoding="utf-8")
    assert "does not prepend `figures/` twice" in instruction
