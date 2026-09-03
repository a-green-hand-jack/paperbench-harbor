from __future__ import annotations

import subprocess
import tomllib

import pytest

from paperbench_harbor.common.task_contract import validate_task_contract
from paperbench_harbor.smoke.hello_world import (
    HELLO_WORLD_TASK_ID,
    build_hello_world_task,
    task_manifest,
)


def test_build_hello_world_task_uses_normal_task_layout(tmp_path) -> None:
    task_dir = build_hello_world_task(tmp_path)

    assert task_dir == tmp_path / "hello-world" / HELLO_WORLD_TASK_ID
    assert {
        "task.toml",
        "instruction.md",
        "environment",
        "solution",
        "tests",
    } <= {path.name for path in task_dir.iterdir()}
    assert not validate_task_contract(task_dir)

    task_toml = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    assert task_toml["artifacts"] == ["/workspace/submission"]
    assert task_toml["verifier"]["environment_mode"] == "separate"
    assert task_toml["agent"]["timeout_sec"] == 300.0

    environment_dockerfile = (task_dir / "environment" / "Dockerfile").read_text(encoding="utf-8")
    verifier_dockerfile = (task_dir / "tests" / "Dockerfile").read_text(encoding="utf-8")
    assert "texlive-latex-base" in environment_dockerfile
    assert "nodejs" in environment_dockerfile
    assert "texlive-full" not in environment_dockerfile
    assert "pytest-json-ctrf" in verifier_dockerfile

    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
    assert "/workspace/materials/brief.md" in instruction
    assert "/workspace/submission/main.tex" in instruction
    assert "HELLO_WORLD_SIGNAL" in instruction

    verifier = (task_dir / "tests" / "test_hello_world.py").read_text(encoding="utf-8")
    assert "test_submission_uses_the_supplied_brief" in verifier
    assert "submission did not use the mounted brief" in verifier

    manifest = task_manifest(task_dir)
    assert manifest["benchmark"] == "PaperBench Harbor"
    assert manifest["upstream_id"] == HELLO_WORLD_TASK_ID
    assert manifest["extra"]["task_version"] == 1


def test_oracle_produces_a_submission_that_matches_the_smoke_requirements(tmp_path) -> None:
    task_dir = build_hello_world_task(tmp_path)
    destination = tmp_path / "oracle-submission"

    subprocess.run(
        ["bash", task_dir / "solution" / "solve.sh", destination],
        check=True,
    )

    main_tex = (destination / "main.tex").read_text(encoding="utf-8")
    bibliography = (destination / "references.bib").read_text(encoding="utf-8")
    assert "PaperBench Harbor Hello World" in main_tex
    assert "HELLO\\_WORLD\\_SIGNAL" in main_tex
    assert "\\cite{harbor-smoke}" in main_tex
    assert "@misc{harbor-smoke," in bibliography


def test_build_refuses_to_overwrite_a_task_without_opt_in(tmp_path) -> None:
    build_hello_world_task(tmp_path)

    with pytest.raises(FileExistsError):
        build_hello_world_task(tmp_path)

    assert build_hello_world_task(tmp_path, overwrite=True).is_dir()
