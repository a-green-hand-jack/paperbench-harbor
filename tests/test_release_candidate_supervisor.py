from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "run_lifesci_paperrecon_release_candidate.py"
)


def _load_supervisor():
    spec = importlib.util.spec_from_file_location("release_candidate_supervisor", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_supervisor_runs_all_release_candidate_stages(monkeypatch, tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    commands: list[list[str]] = []
    run_root = tmp_path / "candidate"
    run_root.mkdir()
    (run_root / ".agent-workspace.json").write_text("{}\n")
    (run_root / "supervisor.log").write_text("")
    (run_root / "supervisor.pid").write_text("123\n")

    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: "revision-123\n")

    def fake_run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["supervisor", "--run-root", str(run_root)],
    )

    assert supervisor.main() == 0

    summary = json.loads((run_root / "run-summary.json").read_text())
    assert summary["status"] == "passed"
    assert [stage["stage"] for stage in summary["stages"]] == [
        "download-published-manifest",
        "build-and-review-published-corpus",
        "audit-source-table-coverage",
        "convert-harbor-tasks",
        "audit-task-fidelity",
    ]
    assert commands[0][:4] == ["hf", "download", "Jack-Jieke-Wu/Paper-Writing-Exam", "lifesci-paperrecon-short/dataset-manifest.jsonl"]
    assert "--fresh" in commands[1]
    assert commands[2][2] == "scripts/audit_lifesci_table_coverage.py"
    assert commands[3][2:4] == ["paperbench-harbor", "lifesci-paperrecon"]
    assert commands[4][2:4] == ["scripts/audit_fidelity.py", "lifesci-paperrecon"]
