"""Run the release evidence workflow before a Paper-Writing-Exam tag is created.

The workflow deliberately has no upload operation.  It regenerates the
independent audit evidence for every declared task configuration, builds the
separate source archive for the configurations covered by its provenance plan,
and writes one durable gate report.  A release operator may upload candidate
bytes to an isolated Hugging Face revision first, because that immutable
revision is part of the source-archive plan, but must not create the public
release tag until this command succeeds.

The JSON spec is intentionally small and strict.  It fixes the converter and
workflow commits, the semantic-review model, all audit inputs, and the
LifeSci-only (or future complete) source-archive plan.  Paths are resolved
relative to the spec file so an operator can keep a release bundle together
outside the runnable task directories.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperbench_harbor.source_archive import SourceArchiveError, build_source_archive
from paperbench_harbor.source_archive.registry import load_plan
from paperbench_harbor.source_archive.release_gate import validate_release_provenance


class ReleaseWorkflowError(RuntimeError):
    """Raised when a release cannot produce complete, version-bound evidence."""


_SPEC_KEYS = {"schema_version", "release", "audits", "source_archive"}
_RELEASE_KEYS = {
    "converter_revision",
    "workflow_revision",
    "reviewer_model",
    "max_concurrent_audits",
}
_AUDIT_KEYS = {
    "config",
    "benchmark",
    "source",
    "dataset",
    "upstream_revision",
    "overview",
    "protocol",
    "workers",
}
_ARCHIVE_KEYS = {"plan", "dataset"}
_BENCHMARKS = {"paperwrite-bench", "paperwritingbench", "lifesci-paperrecon"}


@dataclass(frozen=True)
class AuditSpec:
    config: str
    benchmark: str
    source: Path
    dataset: Path
    upstream_revision: str
    overview: str | None
    protocol: str | None
    workers: int


@dataclass(frozen=True)
class ReleaseWorkflowSpec:
    converter_revision: str
    workflow_revision: str
    reviewer_model: str
    max_concurrent_audits: int
    audits: tuple[AuditSpec, ...]
    archive_plan: Path
    archive_dataset: Path


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ReleaseWorkflowError(f"{label} not found: {path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseWorkflowError(f"cannot read {label} {path}: {error}") from error
    if not isinstance(value, dict):
        raise ReleaseWorkflowError(f"{label} must be a JSON object: {path}")
    return value


def _exact_keys(record: dict[str, Any], expected: set[str], *, label: str) -> None:
    actual = set(record)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ReleaseWorkflowError(
            f"{label} keys differ; missing={missing}, unexpected={unexpected}"
        )


def _nonempty_string(record: dict[str, Any], key: str, *, label: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ReleaseWorkflowError(f"{label}.{key} must be a non-empty string")
    return value


def _pinned_revision(value: str, *, label: str) -> str:
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value.lower()):
        raise ReleaseWorkflowError(f"{label} must be a 40-character hexadecimal revision")
    return value


def _positive_integer(record: dict[str, Any], key: str, *, label: str) -> int:
    value = record.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ReleaseWorkflowError(f"{label}.{key} must be a positive integer")
    return value


def _resolve(spec_path: Path, value: str, *, label: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    resolved = (spec_path.parent / path).resolve()
    if not resolved:
        raise ReleaseWorkflowError(f"{label} is not a valid path")
    return resolved


def load_workflow_spec(path: Path) -> ReleaseWorkflowSpec:
    """Parse a strict release workflow spec without running any audit."""
    spec = _read_json_object(path, label="release workflow spec")
    _exact_keys(spec, _SPEC_KEYS, label="release workflow spec")
    if spec.get("schema_version") != 1:
        raise ReleaseWorkflowError("release workflow spec schema_version must be 1")

    release = spec.get("release")
    if not isinstance(release, dict):
        raise ReleaseWorkflowError("release workflow spec.release must be an object")
    _exact_keys(release, _RELEASE_KEYS, label="release workflow spec.release")
    converter_revision = _pinned_revision(
        _nonempty_string(release, "converter_revision", label="release workflow spec.release"),
        label="release workflow spec.release.converter_revision",
    )
    workflow_revision = _pinned_revision(
        _nonempty_string(release, "workflow_revision", label="release workflow spec.release"),
        label="release workflow spec.release.workflow_revision",
    )
    reviewer_model = _nonempty_string(release, "reviewer_model", label="release workflow spec.release")
    max_concurrent_audits = _positive_integer(
        release, "max_concurrent_audits", label="release workflow spec.release"
    )

    raw_audits = spec.get("audits")
    if not isinstance(raw_audits, list) or not raw_audits:
        raise ReleaseWorkflowError("release workflow spec.audits must be a non-empty list")
    audits: list[AuditSpec] = []
    seen_configs: set[str] = set()
    for index, raw_audit in enumerate(raw_audits):
        label = f"release workflow spec.audits[{index}]"
        if not isinstance(raw_audit, dict):
            raise ReleaseWorkflowError(f"{label} must be an object")
        _exact_keys(raw_audit, _AUDIT_KEYS, label=label)
        config = _nonempty_string(raw_audit, "config", label=label)
        if Path(config).name != config or config in {".", ".."}:
            raise ReleaseWorkflowError(f"{label}.config must be one directory name")
        if config in seen_configs:
            raise ReleaseWorkflowError(f"release workflow spec repeats config {config!r}")
        seen_configs.add(config)
        benchmark = _nonempty_string(raw_audit, "benchmark", label=label)
        if benchmark not in _BENCHMARKS:
            raise ReleaseWorkflowError(f"{label}.benchmark is not supported: {benchmark!r}")
        source = _resolve(path, _nonempty_string(raw_audit, "source", label=label), label=label)
        dataset = _resolve(path, _nonempty_string(raw_audit, "dataset", label=label), label=label)
        upstream_revision = _nonempty_string(raw_audit, "upstream_revision", label=label)
        overview = raw_audit.get("overview")
        protocol = raw_audit.get("protocol")
        if overview is not None and overview not in {"short", "long"}:
            raise ReleaseWorkflowError(f"{label}.overview must be null, 'short', or 'long'")
        if protocol is not None and protocol != "sparse-plotoff":
            raise ReleaseWorkflowError(f"{label}.protocol must be null or 'sparse-plotoff'")
        if benchmark in {"paperwrite-bench", "lifesci-paperrecon"}:
            if overview is None or protocol is not None:
                raise ReleaseWorkflowError(f"{label} needs overview and no protocol")
        elif protocol is None or overview is not None:
            raise ReleaseWorkflowError(f"{label} needs protocol and no overview")
        audits.append(
            AuditSpec(
                config=config,
                benchmark=benchmark,
                source=source,
                dataset=dataset,
                upstream_revision=upstream_revision,
                overview=overview,
                protocol=protocol,
                workers=_positive_integer(raw_audit, "workers", label=label),
            )
        )

    archive = spec.get("source_archive")
    if not isinstance(archive, dict):
        raise ReleaseWorkflowError("release workflow spec.source_archive must be an object")
    _exact_keys(archive, _ARCHIVE_KEYS, label="release workflow spec.source_archive")
    archive_plan = _resolve(
        path,
        _nonempty_string(archive, "plan", label="release workflow spec.source_archive"),
        label="release workflow spec.source_archive.plan",
    )
    archive_dataset = _resolve(
        path,
        _nonempty_string(archive, "dataset", label="release workflow spec.source_archive"),
        label="release workflow spec.source_archive.dataset",
    )
    return ReleaseWorkflowSpec(
        converter_revision=converter_revision,
        workflow_revision=workflow_revision,
        reviewer_model=reviewer_model,
        max_concurrent_audits=max_concurrent_audits,
        audits=tuple(audits),
        archive_plan=archive_plan,
        archive_dataset=archive_dataset,
    )


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.is_dir():
        return "missing"
    for path in sorted(path for path in root.rglob("*") if path.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(_file_digest(path).encode("ascii"))
    return digest.hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _git_revision() -> str:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
            encoding="utf-8",
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
            encoding="utf-8",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReleaseWorkflowError("release workflow must run from a Git checkout") from error
    if dirty:
        raise ReleaseWorkflowError("release workflow requires a clean Git checkout")
    return _pinned_revision(revision, label="current workflow revision")


def _prepare_empty_directory(path: Path, *, label: str) -> None:
    if path.exists() and not path.is_dir():
        raise ReleaseWorkflowError(f"{label} must be a directory: {path}")
    if path.exists() and any(path.iterdir()):
        raise ReleaseWorkflowError(f"{label} must be empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def _separate(path: Path, protected: Path, *, label: str) -> None:
    resolved = path.resolve()
    protected_resolved = protected.resolve()
    if resolved == protected_resolved or resolved in protected_resolved.parents or protected_resolved in resolved.parents:
        raise ReleaseWorkflowError(f"{label} must be outside runnable task directory {protected}")


def _audit_command(audit: AuditSpec, *, output: Path, reviewer_model: str) -> list[str]:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "audit_fidelity.py"),
        audit.benchmark,
        "--source",
        str(audit.source),
        "--dataset",
        str(audit.dataset),
        "--upstream-revision",
        audit.upstream_revision,
        "--output",
        str(output),
        "--semantic-review",
        "--reviewer-model",
        reviewer_model,
        "--workers",
        str(audit.workers),
    ]
    if audit.overview is not None:
        command.extend(["--overview", audit.overview])
    if audit.protocol is not None:
        command.extend(["--protocol", audit.protocol])
    return command


def _run_audit(audit: AuditSpec, *, output: Path, reviewer_model: str) -> Path:
    command = _audit_command(audit, output=output, reviewer_model=reviewer_model)
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode:
        details = (completed.stdout + completed.stderr).strip()
        raise ReleaseWorkflowError(f"fidelity audit failed for {audit.config}: {details}")
    return output / "summary.json"


def _manifest_task_count(dataset: Path) -> int:
    manifest = dataset / "dataset-manifest.jsonl"
    try:
        records = [line for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    except FileNotFoundError as error:
        raise ReleaseWorkflowError(f"dataset manifest missing for {dataset}") from error
    if not records:
        raise ReleaseWorkflowError(f"dataset manifest is empty for {dataset}")
    return len(records)


def _load_audit_summary(
    audit: AuditSpec,
    *,
    summary_path: Path,
    reviewer_model: str,
    workflow_revision: str,
) -> dict[str, Any]:
    summary = _read_json_object(summary_path, label=f"fidelity audit summary for {audit.config}")
    total = _manifest_task_count(audit.dataset)
    expected = {
        "total_tasks": total,
        "passed_tasks": total,
        "failed_tasks": 0,
        "determinism_ok": True,
        "semantic_reviews": total,
        "semantic_review_failures": 0,
    }
    for key, value in expected.items():
        if summary.get(key) != value:
            raise ReleaseWorkflowError(
                f"fidelity audit for {audit.config} has {key}={summary.get(key)!r}, expected {value!r}"
            )
    evidence = summary.get("evidence")
    if not isinstance(evidence, dict):
        raise ReleaseWorkflowError(f"fidelity audit for {audit.config} has no evidence object")
    expected_evidence = {
        "semantic_review_required": True,
        "reviewer_model": reviewer_model,
        "converter_revision": workflow_revision,
        "upstream_revision": audit.upstream_revision,
        "dataset_tree_sha256": _tree_digest(audit.dataset),
    }
    for key, value in expected_evidence.items():
        if evidence.get(key) != value:
            raise ReleaseWorkflowError(
                f"fidelity audit for {audit.config} evidence has {key}={evidence.get(key)!r}, "
                f"expected {value!r}"
            )
    return summary


def _validate_archive_audit_binding(
    plan: dict[str, Any], *, archive_dataset: Path, audits: tuple[AuditSpec, ...]
) -> set[str]:
    """Prove each archived task was audited from the same task directory.

    The archive can cover one configuration rooted directly at ``archive_dataset``
    or several configurations rooted beneath it.  In either case every planned
    archive path must resolve to the task directory named by that configuration's
    audit manifest.  A passing summary from a similarly shaped but different
    candidate tree is therefore not reusable as release evidence.
    """
    by_config = {audit.config: audit for audit in audits}
    planned_counts: dict[str, int] = {}
    archive_configs: set[str] = set()
    for task in plan["tasks"]:
        config = task["config"]
        archive_configs.add(config)
        planned_counts[config] = planned_counts.get(config, 0) + 1
        audit = by_config[config]
        archived_task = archive_dataset / task["task_path"]
        audited_task = audit.dataset / task["task_id"]
        if archived_task.resolve() != audited_task.resolve():
            raise ReleaseWorkflowError(
                f"source archive task {task['task_id']} is not the task audited for {config}"
            )
    for config, expected_count in planned_counts.items():
        actual_count = _manifest_task_count(by_config[config].dataset)
        if actual_count != expected_count:
            raise ReleaseWorkflowError(
                f"source archive plan covers {expected_count} task(s) for {config}, "
                f"but its audit dataset contains {actual_count}"
            )
    return archive_configs


def _write_evidence(
    path: Path,
    *,
    spec: ReleaseWorkflowSpec,
    audit_summaries: dict[str, Path],
    archive_output: Path,
    archive_report: dict[str, Any],
) -> None:
    if path.exists():
        raise ReleaseWorkflowError(f"release workflow evidence already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    audits = []
    for audit in spec.audits:
        summary = _read_json_object(audit_summaries[audit.config], label="fidelity audit summary")
        evidence = summary["evidence"]
        audits.append(
            {
                "config": audit.config,
                "benchmark": audit.benchmark,
                "task_count": summary["total_tasks"],
                "upstream_revision": evidence["upstream_revision"],
                "upstream_tree_sha256": evidence["upstream_tree_sha256"],
                "dataset_tree_sha256": evidence["dataset_tree_sha256"],
                "summary_sha256": _file_digest(audit_summaries[audit.config]),
            }
        )
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "converter_revision": spec.converter_revision,
                "workflow_revision": spec.workflow_revision,
                "reviewer_model": spec.reviewer_model,
                "audits": audits,
                "source_archive_plan_sha256": _file_digest(spec.archive_plan),
                "source_archive_tree_sha256": _tree_digest(archive_output),
                "source_archive_gate": archive_report,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def run_release_workflow(
    *,
    spec: ReleaseWorkflowSpec,
    audit_output: Path,
    archive_output: Path,
    evidence_output: Path,
) -> dict[str, Any]:
    """Run all semantic audits concurrently and then prove archive provenance."""
    if _git_revision() != spec.workflow_revision:
        raise ReleaseWorkflowError(
            "workflow_revision does not match the clean checkout that is running this release"
        )
    if not spec.archive_dataset.is_dir():
        raise ReleaseWorkflowError(f"source archive dataset root does not exist: {spec.archive_dataset}")
    for audit in spec.audits:
        if not audit.source.is_dir():
            raise ReleaseWorkflowError(f"audit source does not exist for {audit.config}: {audit.source}")
        if not audit.dataset.is_dir():
            raise ReleaseWorkflowError(f"audit dataset does not exist for {audit.config}: {audit.dataset}")
        _separate(audit_output, audit.dataset, label="audit output")
        _separate(archive_output, audit.dataset, label="source archive output")
        _separate(evidence_output, audit.dataset, label="release workflow evidence")
    _prepare_empty_directory(audit_output, label="audit output")
    _prepare_empty_directory(archive_output, label="source archive output")

    try:
        plan = load_plan(spec.archive_plan)
    except SourceArchiveError as error:
        raise ReleaseWorkflowError(f"invalid source archive plan: {error}") from error
    if plan["release"]["converter_revision"] != spec.converter_revision:
        raise ReleaseWorkflowError("source archive plan converter_revision disagrees with workflow spec")
    if plan["release"]["workflow_revision"] != spec.workflow_revision:
        raise ReleaseWorkflowError("source archive plan workflow_revision disagrees with workflow spec")
    configured = {audit.config for audit in spec.audits}
    archive_configs = {task["config"] for task in plan["tasks"]}
    if not archive_configs <= configured:
        raise ReleaseWorkflowError(
            "source archive plan includes configurations without a full semantic audit: "
            f"{sorted(archive_configs - configured)}"
        )
    archive_configs = _validate_archive_audit_binding(
        plan, archive_dataset=spec.archive_dataset, audits=spec.audits
    )

    summary_paths: dict[str, Path] = {}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(spec.max_concurrent_audits, len(spec.audits))
    ) as executor:
        futures = {
            executor.submit(
                _run_audit,
                audit,
                output=audit_output / audit.config,
                reviewer_model=spec.reviewer_model,
            ): audit
            for audit in spec.audits
        }
        for future in concurrent.futures.as_completed(futures):
            audit = futures[future]
            summary_paths[audit.config] = future.result()

    for audit in spec.audits:
        _load_audit_summary(
            audit,
            summary_path=summary_paths[audit.config],
            reviewer_model=spec.reviewer_model,
            workflow_revision=spec.workflow_revision,
        )

    try:
        build_source_archive(
            plan_path=spec.archive_plan,
            dataset_root=spec.archive_dataset,
            output_root=archive_output,
        )
        archive_report = validate_release_provenance(
            plan_path=spec.archive_plan,
            dataset_root=spec.archive_dataset,
            archive_root=archive_output,
            audit_summaries={config: summary_paths[config] for config in archive_configs},
        )
    except SourceArchiveError as error:
        raise ReleaseWorkflowError(f"source archive release gate failed: {error}") from error

    _write_evidence(
        evidence_output,
        spec=spec,
        audit_summaries=summary_paths,
        archive_output=archive_output,
        archive_report=archive_report,
    )
    return {"audit_summaries": summary_paths, "archive_report": archive_report}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="strict schema-v1 workflow spec JSON")
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--archive-output", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        spec = load_workflow_spec(args.spec)
        report = run_release_workflow(
            spec=spec,
            audit_output=args.audit_output,
            archive_output=args.archive_output,
            evidence_output=args.evidence_output,
        )
    except ReleaseWorkflowError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report["archive_report"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
