"""Build and validate the source archive that is deliberately outside tasks.

The plan is human-authored, versioned release metadata.  This module turns it
into a portable registry plus the legally redistributable source bytes.  It
never reads from an already-built archive while converting Harbor tasks; the
only direction of data flow is task release + local build inputs -> archive.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from paperbench_harbor.common.manifest import sha256_file


class SourceArchiveError(RuntimeError):
    """The release cannot be published because provenance is incomplete."""


_TOP_LEVEL = {"schema_version", "release", "papers", "tasks"}
_RELEASE_FIELDS = {
    "dataset_repo",
    "dataset_revision",
    "dataset_tag",
    "source_archive_repo",
    "source_archive_tag",
    "converter_revision",
    "workflow_revision",
}
_PAPER_FIELDS = {"paper_id", "identity", "code", "workflow", "inputs"}
_IDENTITY_FIELDS = {
    "title",
    "source_kind",
    "arxiv_id",
    "arxiv_version",
    "abstract_url",
    "eprint_url",
    "pdf_url",
    "license",
    "source_exclusion_reason",
}
_CODE_FIELDS = {"status", "repository_url", "revision", "license", "exclusion_reason"}
_WORKFLOW_FIELDS = {"kind", "revision", "fetched_at", "source_archive_manifest_revision"}
_INPUT_FIELDS = {
    "kind",
    "source_url",
    "fetched_at",
    "sha256",
    "bytes",
    "redistribution",
    "archive_path",
    "source_path",
    "exclusion_reason",
}
_TASK_FIELDS = {
    "task_id",
    "task_path",
    "config",
    "paper_id",
    "dataset_revision",
    "converter_revision",
}
_REQUIRED_INPUT_KINDS = frozenset({"eprint", "pdf", "source-tree-manifest"})
_SHA256_HEX = frozenset("0123456789abcdef")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SourceArchiveError(f"{label} not found: {path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise SourceArchiveError(f"cannot read {label} {path}: {error}") from error
    if not isinstance(payload, dict):
        raise SourceArchiveError(f"{label} must be a JSON object: {path}")
    return payload


def _exact_keys(record: Mapping[str, Any], expected: set[str], *, label: str) -> None:
    unknown = sorted(set(record) - expected)
    missing = sorted(expected - set(record))
    if unknown or missing:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unexpected " + ", ".join(unknown))
        raise SourceArchiveError(f"{label}: " + "; ".join(details))


def _nonempty(record: Mapping[str, Any], field: str, *, label: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SourceArchiveError(f"{label} {field!r} must be a non-empty string")
    return value.strip()


def _sha256(value: str, *, label: str) -> None:
    if len(value) != 64 or any(char not in _SHA256_HEX for char in value.lower()):
        raise SourceArchiveError(f"{label} must be a SHA-256 hex digest")


def _pinned_revision(value: str, *, label: str) -> None:
    if len(value) != 40 or any(char not in _SHA256_HEX for char in value.lower()):
        raise SourceArchiveError(f"{label} must be a full pinned Git SHA-1")


def _relative_path(value: str, *, label: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or value in {"", "."}:
        raise SourceArchiveError(f"{label} must be a safe archive-relative path")
    return path


def _url_or_na(value: str, *, label: str, allow_na: bool = False) -> None:
    if allow_na and value == "not-applicable":
        return
    if not value.startswith("https://"):
        raise SourceArchiveError(f"{label} must be an HTTPS URL")


def load_plan(path: Path) -> dict[str, Any]:
    """Read a strict, portable source-archive plan before any bytes are copied."""
    plan = _read_json(path, label="source archive plan")
    _exact_keys(plan, _TOP_LEVEL, label="source archive plan")
    if plan.get("schema_version") != 1:
        raise SourceArchiveError("source archive plan schema_version must be 1")

    release = plan["release"]
    if not isinstance(release, dict):
        raise SourceArchiveError("source archive plan release must be an object")
    _exact_keys(release, _RELEASE_FIELDS, label="release")
    for field in _RELEASE_FIELDS:
        _nonempty(release, field, label="release")
    _url_or_na(release["dataset_repo"], label="release dataset_repo")
    _url_or_na(release["source_archive_repo"], label="release source_archive_repo")
    _pinned_revision(release["dataset_revision"], label="release dataset_revision")
    _pinned_revision(release["converter_revision"], label="release converter_revision")
    _pinned_revision(release["workflow_revision"], label="release workflow_revision")

    papers = plan["papers"]
    if not isinstance(papers, list) or not papers:
        raise SourceArchiveError("source archive plan papers must be a non-empty list")
    paper_ids: set[str] = set()
    for index, paper in enumerate(papers):
        _validate_paper(paper, index=index, paper_ids=paper_ids)

    tasks = plan["tasks"]
    if not isinstance(tasks, list) or not tasks:
        raise SourceArchiveError("source archive plan tasks must be a non-empty list")
    task_ids: set[str] = set()
    task_paths: set[str] = set()
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise SourceArchiveError(f"task[{index}] must be an object")
        _exact_keys(task, _TASK_FIELDS, label=f"task[{index}]")
        task_id = _nonempty(task, "task_id", label=f"task[{index}]")
        task_path = _nonempty(task, "task_path", label=f"task[{index}]")
        _relative_path(task_path, label=f"task[{index}] task_path")
        _nonempty(task, "config", label=f"task[{index}]")
        paper_id = _nonempty(task, "paper_id", label=f"task[{index}]")
        if paper_id not in paper_ids:
            raise SourceArchiveError(f"task[{index}] references unknown paper_id {paper_id!r}")
        if task["dataset_revision"] != release["dataset_revision"]:
            raise SourceArchiveError(f"task[{index}] dataset_revision disagrees with release")
        if task["converter_revision"] != release["converter_revision"]:
            raise SourceArchiveError(f"task[{index}] converter_revision disagrees with release")
        if task_id in task_ids or task_path in task_paths:
            raise SourceArchiveError(f"task[{index}] duplicates a task id or task path")
        task_ids.add(task_id)
        task_paths.add(task_path)
    return plan


def _validate_paper(paper: Any, *, index: int, paper_ids: set[str]) -> None:
    if not isinstance(paper, dict):
        raise SourceArchiveError(f"paper[{index}] must be an object")
    _exact_keys(paper, _PAPER_FIELDS, label=f"paper[{index}]")
    paper_id = _nonempty(paper, "paper_id", label=f"paper[{index}]")
    if paper_id in paper_ids:
        raise SourceArchiveError(f"paper[{index}] duplicates paper_id {paper_id!r}")
    paper_ids.add(paper_id)

    identity = paper["identity"]
    if not isinstance(identity, dict):
        raise SourceArchiveError(f"paper[{index}] identity must be an object")
    _exact_keys(identity, _IDENTITY_FIELDS, label=f"paper[{index}] identity")
    for field in (
        "title",
        "source_kind",
        "arxiv_id",
        "arxiv_version",
        "abstract_url",
        "eprint_url",
        "pdf_url",
        "license",
    ):
        _nonempty(identity, field, label=f"paper[{index}] identity")
    source_kind = identity["source_kind"]
    if source_kind not in {"arxiv", "venue-only"}:
        raise SourceArchiveError(f"paper[{index}] identity source_kind is invalid")
    _url_or_na(
        identity["abstract_url"],
        label=f"paper[{index}] abstract_url",
        allow_na=source_kind == "venue-only",
    )
    _url_or_na(
        identity["eprint_url"],
        label=f"paper[{index}] eprint_url",
        allow_na=source_kind == "venue-only",
    )
    _url_or_na(identity["pdf_url"], label=f"paper[{index}] pdf_url")
    if source_kind == "arxiv":
        if identity["source_exclusion_reason"] not in {None, ""}:
            raise SourceArchiveError(
                f"paper[{index}] arXiv identity must not have source_exclusion_reason"
            )
    else:
        if any(
            identity[field] != "not-applicable"
            for field in ("arxiv_id", "arxiv_version", "abstract_url", "eprint_url")
        ):
            raise SourceArchiveError(
                f"paper[{index}] venue-only identity must explicitly mark arXiv fields not-applicable"
            )
        _nonempty(identity, "source_exclusion_reason", label=f"paper[{index}] identity")

    code = paper["code"]
    if not isinstance(code, dict):
        raise SourceArchiveError(f"paper[{index}] code must be an object")
    _exact_keys(code, _CODE_FIELDS, label=f"paper[{index}] code")
    status = _nonempty(code, "status", label=f"paper[{index}] code")
    if status not in {"archived", "locator-only", "not-applicable"}:
        raise SourceArchiveError(f"paper[{index}] code status is invalid")
    _url_or_na(code["repository_url"], label=f"paper[{index}] code repository_url", allow_na=True)
    if status == "not-applicable":
        if code["repository_url"] != "not-applicable" or code["revision"] != "not-applicable":
            raise SourceArchiveError(
                f"paper[{index}] code without a repository must explicitly use not-applicable"
            )
        _nonempty(code, "exclusion_reason", label=f"paper[{index}] code")
    else:
        _url_or_na(code["repository_url"], label=f"paper[{index}] code repository_url")
        _pinned_revision(
            _nonempty(code, "revision", label=f"paper[{index}] code"),
            label=f"paper[{index}] code revision",
        )
        _nonempty(code, "license", label=f"paper[{index}] code")
        if status == "locator-only":
            _nonempty(code, "exclusion_reason", label=f"paper[{index}] code")
        elif code["exclusion_reason"] not in {None, ""}:
            raise SourceArchiveError(f"paper[{index}] archived code must not have exclusion_reason")

    workflow = paper["workflow"]
    if not isinstance(workflow, dict):
        raise SourceArchiveError(f"paper[{index}] workflow must be an object")
    _exact_keys(workflow, _WORKFLOW_FIELDS, label=f"paper[{index}] workflow")
    for field in _WORKFLOW_FIELDS:
        _nonempty(workflow, field, label=f"paper[{index}] workflow")
    _pinned_revision(workflow["revision"], label=f"paper[{index}] workflow revision")

    inputs = paper["inputs"]
    if not isinstance(inputs, list) or not inputs:
        raise SourceArchiveError(f"paper[{index}] inputs must be a non-empty list")
    kinds: set[str] = set()
    archive_paths: set[str] = set()
    for input_index, source in enumerate(inputs):
        _validate_input(
            source, label=f"paper[{index}] input[{input_index}]", archive_paths=archive_paths
        )
        kinds.add(source["kind"])
    required_kinds = set(_REQUIRED_INPUT_KINDS)
    if source_kind == "venue-only":
        required_kinds.remove("eprint")
    missing_kinds = sorted(required_kinds - kinds)
    if missing_kinds:
        raise SourceArchiveError(
            f"paper[{index}] misses required source inputs: {', '.join(missing_kinds)}"
        )
    if code["status"] in {"archived", "locator-only"} and "code-snapshot" not in kinds:
        raise SourceArchiveError(f"paper[{index}] code record needs a code-snapshot input")


def _validate_input(source: Any, *, label: str, archive_paths: set[str]) -> None:
    if not isinstance(source, dict):
        raise SourceArchiveError(f"{label} must be an object")
    _exact_keys(source, _INPUT_FIELDS, label=label)
    for field in ("kind", "source_url", "fetched_at", "sha256", "redistribution"):
        _nonempty(source, field, label=label)
    _url_or_na(source["source_url"], label=f"{label} source_url")
    _sha256(source["sha256"], label=f"{label} sha256")
    if (
        not isinstance(source["bytes"], int)
        or isinstance(source["bytes"], bool)
        or source["bytes"] < 0
    ):
        raise SourceArchiveError(f"{label} bytes must be a non-negative integer")
    redistribution = source["redistribution"]
    if redistribution not in {"archived", "locator-only"}:
        raise SourceArchiveError(f"{label} redistribution must be archived or locator-only")
    source_path = source["source_path"]
    archive_path = source["archive_path"]
    reason = source["exclusion_reason"]
    if source_path is not None and not isinstance(source_path, str):
        raise SourceArchiveError(f"{label} source_path must be a string or null")
    if redistribution == "archived":
        if not isinstance(source_path, str) or not source_path:
            raise SourceArchiveError(f"{label} archived input needs source_path")
        if not isinstance(archive_path, str) or not archive_path:
            raise SourceArchiveError(f"{label} archived input needs archive_path")
        relative = _relative_path(archive_path, label=f"{label} archive_path")
        if relative.as_posix() in archive_paths:
            raise SourceArchiveError(f"{label} duplicates archive_path {relative}")
        archive_paths.add(relative.as_posix())
        if reason not in {None, ""}:
            raise SourceArchiveError(f"{label} archived input must not have exclusion_reason")
    else:
        if archive_path is not None:
            raise SourceArchiveError(f"{label} locator-only input must not have archive_path")
        if not isinstance(reason, str) or not reason.strip():
            raise SourceArchiveError(f"{label} locator-only input needs exclusion_reason")


def _discover_tasks(dataset_root: Path) -> dict[str, str]:
    """Return task-id -> path from all dataset manifests beneath one release root."""
    found: dict[str, str] = {}
    manifests = sorted(dataset_root.rglob("dataset-manifest.jsonl"))
    if not manifests:
        raise SourceArchiveError(f"no dataset-manifest.jsonl beneath release root {dataset_root}")
    for manifest in manifests:
        config_root = manifest.parent
        for line_number, line in enumerate(
            manifest.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise SourceArchiveError(f"invalid JSON in {manifest}:{line_number}") from error
            if not isinstance(record, dict) or not isinstance(record.get("task_id"), str):
                raise SourceArchiveError(f"{manifest}:{line_number} needs a task_id")
            task_id = record["task_id"]
            task = config_root / task_id
            if not task.is_dir() or not (task / "task.toml").is_file():
                raise SourceArchiveError(f"published task is incomplete: {task}")
            relative = task.relative_to(dataset_root).as_posix()
            if task_id in found:
                raise SourceArchiveError(f"duplicate task id in release manifests: {task_id}")
            found[task_id] = relative
    return found


def _task_tree_hashes(dataset_root: Path) -> dict[str, str]:
    return {
        path.relative_to(dataset_root).as_posix(): sha256_file(path)
        for path in dataset_root.rglob("*")
        if path.is_file()
    }


def _require_separate_roots(dataset_root: Path, archive_root: Path) -> None:
    dataset = dataset_root.resolve()
    archive = archive_root.resolve()
    if archive == dataset or dataset in archive.parents or archive in dataset.parents:
        raise SourceArchiveError("source archive output must be outside the runnable task release")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def _portable_input(source: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in source.items() if key != "source_path"}


def build_source_archive(
    *, plan_path: Path, dataset_root: Path, output_root: Path
) -> dict[str, Any]:
    """Validate a release plan, copy allowed bytes, and write portable registry files."""
    plan = load_plan(plan_path)
    if not dataset_root.is_dir():
        raise SourceArchiveError(f"dataset release root does not exist: {dataset_root}")
    _require_separate_roots(dataset_root, output_root)
    if output_root.exists() and any(output_root.iterdir()):
        raise SourceArchiveError(f"source archive output must be empty: {output_root}")

    expected_tasks = _discover_tasks(dataset_root)
    planned_tasks = {task["task_id"]: task["task_path"] for task in plan["tasks"]}
    if expected_tasks != planned_tasks:
        missing = sorted(set(expected_tasks) - set(planned_tasks))
        unexpected = sorted(set(planned_tasks) - set(expected_tasks))
        mismatched = sorted(
            task_id
            for task_id in set(expected_tasks) & set(planned_tasks)
            if expected_tasks[task_id] != planned_tasks[task_id]
        )
        details = []
        if missing:
            details.append("missing task registrations: " + ", ".join(missing[:5]))
        if unexpected:
            details.append("unknown task registrations: " + ", ".join(unexpected[:5]))
        if mismatched:
            details.append("task paths disagree: " + ", ".join(mismatched[:5]))
        raise SourceArchiveError(
            "release registry does not cover the task release: " + "; ".join(details)
        )

    before = _task_tree_hashes(dataset_root)
    output_root.mkdir(parents=True, exist_ok=True)
    archived_inputs: list[dict[str, Any]] = []
    input_records: list[dict[str, Any]] = []
    for paper in plan["papers"]:
        for source in paper["inputs"]:
            record = {"paper_id": paper["paper_id"], **_portable_input(source)}
            source_path = Path(source["source_path"]) if source["source_path"] else None
            if source_path is None:
                raise SourceArchiveError(
                    f"archive input needs source_path for independent byte verification: {source['kind']}"
                )
            if not source_path.is_file():
                raise SourceArchiveError(f"archive input does not exist: {source_path}")
            if source_path.stat().st_size != source["bytes"]:
                raise SourceArchiveError(f"archive input bytes disagree: {source_path}")
            if sha256_file(source_path) != source["sha256"]:
                raise SourceArchiveError(f"archive input hash disagrees: {source_path}")
            if source["redistribution"] == "archived":
                assert source_path is not None
                destination = output_root / source["archive_path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_path, destination)
                if sha256_file(destination) != source["sha256"]:
                    raise SourceArchiveError(f"copied archive input hash disagrees: {destination}")
                archived_inputs.append(record)
            input_records.append(record)

    release = plan["release"]
    papers = [
        {key: value for key, value in paper.items() if key != "inputs"} for paper in plan["papers"]
    ]
    _write_jsonl(output_root / "registry" / "tasks.jsonl", plan["tasks"])
    _write_jsonl(output_root / "registry" / "papers.jsonl", papers)
    _write_jsonl(output_root / "registry" / "inputs.jsonl", input_records)
    _write_json(
        output_root / "registry" / "release.json",
        {
            **release,
            "schema_version": 1,
            "task_count": len(plan["tasks"]),
            "paper_count": len(papers),
        },
    )
    _write_json(
        output_root / "registry" / "archive-manifest.json",
        {
            "schema_version": 1,
            "archive_files": [
                {
                    "archive_path": record["archive_path"],
                    "bytes": record["bytes"],
                    "sha256": record["sha256"],
                }
                for record in archived_inputs
            ],
        },
    )
    (output_root / "README.md").write_text(
        "# Paper-Writing-Exam Source Archive\n\n"
        "This repository is immutable provenance evidence for a Paper-Writing-Exam release. "
        "It is not a Harbor task source and no runnable task reads it. "
        "Use `registry/release.json` and the JSONL registries to find a task's paper "
        "and the exact archived or locator-only construction inputs.\n",
        encoding="utf-8",
    )
    after = _task_tree_hashes(dataset_root)
    if before != after:
        raise SourceArchiveError("building the source archive changed the runnable task release")
    return validate_source_archive(
        plan_path=plan_path,
        dataset_root=dataset_root,
        archive_root=output_root,
    )


def validate_source_archive(
    *, plan_path: Path, dataset_root: Path, archive_root: Path
) -> dict[str, Any]:
    """Recheck registry coverage and all copied bytes without rebuilding tasks."""
    plan = load_plan(plan_path)
    _require_separate_roots(dataset_root, archive_root)
    if not archive_root.is_dir():
        raise SourceArchiveError(f"source archive root does not exist: {archive_root}")
    expected_tasks = _discover_tasks(dataset_root)
    tasks_path = archive_root / "registry" / "tasks.jsonl"
    if not tasks_path.is_file():
        raise SourceArchiveError(f"source archive task registry missing: {tasks_path}")
    registered = {
        record["task_id"]: record["task_path"]
        for record in _read_jsonl(tasks_path, label="source archive task registry")
    }
    if registered != expected_tasks:
        raise SourceArchiveError("source archive task registry does not match the task release")
    release = _read_json(archive_root / "registry" / "release.json", label="source archive release")
    expected_release = {
        **plan["release"],
        "schema_version": 1,
        "task_count": len(plan["tasks"]),
        "paper_count": len(plan["papers"]),
    }
    if release != expected_release:
        raise SourceArchiveError("source archive release registry disagrees with the approved plan")
    expected_papers = [
        {key: value for key, value in paper.items() if key != "inputs"} for paper in plan["papers"]
    ]
    actual_papers = _read_jsonl(archive_root / "registry" / "papers.jsonl", label="paper registry")
    if actual_papers != expected_papers:
        raise SourceArchiveError("source archive paper registry disagrees with the approved plan")
    expected_inputs = [
        {"paper_id": paper["paper_id"], **_portable_input(source)}
        for paper in plan["papers"]
        for source in paper["inputs"]
    ]
    actual_inputs = _read_jsonl(archive_root / "registry" / "inputs.jsonl", label="input registry")
    if actual_inputs != expected_inputs:
        raise SourceArchiveError("source archive input registry disagrees with the approved plan")
    expected_archived = []
    for paper in plan["papers"]:
        for source in paper["inputs"]:
            if source["redistribution"] != "archived":
                continue
            path = archive_root / source["archive_path"]
            if not path.is_file():
                raise SourceArchiveError(f"archived input missing: {path}")
            if path.stat().st_size != source["bytes"] or sha256_file(path) != source["sha256"]:
                raise SourceArchiveError(f"archived input integrity failure: {path}")
            expected_archived.append(source["archive_path"])
    manifest = _read_json(
        archive_root / "registry" / "archive-manifest.json", label="archive manifest"
    )
    actual_archived = [entry.get("archive_path") for entry in manifest.get("archive_files", [])]
    if sorted(actual_archived) != sorted(expected_archived):
        raise SourceArchiveError("archive manifest does not list exactly the copied inputs")
    return {
        "ok": True,
        "task_count": len(expected_tasks),
        "paper_count": len(plan["papers"]),
        "archived_input_count": len(expected_archived),
        "dataset_revision": plan["release"]["dataset_revision"],
        "source_archive_tag": plan["release"]["source_archive_tag"],
    }


def _read_jsonl(path: Path, *, label: str) -> list[dict[str, Any]]:
    records = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as error:
        raise SourceArchiveError(f"{label} missing: {path}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise SourceArchiveError(f"invalid JSON in {path}:{line_number}") from error
        if not isinstance(value, dict):
            raise SourceArchiveError(f"{path}:{line_number} must be an object")
        records.append(value)
    return records
