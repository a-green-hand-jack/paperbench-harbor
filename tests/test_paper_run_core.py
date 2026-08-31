from __future__ import annotations

import subprocess
from pathlib import Path

from paperbench_harbor.agents import paper_run_core as core


def _run(command: str) -> None:
    result = subprocess.run(
        ["bash", "-c", f"set -o pipefail; {command}"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def _paper_project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    paper = project / "paper"
    paper.mkdir(parents=True)
    (paper / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    (paper / "refs.bib").write_text("@misc{generated}\n", encoding="utf-8")
    return project, paper


def test_brief_and_start_command_bridge_harbor_inputs() -> None:
    brief = core.build_brief(
        "Read /workspace/materials/idea.md.\n\n"
        "## Submission contract\nWrite to /workspace/submission/main.tex.\n"
    )

    assert all(f"## {section}" in brief for section in core.REQUIRED_BRIEF_SECTIONS)
    assert "materials/idea.md" in brief
    assert "/workspace/submission/main.tex" not in brief

    command = core.start_command("openai/gpt-5.6-terra", "medium")
    assert "paper-run start --headless --mode autonomous" in command
    assert "--model 'openai/gpt-5.6-terra'" in command
    assert "--variant 'medium'" in command
    assert "--stage-timeout-multiplier 2" in command


def test_export_preserves_paperwrite_bench_bibliography(tmp_path: Path) -> None:
    project, _ = _paper_project(tmp_path)
    project_materials = project / "materials"
    project_materials.mkdir()
    (project_materials / "references.bib").write_text(
        "@misc{modified-project-copy}\n", encoding="utf-8"
    )
    materials = tmp_path / "materials"
    materials.mkdir()
    supplied = "@article{supplied, title={Supplied}}\n"
    (materials / "references.bib").write_text(supplied, encoding="utf-8")
    submission = tmp_path / "submission"

    for command in core.export_commands(
        str(project), str(submission), str(tmp_path / "logs"), str(materials)
    )[:2]:
        _run(command)

    assert (submission / "references.bib").read_text(encoding="utf-8") == supplied
    assert (submission / "refs.bib").read_text(encoding="utf-8") == supplied


def test_export_keeps_paperwritingbench_generated_bibliography(tmp_path: Path) -> None:
    project, paper = _paper_project(tmp_path)
    generated = (paper / "refs.bib").read_text(encoding="utf-8")
    submission = tmp_path / "submission"

    for command in core.export_commands(
        str(project), str(submission), str(tmp_path / "logs"), str(tmp_path / "materials")
    )[:2]:
        _run(command)

    assert (submission / "references.bib").read_text(encoding="utf-8") == generated
    assert (submission / "refs.bib").read_text(encoding="utf-8") == generated


def test_shared_task_budget_remains_agent_neutral() -> None:
    templates = Path("src/paperbench_harbor/common/templates")

    task = (templates / "task.toml.j2").read_text(encoding="utf-8")
    instruction = (templates / "instruction.md.j2").read_text(encoding="utf-8")
    pwbw_instruction = (templates / "instruction_pwbw.md.j2").read_text(encoding="utf-8")

    assert "timeout_sec = 3600.0" in task
    assert "3600 seconds (1 hour)" in instruction
    assert "3600 seconds (1 hour)" in pwbw_instruction
