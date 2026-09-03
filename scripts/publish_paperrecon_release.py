"""Gate and publish a complete multi-domain PaperRecon candidate release.

The builder intentionally stops at local candidate staging.  This command is
the separate release operator step: it verifies all domain summaries, creates
an immutable candidate branch in the task and source-archive datasets, and
only creates the public tag when ``--publish`` is supplied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

DOMAINS = ("lifesci", "physics", "chemistry", "mathematics")
CONFIGS = {
    "lifesci": "lifesci-paperrecon-short",
    "physics": "physics-paperrecon-short",
    "chemistry": "chemistry-paperrecon-short",
    "mathematics": "mathematics-paperrecon-short",
}
MIN_TASKS = 20


class ReleasePublisherError(RuntimeError):
    """Raised when a candidate release does not satisfy the cross-domain gate."""


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleasePublisherError(f"cannot read {label}: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ReleasePublisherError(f"{label} must be a JSON object: {path}")
    return value


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_digest(root: Path) -> str:
    if not root.is_dir():
        return "missing"
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(_digest(path).encode("ascii"))
    return digest.hexdigest()


def _domain_run(root: Path, domain: str) -> dict[str, Any]:
    summary_path = root / "run-summary.json"
    summary = _read_json(summary_path, label=f"{domain} run summary")
    built = summary.get("built_tasks")
    converted = summary.get("converted_tasks")
    if not isinstance(built, int) or built < MIN_TASKS:
        raise ReleasePublisherError(f"{domain} has only {built!r} built tasks; need {MIN_TASKS}")
    if not isinstance(converted, int) or converted != built:
        raise ReleasePublisherError(f"{domain} converted_tasks must equal built_tasks ({built})")
    dataset = Path(summary.get("dataset", ""))
    archive = Path(summary.get("source_archive", ""))
    if not dataset.is_dir():
        raise ReleasePublisherError(f"{domain} dataset staging directory is missing: {dataset}")
    if not archive.is_dir():
        raise ReleasePublisherError(f"{domain} source archive staging directory is missing: {archive}")
    config = CONFIGS[domain]
    if dataset.name != config:
        raise ReleasePublisherError(f"{domain} dataset directory must be {config!r}, got {dataset}")
    fidelity = root / "reports" / "fidelity" / "summary.json"
    audit = _read_json(fidelity, label=f"{domain} fidelity summary")
    for key, expected in {
        "total_tasks": built,
        "passed_tasks": built,
        "failed_tasks": 0,
        "determinism_ok": True,
        "semantic_reviews": built,
        "semantic_review_failures": 0,
    }.items():
        if audit.get(key) != expected:
            raise ReleasePublisherError(
                f"{domain} fidelity summary {key}={audit.get(key)!r}, expected {expected!r}"
            )
    return {
        "domain": domain,
        "config": config,
        "run_root": str(root),
        "dataset": str(dataset),
        "archive": str(archive),
        "task_count": built,
        "dataset_tree_sha256": _tree_digest(dataset),
        "archive_tree_sha256": _tree_digest(archive),
        "fidelity_summary_sha256": _digest(fidelity),
    }


def load_gate(run_roots: dict[str, Path]) -> dict[str, Any]:
    """Validate the complete release and return immutable evidence."""
    missing = [domain for domain in DOMAINS if domain not in run_roots]
    if missing:
        raise ReleasePublisherError(f"missing required domain run(s): {', '.join(missing)}")
    domains = [_domain_run(run_roots[domain].resolve(), domain) for domain in DOMAINS]
    return {"schema_version": 1, "minimum_tasks_per_domain": MIN_TASKS, "domains": domains}


def _run(command: list[str]) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode:
        details = (completed.stdout + completed.stderr).strip()
        raise ReleasePublisherError(f"command failed ({' '.join(command)}): {details}")
    return completed.stdout.strip()


def publish(
    evidence: dict[str, Any],
    *,
    task_repo: str,
    archive_repo: str,
    candidate_revision: str,
    release_tag: str,
    publish_public: bool,
    evidence_path: Path,
) -> dict[str, Any]:
    """Upload staged bytes and optionally create the public tag."""
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    branch_args = ["hf", "repos", "branch", "create", task_repo, candidate_revision, "--type", "dataset", "--exist-ok"]
    _run(branch_args)
    _run(["hf", "repos", "branch", "create", archive_repo, candidate_revision, "--type", "dataset", "--exist-ok"])
    for record in evidence["domains"]:
        _run([
            "hf", "upload", task_repo, record["dataset"], record["config"], "--type", "dataset",
            "--revision", candidate_revision, "--commit-message", f"Stage {record['domain']} PaperRecon candidate",
        ])
        _run([
            "hf", "upload", archive_repo, record["archive"], record["config"], "--type", "dataset",
            "--revision", candidate_revision, "--commit-message", f"Stage {record['domain']} source archive",
        ])
    _run([
        "hf", "upload", task_repo, str(evidence_path), "release-evidence/paperrecon-gate.json",
        "--type", "dataset", "--revision", candidate_revision, "--commit-message", "Record PaperRecon release gate",
    ])
    if publish_public:
        _run(["hf", "repos", "tag", "create", task_repo, release_tag, "--type", "dataset", "--revision", candidate_revision, "--message", "PaperRecon multi-domain release"])
        _run(["hf", "repos", "tag", "create", archive_repo, release_tag, "--type", "dataset", "--revision", candidate_revision, "--message", "PaperRecon source archive release"])
    return {
        "candidate_revision": candidate_revision,
        "release_tag": release_tag if publish_public else None,
        "published": publish_public,
        "task_repo": task_repo,
        "archive_repo": archive_repo,
        "evidence": str(evidence_path),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    for domain in DOMAINS:
        parser.add_argument(f"--{domain}-run", type=Path, required=(domain != "lifesci"))
    parser.add_argument("--task-repo", default="Jack-Jieke-Wu/Paper-Writing-Exam")
    parser.add_argument("--archive-repo", default="Jack-Jieke-Wu/Paper-Writing-Exam-Source-Archive")
    parser.add_argument("--candidate-revision", default="paperrecon-v0.1.0-candidate")
    parser.add_argument("--release-tag", default="v0.1.0")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--publish", action="store_true", help="create the public release tag after upload")
    return parser


def main() -> int:
    args = _parser().parse_args()
    roots = {domain: getattr(args, f"{domain}_run") for domain in DOMAINS if getattr(args, f"{domain}_run")}
    try:
        evidence = load_gate(roots)
        result = publish(
            evidence,
            task_repo=args.task_repo,
            archive_repo=args.archive_repo,
            candidate_revision=args.candidate_revision,
            release_tag=args.release_tag,
            publish_public=args.publish,
            evidence_path=args.evidence,
        )
    except ReleasePublisherError as error:
        print(f"ERROR: {error}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
