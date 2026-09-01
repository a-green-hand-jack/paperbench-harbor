from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from paperbench_harbor.agents import paper_run_core as core


def _run(command: str, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(
        ["bash", "-c", f"set -o pipefail; {command}"],
        capture_output=True,
        check=False,
        env={**os.environ, **(env or {})},
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
    assert "--template 'v0.3.0'" in core.init_command()
    assert "git ls-remote --exit-code" in core.init_command()
    assert core.HARNESS_TEMPLATE_COMMIT in core.init_command()
    patch_command = core.patch_opencode_project_command()
    assert "bash.clear()" in patch_command
    assert "bash['*'] = 'ask'" in patch_command
    assert "bash['git rev-parse --show-toplevel'] = 'allow'" in patch_command
    assert "git branch --show-current && git status --short && git remote -v" in patch_command
    assert "bash['ls \"paper/figures/srcs\" \"paper/tables\" \"materials/figures\" \"materials/tables\"'] = 'allow'" in patch_command
    for unsafe in (
        "python3 *",
        "python *",
        "find *",
        "cat *",
        "cp *",
        "mv *",
        "make *",
        "pdflatex *",
        "git status*",
        "git remote*",
    ):
        assert unsafe not in patch_command


def test_patch_replaces_inherited_bash_permissions(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config_path = project / "opencode.json"
    config_path.write_text(
        json.dumps(
            {
                "permission": {
                    "bash": {
                        "*": "ask",
                        "python3 *": "allow",
                        "git status*": "allow",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    _run(core.patch_opencode_project_command(str(project)))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    bash_rules = config["permission"]["bash"]
    assert list(bash_rules) == [
        "*",
        "git rev-parse --show-toplevel",
        "git rev-parse --show-toplevel && git branch --show-current && git status --short && git remote -v",
        'ls "paper/figures/srcs" "paper/tables" "materials/figures" "materials/tables"',
    ]
    assert bash_rules["*"] == "ask"
    assert bash_rules["git rev-parse --show-toplevel"] == "allow"
    assert bash_rules[
        "git rev-parse --show-toplevel && git branch --show-current && git status --short && git remote -v"
    ] == "allow"
    assert bash_rules[
        'ls "paper/figures/srcs" "paper/tables" "materials/figures" "materials/tables"'
    ] == "allow"


def test_install_command_uses_pinned_v050_source_build() -> None:
    command = core.paper_run_install_commands()[0]

    assert core.PAPER_RUN_VERSION == "0.5.0"
    assert core.PAPER_RUN_COMMIT == "9925848adf195e68d3f3e3039959f9f2c19fb7a3"
    assert core.PAPER_RUN_REPOSITORY_URL in command
    assert core.PAPER_RUN_COMMIT in command
    assert f"test \"$(paper-run --version)\" = '{core.PAPER_RUN_VERSION}'" in command
    assert "git init" in command
    assert "git -C \"$repo_dir\" fetch --quiet --depth 1 origin" in command
    assert "npm ci --ignore-scripts" in command
    assert "cp package-lock.json npm-shrinkwrap.json" in command
    assert "npm-shrinkwrap.json" in command
    assert "npm run build" in command
    assert "npm pack --ignore-scripts" in command
    assert "paper-run-package.sha256" in command
    assert "npm install -g \"$package_path\" --ignore-scripts" in command
    assert core.PAPER_RUN_OFFICIAL_INSTALL_URL.endswith("/v0.5.0/install.sh")


def test_install_command_is_shell_parseable(tmp_path: Path) -> None:
    script = tmp_path / "install.sh"
    script.write_text(f"#!/bin/sh\n{core.paper_run_install_commands()[0]}\n", encoding="utf-8")
    result = subprocess.run(
        ["bash", "-n", str(script)], capture_output=True, check=False, text=True
    )

    assert result.returncode == 0, result.stderr


def test_version_check_requires_current_paper_run_version() -> None:
    command = core.version_check_command()

    assert "paper-run --version" in command
    assert "= '0.5.0'" in command


def test_new_paper_path_does_not_expose_external_import_commands() -> None:
    command = core.init_command(model="openai/gpt-5.6-terra")
    start = core.start_command("openai/gpt-5.6-terra", "medium")

    assert "paper-run init" in command
    assert "paper-run start --headless --mode autonomous" in start
    assert "paper-run review" not in command + start
    assert "paper-run transfer" not in command + start
    assert "paper-run adopt" not in command + start


def test_provider_config_does_not_persist_credentials(tmp_path: Path) -> None:
    home = tmp_path / "home"
    command = core.opencode_user_config_command(
        "https://gateway.example/v1", "openai/gpt-test"
    )
    assert command is not None

    secret = "sk-regression-secret"
    _run(command, {"HOME": str(home), "OPENAI_API_KEY": secret})
    config_path = home / ".config" / "opencode" / "opencode.json"
    config_text = config_path.read_text(encoding="utf-8")
    config = json.loads(config_text)

    assert config == {
        "provider": {
            "openai": {
                "models": {"gpt-test": {}},
                "options": {"baseURL": "https://gateway.example/v1"},
            }
        }
    }
    assert secret not in config_text
    assert "OPENAI_API_KEY" not in config_text
    assert "permission" not in config


def test_provider_config_rejects_credential_bearing_endpoint() -> None:
    for base_url in (
        "https://user:secret@gateway.example/v1",
        "https://gateway.example/v1?api_key=secret",
        "https://gateway.example/v1#secret",
    ):
        try:
            core.opencode_user_config_command(base_url, "openai/gpt-test")
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted sensitive endpoint: {base_url}")


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
    sections = paper / "sections"
    sections.mkdir()
    (sections / "method.tex").write_text("Method body.\n", encoding="utf-8")
    figures = paper / "figures"
    figures.mkdir()
    (figures / "result.pdf").write_bytes(b"%PDF-1.4\n")
    generated = (paper / "refs.bib").read_text(encoding="utf-8")
    submission = tmp_path / "submission"

    for command in core.export_commands(
        str(project), str(submission), str(tmp_path / "logs"), str(tmp_path / "materials")
    )[:2]:
        _run(command)

    assert (submission / "references.bib").read_text(encoding="utf-8") == generated
    assert (submission / "refs.bib").read_text(encoding="utf-8") == generated
    assert (submission / "sections" / "method.tex").read_text(encoding="utf-8") == (
        "Method body.\n"
    )
    assert (submission / "figures" / "result.pdf").read_bytes() == b"%PDF-1.4\n"


def test_export_records_pinned_provenance_and_submission_hash_command(tmp_path: Path) -> None:
    project, _ = _paper_project(tmp_path)
    submission = tmp_path / "submission"
    commands = core.export_commands(
        str(project),
        str(submission),
        str(tmp_path / "logs"),
        str(tmp_path / "materials"),
        model="openai/gpt-5.6-terra",
        variant="medium",
        base_url="https://gateway.example/v1",
    )

    assert core.PAPER_RUN_COMMIT in commands[2]
    assert '"paper_run_version": "0.5.0"' in commands[2]
    assert '"model": "openai/gpt-5.6-terra"' in commands[2]
    assert '"variant": "medium"' in commands[2]
    assert '"openai_base_url_origin": "https://gateway.example"' in commands[2]
    assert "https://gateway.example/v1" not in commands[2]
    assert "materials.sha256" in commands[2]
    assert "paper-run-state.sha256" in commands[2]
    assert "submission.sha256" in commands[2]
    assert "paper-run-package.sha256" in commands[2]
    assert "cp '/logs/agent/paper-run/paper-run-package.sha256'" in commands[2]
    assert "OPENAI_API_KEY" in commands[2]


def test_export_writes_artifacts_and_provenance(tmp_path: Path, monkeypatch) -> None:
    project, _ = _paper_project(tmp_path)
    paper_run_state = project / ".paper-run"
    paper_run_state.mkdir()
    (paper_run_state / "run.log").write_text("run complete\n", encoding="utf-8")
    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "idea.md").write_text("Public idea\n", encoding="utf-8")
    package_hash = tmp_path / "package.sha256"
    package_hash.write_text("hash  paper-run-0.5.0.tgz\n", encoding="utf-8")
    monkeypatch.setattr(core, "PACKAGE_HASH_ARTIFACT", str(package_hash))
    submission = tmp_path / "submission"
    logs = tmp_path / "logs"

    for command in core.export_commands(
        str(project), str(submission), str(logs), str(materials)
    ):
        _run(command)

    artifact_dir = logs / "paper-run"
    provenance = json.loads((artifact_dir / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["package_hash"] == "paper-run-package.sha256"
    assert (artifact_dir / "paper-run-package.sha256").read_text(encoding="utf-8") == (
        "hash  paper-run-0.5.0.tgz\n"
    )
    assert (artifact_dir / "paper-run-state.sha256").is_file()
    assert (artifact_dir / "materials.sha256").is_file()
    assert (artifact_dir / "submission.sha256").is_file()


def test_shared_task_budget_remains_agent_neutral() -> None:
    templates = Path("src/paperbench_harbor/common/templates")

    task = (templates / "task.toml.j2").read_text(encoding="utf-8")
    instruction = (templates / "instruction.md.j2").read_text(encoding="utf-8")
    pwbw_instruction = (templates / "instruction_pwbw.md.j2").read_text(encoding="utf-8")

    assert "timeout_sec = 3600.0" in task
    assert "3600 seconds (1 hour)" in instruction
    assert "3600 seconds (1 hour)" in pwbw_instruction
