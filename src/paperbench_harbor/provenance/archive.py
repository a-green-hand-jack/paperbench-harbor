"""Build and verify a separate, immutable archive of benchmark source inputs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
REGISTRY_FILENAME = "task-paper-registry.jsonl"
ARCHIVE_MANIFEST_FILENAME = "source-archive-manifest.jsonl"
ARCHIVE_METADATA_FILENAME = "archive-metadata.json"

_IGNORED_PARTS = {".git", ".cache", "__pycache__"}
PAPERRECON_CONFIGS = {
    "lifesci-paperrecon-short": "lifesci",
    "physics-paperrecon-short": "physics",
    "chemistry-paperrecon-short": "chemistry",
    "mathematics-paperrecon-short": "mathematics",
}


@dataclass(frozen=True)
class SourceLocation:
    """One archiveable source tree associated with a released task."""

    kind: str
    source: Path
    archive_path: Path
    provenance: dict[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path, *, allow_symlinks: bool = False) -> str:
    """Return a portable digest for the files below ``root``.

    Source archives reject symlinks because their targets are not portable.
    Released historical task trees can contain an upstream symlink, so their
    checksum records the link target without following it.
    """

    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda candidate: candidate.as_posix()):
        relative_path = path.relative_to(root)
        if any(part in _IGNORED_PARTS for part in relative_path.parts):
            continue
        relative = relative_path.as_posix()
        if path.is_symlink():
            if not allow_symlinks:
                raise ValueError(f"source archive does not permit symlinks: {path}")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0symlink\0")
            digest.update(os.readlink(path).encode("utf-8"))
            digest.update(b"\n")
            continue
        if not path.is_file():
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _iter_regular_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*"), key=lambda candidate: candidate.as_posix()):
        relative_parts = path.relative_to(root).parts
        if any(part in _IGNORED_PARTS for part in relative_parts):
            continue
        if path.is_symlink():
            raise ValueError(f"source archive does not permit symlinks: {path}")
        if path.is_file():
            yield path


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True))
            handle.write("\n")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON at {path}: {error.msg}") from error
    if not isinstance(data, dict):
        raise TypeError(f"expected a JSON object at {path}")
    return data


def _read_source_manifest(task_dir: Path) -> dict[str, Any]:
    path = task_dir / "tests" / "private" / "source_manifest.json"
    if not path.is_file():
        raise ValueError(f"task has no verifier-only source manifest: {task_dir}")
    return _read_json(path)


def _extract_latex_title(path: Path) -> str | None:
    if not path.is_file():
        return None
    source = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"\\title(?:\[[^\]]*\])?\s*\{([^}]*)\}", source, re.DOTALL)
    if match is None:
        return None
    return " ".join(match.group(1).split()) or None


def _paperrecon_provenance(source: Path) -> dict[str, Any]:
    path = source / "original" / "provenance.json"
    provenance = _read_json(path)
    return {
        "source_identity_kind": "arxiv_paper",
        "title": provenance.get("title"),
        "arxiv_id": provenance.get("arxiv_id"),
        "arxiv_version": provenance.get("arxiv_version"),
        "arxiv_url": (
            f"https://arxiv.org/abs/{provenance['arxiv_id']}{provenance['arxiv_version']}"
            if isinstance(provenance.get("arxiv_id"), str)
            and isinstance(provenance.get("arxiv_version"), str)
            else None
        ),
        "source_url": provenance.get("source_url"),
        "paper_license": provenance.get("license_label"),
        "paper_license_url": provenance.get("license_url"),
        "source_fetch_date": provenance.get("fetch_date"),
        "code_repository": provenance.get("code_repo"),
        "code_revision": provenance.get("code_commit"),
        "code_license": provenance.get("code_license"),
        "code_status": provenance.get("code_status"),
        "code_not_applicable_reason": provenance.get("code_not_applicable_reason"),
    }


def _source_location(
    *,
    config: str,
    task_dir: Path,
    source_manifest: dict[str, Any],
    paperwrite_source: Path,
    paperwritingbench_source: Path,
    lifesci_source: Path,
    paperrecon_sources: Mapping[str, Path] | None = None,
) -> SourceLocation:
    upstream_id = source_manifest.get("upstream_id")
    if not isinstance(upstream_id, str) or not upstream_id:
        raise ValueError(f"task source manifest lacks upstream_id: {task_dir}")
    extra = source_manifest.get("extra")
    if not isinstance(extra, dict):
        extra = {}

    if config == "paperwrite-bench-short":
        source = paperwrite_source / upstream_id
        return SourceLocation(
            kind="upstream_benchmark_record",
            source=source,
            archive_path=Path("sources") / "paperwrite-bench" / upstream_id,
            provenance={
                "source_identity_kind": "upstream_benchmark_record",
                "upstream_record_id": upstream_id,
                "title": _extract_latex_title(source / "original" / "main.tex"),
                "paper_license": "see upstream benchmark terms",
                "source_url": "https://github.com/hal-utokyo/PaperWrite-Bench",
            },
        )

    if config == "paperwritingbench-sparse-plotoff":
        venue = extra.get("venue")
        if not isinstance(venue, str) or not venue:
            raise ValueError(f"PaperWritingBench task has no venue: {task_dir}")
        source = paperwritingbench_source / "datasets" / venue / "papers" / upstream_id
        return SourceLocation(
            kind="upstream_benchmark_record",
            source=source,
            archive_path=(
                Path("sources") / "paperwritingbench" / venue / "papers" / upstream_id
            ),
            provenance={
                "source_identity_kind": "upstream_benchmark_record",
                "upstream_record_id": upstream_id,
                "venue": venue,
                "paper_license": "see upstream benchmark terms",
                "source_url": "https://github.com/yiwen-song/PaperWritingBench",
            },
        )

    if config in PAPERRECON_CONFIGS:
        domain = PAPERRECON_CONFIGS[config]
        sources = {"lifesci": lifesci_source, **dict(paperrecon_sources or {})}
        try:
            source_root = sources[domain]
        except KeyError as error:
            raise ValueError(f"no PaperRecon source root provided for domain: {domain}") from error
        source = source_root / upstream_id
        provenance = _paperrecon_provenance(source)
        return SourceLocation(
            kind="arxiv_paper",
            source=source / "original",
            archive_path=Path("sources") / f"{domain}-paperrecon" / upstream_id / "original",
            provenance=provenance,
        )

    raise ValueError(f"unsupported dataset configuration: {config}")


def _copy_source_tree(source: Path, destination: Path) -> list[dict[str, Any]]:
    if not source.is_dir():
        raise ValueError(f"missing source tree: {source}")
    records: list[dict[str, Any]] = []
    for file_path in _iter_regular_files(source):
        relative = file_path.relative_to(source)
        destination_path = destination / relative
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, destination_path)
        records.append(
            {
                "relative_path": relative.as_posix(),
                "sha256": sha256_file(destination_path),
                "size_bytes": destination_path.stat().st_size,
            }
        )
    if not records:
        raise ValueError(f"source tree has no archiveable files: {source}")
    return records


def _release_tasks(
    release_root: Path, *, included_configs: set[str] | None = None
) -> Iterable[tuple[str, Path]]:
    for config_dir in sorted(release_root.iterdir(), key=lambda path: path.name):
        if not config_dir.is_dir() or config_dir.name.startswith("."):
            continue
        if included_configs is not None and config_dir.name not in included_configs:
            continue
        for task_dir in sorted(config_dir.iterdir(), key=lambda path: path.name):
            if task_dir.is_dir() and (task_dir / "task.toml").is_file():
                yield config_dir.name, task_dir


def _archive_location_key(location: SourceLocation) -> str:
    return location.archive_path.as_posix()


def build_source_archive(
    *,
    release_root: Path,
    output_dir: Path,
    dataset_repo: str,
    dataset_revision: str,
    converter_revision: str,
    paperwrite_source: Path,
    paperwritingbench_source: Path,
    lifesci_source: Path,
    paperrecon_sources: Mapping[str, Path] | None = None,
    included_configs: set[str] | None = None,
) -> dict[str, int]:
    """Build a release-level registry and a source-only archive.

    The archive deliberately copies only the upstream input trees. It never
    copies a Harbor task directory, solution, verifier, or trial artifact.
    """

    if output_dir.exists():
        raise ValueError(f"output directory already exists: {output_dir}")
    if not dataset_revision or not converter_revision:
        raise ValueError("dataset_revision and converter_revision are required")

    output_dir.mkdir(parents=True)
    source_cache: dict[str, tuple[SourceLocation, list[dict[str, Any]]]] = {}
    registry_records: list[dict[str, Any]] = []
    tasks = list(_release_tasks(release_root, included_configs=included_configs))
    if not tasks:
        raise ValueError(f"release root has no Harbor tasks: {release_root}")

    for config, task_dir in tasks:
        source_manifest = _read_source_manifest(task_dir)
        if config == "hello-world":
            registry_records.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "dataset": {
                        "repo": dataset_repo,
                        "revision": dataset_revision,
                        "config": config,
                        "task_id": task_dir.name,
                        "task_path": f"{config}/{task_dir.name}",
                        "task_tree_sha256": sha256_tree(task_dir, allow_symlinks=True),
                    },
                    "conversion": {
                        "benchmark": source_manifest.get("benchmark"),
                        "protocol": source_manifest.get("protocol"),
                        "upstream_id": source_manifest.get("upstream_id"),
                        "upstream_revision": source_manifest.get("upstream_revision"),
                        "converter_revision": converter_revision,
                    },
                    "paper": {
                        "source_identity_kind": "first_party_smoke_task",
                        "title": "PaperBench Harbor hello-world smoke task",
                    },
                    "source_archive": {
                        "status": "not_applicable",
                        "reason": "first-party smoke task has no source paper or external workflow input",
                    },
                }
            )
            continue
        location = _source_location(
            config=config,
            task_dir=task_dir,
            source_manifest=source_manifest,
            paperwrite_source=paperwrite_source,
            paperwritingbench_source=paperwritingbench_source,
            lifesci_source=lifesci_source,
            paperrecon_sources=paperrecon_sources,
        )
        key = _archive_location_key(location)
        if key not in source_cache:
            destination = output_dir / location.archive_path
            copied_files = _copy_source_tree(location.source, destination)
            source_cache[key] = (location, copied_files)

        upstream_id = source_manifest["upstream_id"]
        registry_records.append(
            {
                "schema_version": SCHEMA_VERSION,
                "dataset": {
                    "repo": dataset_repo,
                    "revision": dataset_revision,
                    "config": config,
                    "task_id": task_dir.name,
                    "task_path": f"{config}/{task_dir.name}",
                    "task_tree_sha256": sha256_tree(task_dir, allow_symlinks=True),
                },
                "conversion": {
                    "benchmark": source_manifest.get("benchmark"),
                    "protocol": source_manifest.get("protocol"),
                    "upstream_id": upstream_id,
                    "upstream_revision": source_manifest.get("upstream_revision"),
                    "converter_revision": converter_revision,
                },
                "paper": source_cache[key][0].provenance,
                "source_archive": {
                    "dataset_path": key,
                    "tree_sha256": sha256_tree(output_dir / key),
                    "status": "archived",
                },
            }
        )

    archive_records: list[dict[str, Any]] = []
    for archive_path, (location, copied_files) in sorted(source_cache.items()):
        for file_record in copied_files:
            archive_file = f"{archive_path}/{file_record['relative_path']}"
            archive_records.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "source_archive_path": archive_path,
                    "source_kind": location.kind,
                    "file": {
                        "archive_path": archive_file,
                        "sha256": file_record["sha256"],
                        "size_bytes": file_record["size_bytes"],
                    },
                    "paper": location.provenance,
                }
            )

    _write_jsonl(output_dir / "registry" / REGISTRY_FILENAME, registry_records)
    _write_jsonl(output_dir / "manifests" / ARCHIVE_MANIFEST_FILENAME, archive_records)
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "dataset_repo": dataset_repo,
        "dataset_revision": dataset_revision,
        "converter_revision": converter_revision,
        "task_count": len(registry_records),
        "source_tree_count": len(source_cache),
        "source_file_count": len(archive_records),
    }
    (output_dir / ARCHIVE_METADATA_FILENAME).write_text(
        json.dumps(metadata, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    verify_source_archive(output_dir)
    return {
        "task_count": len(registry_records),
        "source_tree_count": len(source_cache),
        "source_file_count": len(archive_records),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSON at {path}:{line_number}: {error.msg}") from error
        if not isinstance(record, dict):
            raise TypeError(f"expected object at {path}:{line_number}")
        records.append(record)
    return records


def verify_source_archive(output_dir: Path) -> dict[str, int]:
    """Fail closed when registry coverage or archived-file hashes drift."""

    metadata = _read_json(output_dir / ARCHIVE_METADATA_FILENAME)
    registry = _read_jsonl(output_dir / "registry" / REGISTRY_FILENAME)
    archive_manifest = _read_jsonl(output_dir / "manifests" / ARCHIVE_MANIFEST_FILENAME)
    seen_tasks: set[tuple[str, str]] = set()
    for record in registry:
        dataset = record.get("dataset")
        source_archive = record.get("source_archive")
        if not isinstance(dataset, dict) or not isinstance(source_archive, dict):
            raise TypeError("registry record is missing dataset or source_archive")
        config, task_id = dataset.get("config"), dataset.get("task_id")
        archive_path = source_archive.get("dataset_path")
        if not isinstance(config, str) or not isinstance(task_id, str):
            raise TypeError("registry record has incomplete task identity")
        key = (config, task_id)
        if key in seen_tasks:
            raise ValueError(f"duplicate registry task: {config}/{task_id}")
        seen_tasks.add(key)
        if source_archive.get("status") == "not_applicable":
            if archive_path is not None:
                raise ValueError(f"non-archived record unexpectedly has a source tree: {config}/{task_id}")
            continue
        if not isinstance(archive_path, str):
            raise TypeError("archived registry record has no source tree")
        archived_tree = output_dir / archive_path
        if not archived_tree.is_dir():
            raise ValueError(f"registry references missing source tree: {archive_path}")
        if source_archive.get("tree_sha256") != sha256_tree(archived_tree):
            raise ValueError(f"archive tree hash mismatch: {archive_path}")

    for record in archive_manifest:
        file = record.get("file")
        if not isinstance(file, dict):
            raise TypeError("archive manifest record has no file")
        relative = file.get("archive_path")
        expected_sha = file.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected_sha, str):
            raise TypeError("archive manifest record has incomplete file identity")
        path = output_dir / relative
        if not path.is_file() or sha256_file(path) != expected_sha:
            raise ValueError(f"archive file hash mismatch: {relative}")

    expected_tasks = metadata.get("task_count")
    expected_files = metadata.get("source_file_count")
    if expected_tasks != len(registry) or expected_files != len(archive_manifest):
        raise ValueError("archive metadata count mismatch")
    return {"task_count": len(registry), "source_file_count": len(archive_manifest)}
