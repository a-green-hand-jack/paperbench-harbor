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
import re
import subprocess
from pathlib import Path
from typing import Any

from paperbench_harbor.construction.core.evidence import contained_path, tree_hash
from paperbench_harbor.construction.core.knowledge import get_knowledge_package
from paperbench_harbor.construction.core.trial import verify_trial_evidence

DOMAINS = ("physics", "chemistry", "mathematics")
OPTIONAL_DOMAINS = ("lifesci",)
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
    try:
        return tree_hash(root)
    except ValueError as error:
        raise ReleasePublisherError(str(error)) from error


def _domain_run(root: Path, domain: str) -> dict[str, Any]:
    root = contained_path(root, root, directory=True)
    summary_path = contained_path(root, root / "run-summary.json")
    summary = _read_json(summary_path, label=f"{domain} run summary")
    built = summary.get("built_tasks")
    converted = summary.get("converted_tasks")
    if type(built) is not int or built < MIN_TASKS:
        raise ReleasePublisherError(f"{domain} has only {built!r} built tasks; need {MIN_TASKS}")
    if not isinstance(converted, int) or converted != built:
        raise ReleasePublisherError(f"{domain} converted_tasks must equal built_tasks ({built})")
    config = CONFIGS[domain]
    dataset = contained_path(root, root / "dataset" / config, directory=True)
    archive = contained_path(root, root / "source-archive", directory=True)
    if summary.get("dataset") != str(dataset) or summary.get("source_archive") != str(archive):
        raise ReleasePublisherError(f"{domain}: summary paths must match expected run-root layout")
    if not dataset.is_dir():
        raise ReleasePublisherError(f"{domain} dataset staging directory is missing: {dataset}")
    if not archive.is_dir():
        raise ReleasePublisherError(f"{domain} source archive staging directory is missing: {archive}")
    config = CONFIGS[domain]
    if dataset.name != config:
        raise ReleasePublisherError(f"{domain} dataset directory must be {config!r}, got {dataset}")
    fidelity = contained_path(root, root / "reports" / "fidelity" / "summary.json")
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
    for key, actual in {
        "dataset_tree_sha256": _tree_digest(dataset),
        "archive_tree_sha256": _tree_digest(archive),
        "fidelity_summary_sha256": _digest(fidelity),
    }.items():
        if summary.get(key) != actual:
            raise ReleasePublisherError(f"{domain}: missing or stale evidence binding {key}")
    if summary.get("status") != "passed" or summary.get("approved_count") != built:
        raise ReleasePublisherError(f"{domain}: delivery acceptance is incomplete")
    manifest = contained_path(root, dataset / "dataset-manifest.jsonl")
    try:
        entries = [json.loads(line) for line in manifest.read_text().splitlines() if line]
        ids = [entry["task_id"] for entry in entries]
    except (OSError, ValueError, KeyError) as error:
        raise ReleasePublisherError(f"{domain}: invalid task manifest") from error
    if len(ids) != built or len(set(ids)) != built:
        raise ReleasePublisherError(f"{domain}: task manifest does not match accepted count")
    trials = summary.get("trials", [])
    if len(trials) != built:
        raise ReleasePublisherError(f"{domain}: missing real trial evidence")
    execution_path = contained_path(root, root / "execution.json")
    if _digest(execution_path) != summary.get("execution_sha256"):
        raise ReleasePublisherError(f"{domain}: execution configuration binding mismatch")
    execution = _read_json(execution_path, label="execution")
    knowledge = get_knowledge_package(domain, summary["research_type"]).as_dict()
    # Normalize dataclass tuple fields to their persisted JSON representation.
    knowledge = json.loads(json.dumps(knowledge))
    by_task = {trial["task_id"]: trial for trial in trials}
    if set(by_task) != set(ids) or len(by_task) != len(trials):
        raise ReleasePublisherError(f"{domain}: trial task identities mismatch")
    for entry in entries:
        task_id, paper_id = entry["task_id"], entry["upstream_paper_id"]
        if not all(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]+", name) for name in (task_id, paper_id)):
            raise ReleasePublisherError("unsafe task/paper identity")
        task = contained_path(dataset, dataset / task_id, directory=True)
        paper = contained_path(root / "corpus", root / "corpus" / paper_id, directory=True)
        verify_trial_evidence(by_task[task_id], root=root, task=task, paper=paper,
                              knowledge=knowledge, execution=execution)
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
    try:
        domains = [_domain_run(run_roots[domain].absolute(), domain) for domain in DOMAINS]
        domains.extend(_domain_run(run_roots[domain].absolute(), domain)
                       for domain in OPTIONAL_DOMAINS if domain in run_roots)
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        raise ReleasePublisherError(f"invalid bound release evidence: {error}") from error
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
    upload_candidate: bool = False,
) -> dict[str, Any]:
    """Validate locally by default; each remote operation needs explicit intent."""
    if publish_public and not upload_candidate:
        raise ReleasePublisherError("--publish requires explicit --upload-candidate")
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not upload_candidate:
        return {"uploaded": False, "published": False, "evidence": str(evidence_path)}
    # Recheck the evidence at the write boundary, not only when it was produced.
    current = load_gate({item["domain"]: Path(item["run_root"]) for item in evidence["domains"]})
    if current != evidence:
        raise ReleasePublisherError("release evidence no longer matches staged artifacts")
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
    commits = {}
    for repo in (task_repo, archive_repo):
        info = json.loads(_run(["hf", "datasets", "info", repo, "--revision", candidate_revision, "--expand", "sha", "--format", "json"]))
        sha = info.get("sha", "")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ReleasePublisherError(f"missing immutable remote commit for {repo}")
        commits[repo] = sha
    if publish_public:
        for repo in (task_repo, archive_repo):
            _run(["hf", "repos", "tag", "create", repo, release_tag, "--type", "dataset", "--revision", commits[repo], "--message", "PaperRecon evidence-bound release"])
    return {
        "candidate_revision": candidate_revision,
        "release_tag": release_tag if publish_public else None,
        "published": publish_public,
        "uploaded": True,
        "remote_commits": commits,
        "task_repo": task_repo,
        "archive_repo": archive_repo,
        "evidence": str(evidence_path),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    for domain in (*DOMAINS, *OPTIONAL_DOMAINS):
        parser.add_argument(f"--{domain}-run", type=Path, required=(domain in DOMAINS))
    parser.add_argument("--task-repo", default="Jack-Jieke-Wu/Paper-Writing-Exam")
    parser.add_argument("--archive-repo", default="Jack-Jieke-Wu/Paper-Writing-Exam-Source-Archive")
    parser.add_argument("--candidate-revision", default="paperrecon-v0.5.0-candidate")
    parser.add_argument("--release-tag", default="v0.5.0")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--publish", action="store_true", help="create the public release tag after upload")
    parser.add_argument("--upload-candidate", action="store_true", help="explicitly authorize remote candidate writes")
    return parser


def main() -> int:
    args = _parser().parse_args()
    roots = {
        domain: getattr(args, f"{domain}_run")
        for domain in (*DOMAINS, *OPTIONAL_DOMAINS)
        if getattr(args, f"{domain}_run")
    }
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
            upload_candidate=args.upload_candidate,
        )
    except ReleasePublisherError as error:
        print(f"ERROR: {error}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
