#!/usr/bin/env python3
"""Run one complete, reproducible LifeSci-PaperRecon release-candidate build.

This is intentionally a direct CLI supervisor rather than an OpenCode-agent
tool call.  A published-corpus rebuild starts one OpenCode session per paper and
can legitimately run for several hours; an agent's foreground Bash tool has a
shorter hard timeout.  The supervisor owns the full sequence and writes a
machine-readable status file after every stage, so an interrupted terminal
never looks like a successful partial release candidate.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_REPOSITORY = "Jack-Jieke-Wu/Paper-Writing-Exam"
DEFAULT_WORKER_MODEL = "openai/gpt-5.6-sol"
DEFAULT_REVIEWER_MODEL = "openai/gpt-5.5"


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _write_summary(path: Path, summary: dict) -> None:
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def _run(stage: str, command: list[str], *, summary: dict, summary_path: Path) -> None:
    record = {"stage": stage, "command": command, "started_at": _timestamp()}
    summary["stages"].append(record)
    _write_summary(summary_path, summary)
    print("$ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=REPOSITORY_ROOT, check=False)
    record["finished_at"] = _timestamp()
    record["returncode"] = completed.returncode
    record["status"] = "passed" if completed.returncode == 0 else "failed"
    _write_summary(summary_path, summary)
    if completed.returncode:
        raise subprocess.CalledProcessError(completed.returncode, command)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root",
        type=Path,
        required=True,
        help="New, empty, managed temporary directory for all rebuildable artifacts.",
    )
    parser.add_argument(
        "--dataset-repository",
        default=DEFAULT_DATASET_REPOSITORY,
        help="Hugging Face dataset repository supplying the published manifest.",
    )
    parser.add_argument("--model", default=DEFAULT_WORKER_MODEL)
    parser.add_argument("--reviewer-model", default=DEFAULT_REVIEWER_MODEL)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    run_root = args.run_root.resolve()
    if run_root.exists() and any(run_root.iterdir()):
        raise SystemExit(f"--run-root must be new and empty: {run_root}")
    run_root.mkdir(parents=True, exist_ok=True)

    manifest_root = run_root / "published-manifest"
    manifest = manifest_root / "lifesci-paperrecon-short" / "dataset-manifest.jsonl"
    scratch_root = run_root / "scratch"
    corpus_root = run_root / "corpus"
    build_root = run_root / "build"
    log_dir = run_root / "logs"
    task_root = run_root / "dataset" / "lifesci-paperrecon-short"
    reports_root = run_root / "reports"
    summary_path = run_root / "run-summary.json"
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, text=True
    ).strip()
    summary: dict = {
        "generated_at": _timestamp(),
        "dataset_repository": args.dataset_repository,
        "upstream_revision": revision,
        "worker_model": args.model,
        "reviewer_model": args.reviewer_model,
        "run_root": str(run_root),
        "stages": [],
    }
    _write_summary(summary_path, summary)

    try:
        _run(
            "download-published-manifest",
            [
                "hf",
                "download",
                args.dataset_repository,
                "lifesci-paperrecon-short/dataset-manifest.jsonl",
                "--repo-type",
                "dataset",
                "--local-dir",
                str(manifest_root),
            ],
            summary=summary,
            summary_path=summary_path,
        )
        _run(
            "build-and-review-published-corpus",
            [
                "uv",
                "run",
                "scripts/build_lifesci_paperrecon_source.py",
                "--scratch-root",
                str(scratch_root),
                "--corpus-root",
                str(corpus_root),
                "--build-root",
                str(build_root),
                "--log-dir",
                str(log_dir),
                "--published-manifest",
                str(manifest),
                "--model",
                args.model,
                "--reviewer-model",
                args.reviewer_model,
                "--concurrency",
                "1",
                "--fresh",
                "--report",
                str(run_root / "build-report.json"),
            ],
            summary=summary,
            summary_path=summary_path,
        )
        _run(
            "audit-source-table-coverage",
            [
                "uv",
                "run",
                "scripts/audit_lifesci_table_coverage.py",
                "--source",
                str(corpus_root),
                "--published-manifest",
                str(manifest),
                "--output",
                str(reports_root / "table-coverage.json"),
            ],
            summary=summary,
            summary_path=summary_path,
        )
        _run(
            "convert-harbor-tasks",
            [
                "uv",
                "run",
                "paperbench-harbor",
                "lifesci-paperrecon",
                "--source",
                str(corpus_root),
                "--output-dir",
                str(task_root),
                "--upstream-revision",
                revision,
                "--overview",
                "short",
                "--overwrite",
            ],
            summary=summary,
            summary_path=summary_path,
        )
        _run(
            "audit-task-fidelity",
            [
                "uv",
                "run",
                "scripts/audit_fidelity.py",
                "lifesci-paperrecon",
                "--source",
                str(corpus_root),
                "--dataset",
                str(task_root),
                "--upstream-revision",
                revision,
                "--overview",
                "short",
                "--output",
                str(reports_root / "fidelity"),
            ],
            summary=summary,
            summary_path=summary_path,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        summary["error"] = str(error)
        summary["status"] = "failed"
        summary["finished_at"] = _timestamp()
        _write_summary(summary_path, summary)
        return 1

    summary["status"] = "passed"
    summary["finished_at"] = _timestamp()
    _write_summary(summary_path, summary)
    print(f"release candidate passed -> {run_root}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
