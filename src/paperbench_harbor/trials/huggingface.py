"""Host-side Hugging Face publication for sanitized trial files."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
import tarfile
import tempfile
from collections.abc import Callable
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any

from paperbench_harbor.trials.export import (
    TrialExportError,
    _check_jsonl_values,
    _check_secret_bytes,
    _scan_file,
)

DATASET_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")


class TrialUploadError(RuntimeError):
    """Raised when a sanitized local export cannot be published."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _validate_finite_json(value: Any, source: Path) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise TrialUploadError(f"index contains a non-finite number: {source}")
    if isinstance(value, dict):
        for item in value.values():
            _validate_finite_json(item, source)
    elif isinstance(value, list):
        for item in value:
            _validate_finite_json(item, source)


def _validate_trial_index_row(row: dict[str, Any], source: Path) -> None:
    required = {
        "schema_version",
        "trial_id",
        "task_id",
        "benchmark",
        "benchmark_protocol",
        "benchmark_hf_repo",
        "benchmark_hf_revision",
        "harbor_repo_commit",
        "task_checksum",
        "agent_name",
        "agent_version",
        "integration_commit",
        "model",
        "provider",
        "agent_config_hash",
        "status",
        "official_metrics",
        "artifact_archive",
        "artifact_sha256",
        "sanitization_version",
    }
    if not required.issubset(row):
        raise TrialUploadError(f"trial index row is missing required fields: {source}")
    if row.get("schema_version") != "1.0" or row.get("sanitization_version") != "1.2":
        raise TrialUploadError(f"trial index row has an unsupported schema version: {source}")
    text_fields = {
        "trial_id",
        "task_id",
        "benchmark",
        "benchmark_protocol",
        "benchmark_hf_repo",
        "harbor_repo_commit",
        "task_checksum",
        "agent_name",
        "agent_version",
        "integration_commit",
        "model",
        "provider",
    }
    if any(not isinstance(row.get(field), str) or not row[field] for field in text_fields):
        raise TrialUploadError(f"trial index row has invalid provenance fields: {source}")
    if not isinstance(row.get("benchmark_hf_revision"), str) or not re.fullmatch(
        r"[0-9a-fA-F]{40}", row["benchmark_hf_revision"]
    ):
        raise TrialUploadError(f"trial index row has an invalid benchmark revision: {source}")
    if not isinstance(row.get("agent_config_hash"), str) or not re.fullmatch(
        r"[0-9a-fA-F]{64}", row["agent_config_hash"]
    ):
        raise TrialUploadError(f"trial index row has an invalid agent config hash: {source}")
    if row.get("status") not in {"completed", "failed"}:
        raise TrialUploadError(f"trial index row has an invalid status: {source}")
    if not isinstance(row.get("official_metrics"), dict):
        raise TrialUploadError(f"trial index row has invalid official_metrics: {source}")
    for field in ("run_id", "started_at", "finished_at"):
        if field in row and row[field] is not None and not isinstance(row[field], str):
            raise TrialUploadError(f"trial index row has an invalid {field}: {source}")
    if "duration_seconds" in row and row["duration_seconds"] is not None and not _finite_number(
        row["duration_seconds"]
    ):
        raise TrialUploadError(f"trial index row has an invalid duration: {source}")
    if "harbor_reward" in row and row["harbor_reward"] is not None and (
        isinstance(row["harbor_reward"], bool)
        or isinstance(row["harbor_reward"], float)
        and not math.isfinite(row["harbor_reward"])
        or not isinstance(row["harbor_reward"], (str, int, float, dict, list))
    ):
        raise TrialUploadError(f"trial index row has an invalid reward: {source}")
    if "event_count" in row and (
        isinstance(row["event_count"], bool)
        or not isinstance(row["event_count"], int)
        or row["event_count"] < 0
    ):
        raise TrialUploadError(f"trial index row has an invalid event count: {source}")
    if not isinstance(row.get("artifact_archive"), str) or not row["artifact_archive"].startswith(
        "artifacts/"
    ):
        raise TrialUploadError(f"trial index row has an invalid artifact path: {source}")
    if not isinstance(row.get("artifact_sha256"), str) or not re.fullmatch(
        r"[0-9a-fA-F]{64}", row["artifact_sha256"]
    ):
        raise TrialUploadError(f"trial index row has an invalid artifact hash: {source}")


def _validate_event_index_row(row: dict[str, Any], source: Path) -> None:
    required = {"schema_version", "trial_id", "trajectory_path", "sequence", "step_id", "source", "event"}
    if not required.issubset(row):
        raise TrialUploadError(f"event index row is missing required fields: {source}")
    if (
        row.get("schema_version") != "1.0"
        or not isinstance(row.get("trial_id"), str)
        or not row["trial_id"]
    ):
        raise TrialUploadError(f"event index row has invalid identity fields: {source}")
    if (
        not isinstance(row.get("trajectory_path"), str)
        or not row["trajectory_path"]
        or not isinstance(row.get("event"), dict)
    ):
        raise TrialUploadError(f"event index row has invalid payload fields: {source}")
    if "timestamp" in row and row["timestamp"] is not None and not isinstance(
        row["timestamp"], str
    ):
        raise TrialUploadError(f"event index row has an invalid timestamp: {source}")
    if (
        isinstance(row.get("sequence"), bool)
        or not isinstance(row.get("sequence"), int)
        or row["sequence"] < 0
        or isinstance(row.get("step_id"), bool)
        or not isinstance(row.get("step_id"), int)
        or row["step_id"] < 1
        or row.get("source") not in {"system", "user", "agent"}
    ):
        raise TrialUploadError(f"event index row has invalid sequence or source fields: {source}")


def _validate_manifest(manifest: dict[str, Any], relative: str) -> tuple[str, str]:
    if not isinstance(manifest, dict):
        raise TrialUploadError(f"invalid trial manifest identity: {relative}")
    trial_id = manifest.get("trial_id")
    archive = manifest.get("artifact_archive")
    if (
        not isinstance(trial_id, str)
        or not trial_id
        or relative != f"manifests/{trial_id}.json"
        or archive != f"artifacts/{trial_id}.tar.gz"
        or manifest.get("schema_version") != "1.0"
        or manifest.get("sanitization_version") != "1.2"
        or not isinstance(manifest.get("files"), list)
        or not isinstance(manifest.get("source_result_sha256"), str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", manifest["source_result_sha256"])
        or not isinstance(manifest.get("artifact_sha256"), str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", manifest["artifact_sha256"])
    ):
        raise TrialUploadError(f"invalid trial manifest identity: {relative}")
    return trial_id, archive


def _verify_archive_manifest(archive_path: Path, manifest: dict[str, Any], relative: str) -> None:
    """Verify every public archive member against its sanitized manifest."""
    try:
        _scan_file(archive_path, Path(relative))
        expected: dict[str, tuple[int, str]] = {}
        for item in manifest["files"]:
            if not isinstance(item, dict):
                raise TrialUploadError(f"invalid trial manifest file entry: {relative}")
            name = item.get("path")
            size = item.get("size_bytes")
            digest = item.get("sha256")
            if (
                not isinstance(name, str)
                or not name
                or not isinstance(size, int)
                or isinstance(size, bool)
                or size < 0
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-fA-F]{64}", digest)
                or name in expected
            ):
                raise TrialUploadError(f"invalid trial manifest file entry: {relative}")
            expected[name] = (size, digest.lower())

        actual: dict[str, tuple[int, str]] = {}
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile() or member.name in actual:
                    raise TrialUploadError(f"invalid trial archive member: {relative}")
                handle = archive.extractfile(member)
                if handle is None:
                    raise TrialUploadError(f"invalid trial archive member: {relative}")
                digest = hashlib.sha256()
                size = 0
                with handle:
                    for chunk in iter(partial(handle.read, 1024 * 1024), b""):
                        digest.update(chunk)
                        size += len(chunk)
                actual[member.name] = (size, digest.hexdigest())
        if actual != expected:
            raise TrialUploadError(f"trial archive does not match manifest: {relative}")
        result = actual.get("harbor/result.json")
        if result is None or result[1] != manifest["source_result_sha256"].lower():
            raise TrialUploadError(f"trial result does not match manifest: {relative}")
    except (OSError, tarfile.TarError) as exc:
        raise TrialUploadError(f"invalid compressed artifact: {relative}") from exc


def validate_dataset_repo(repo_id: str) -> str:
    """Validate a Hub dataset repository ID without contacting the Hub."""
    value = repo_id.strip()
    if not DATASET_REPO_RE.fullmatch(value):
        raise ValueError("dataset_repo must be an HF repository ID in 'namespace/name' form")
    return value


def _local_file(output_dir: Path, relative: str) -> tuple[Path, str]:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise TrialUploadError(f"invalid local export path: {relative!r}")
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or "." in posix.parts:
        raise TrialUploadError(f"invalid local export path: {relative!r}")
    normalized = posix.as_posix()
    root = output_dir.resolve()
    candidate = root / Path(*posix.parts)
    current = root
    for part in posix.parts:
        current /= part
        if current.is_symlink():
            raise TrialUploadError(f"local export file is missing or unsafe: {relative}")
    path = candidate.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise TrialUploadError(f"local export path escapes output directory: {relative!r}") from exc
    if not path.is_file() or path.is_symlink():
        raise TrialUploadError(f"local export file is missing or unsafe: {relative}")
    return path, normalized


def _validate_upload_file(path: Path, relative: str) -> None:
    allowed = (
        relative in {"data/trials.jsonl", "data/events.jsonl"}
        or relative.startswith("manifests/") and relative.endswith(".json")
        or relative.startswith("artifacts/") and relative.endswith(".tar.gz")
    )
    if not allowed:
        raise TrialUploadError(f"refusing unsupported trial upload path: {relative}")
    try:
        _scan_file(path, Path(relative))
    except TrialExportError as exc:
        raise TrialUploadError(str(exc)) from exc


def _open_upload_source(root_fd: int, relative: Path) -> Any:
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    directory_fd = os.dup(root_fd)
    try:
        for part in relative.parts[:-1]:
            next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(relative.name, file_flags, dir_fd=directory_fd)
        return os.fdopen(file_fd, "rb")
    except OSError as exc:
        raise TrialUploadError(f"cannot safely read trial upload file: {relative}") from exc
    finally:
        os.close(directory_fd)


def _open_upload_snapshot(path: Path, relative: str) -> Any:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        file_fd = os.open(path, flags)
        handle = os.fdopen(file_fd, "rb")
    except OSError as exc:
        raise TrialUploadError(f"cannot safely retain trial upload file: {relative}") from exc
    metadata = os.fstat(handle.fileno())
    if not stat.S_ISREG(metadata.st_mode):
        handle.close()
        raise TrialUploadError(f"refusing non-regular trial upload file: {relative}")
    return handle


def _merge_jsonl(local: Path, remote: Path | None, *, events: bool) -> str:
    """Merge local and remote indexes without duplicating trial rows."""
    rows: list[dict[str, Any]] = []
    seen_trials: dict[str, dict[str, Any]] = {}
    seen_lines: set[str] = set()
    for source in (remote, local):
        if source is None:
            continue
        for line in source.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line, parse_constant=_reject_json_constant)
            except (ValueError, json.JSONDecodeError) as exc:
                raise TrialUploadError(f"invalid trial index: {source}") from exc
            if not isinstance(row, dict):
                raise TrialUploadError(f"trial index row is not an object: {source}")
            _validate_finite_json(row, source)
            if events:
                _validate_event_index_row(row, source)
            else:
                _validate_trial_index_row(row, source)
            key = json.dumps(row, sort_keys=True, separators=(",", ":"))
            if events:
                if key in seen_lines:
                    continue
                seen_lines.add(key)
            else:
                trial_id = row.get("trial_id")
                if not isinstance(trial_id, str):
                    raise TrialUploadError(f"trial index row has no trial_id: {source}")
                previous = seen_trials.get(trial_id)
                if previous is not None:
                    if previous != row:
                        raise TrialUploadError(f"remote trial index conflicts for trial {trial_id}")
                    continue
                seen_trials[trial_id] = row
            rows.append(row)
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def _remote_file(
    repo_id: str,
    filename: str,
    revision: str,
    *,
    enabled: bool,
    downloader: Callable[[str, str, str], Path | str | None] | None = None,
) -> Path | None:
    """Download one remote index/manifest when a real Hub client is in use."""
    if not enabled:
        return None
    if downloader is not None:
        try:
            downloaded = downloader(repo_id, filename, revision)
        except Exception as exc:
            try:
                from huggingface_hub.utils import EntryNotFoundError
            except ImportError:
                pass
            else:
                if isinstance(exc, EntryNotFoundError):
                    return None
            raise
        return Path(downloaded) if downloaded is not None else None
    try:
        from huggingface_hub import hf_hub_download
        from huggingface_hub.utils import EntryNotFoundError
    except ImportError as exc:  # pragma: no cover
        raise TrialUploadError("huggingface-hub is required for upload") from exc
    try:
        return Path(
            hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                repo_type="dataset",
                revision=revision,
            )
        )
    except EntryNotFoundError:
        return None


def upload_export(
    output_dir: Path,
    repo_id: str,
    relative_paths: list[str],
    *,
    revision: str = "main",
    parent_commit: str | None = None,
    commit_message: str = "Add sanitized Harbor trial export",
    api: Any | None = None,
    downloader: Callable[[str, str, str], Path | str | None] | None = None,
) -> str:
    """Upload exactly ``relative_paths`` and return the immutable commit SHA.

    Authentication is intentionally delegated to ``huggingface_hub``'s normal
    host-side token resolution.  No token is accepted as a plugin argument or
    written to a trial, report, or command log.
    """
    repo_id = validate_dataset_repo(repo_id)
    output_dir = output_dir.expanduser().absolute()
    paths: list[tuple[Path, str]] = []
    for relative in sorted(set(relative_paths)):
        path, normalized = _local_file(output_dir, relative)
        _validate_upload_file(path, normalized)
        paths.append((path, normalized))
    if not paths:
        raise TrialUploadError("no local export files selected for upload")

    if api is None:
        try:
            from huggingface_hub import CommitOperationAdd, HfApi
        except ImportError as exc:  # pragma: no cover - exercised in an install test
            raise TrialUploadError(
                "huggingface-hub is required for upload; install the [trials] extra"
            ) from exc
        api = HfApi()
    else:
        from huggingface_hub import CommitOperationAdd

    remote_downloader = downloader
    if remote_downloader is None:
        api_downloader = getattr(api, "hf_hub_download", None)
        if callable(api_downloader):
            remote_downloader = lambda repo, filename, ref: api_downloader(
                repo_id=repo, filename=filename, repo_type="dataset", revision=ref
            )

    # The API creates the repository if needed.  ``exist_ok`` makes reruns
    # harmless while preserving the exporter-level duplicate protection.
    api.create_repo(repo_id, repo_type="dataset", exist_ok=True)
    current_sha = None
    dataset_info = getattr(api, "dataset_info", None)
    if callable(dataset_info):
        info = dataset_info(repo_id, revision=revision)
        current_sha = getattr(info, "sha", None)

    # Merge aggregate indexes with the remote version before creating a commit;
    # uploading a fresh local staging directory must not discard old trials.
    temporary_paths: list[Path] = []
    upload_handles: dict[str, Any] = {}
    root_fd: int | None = None
    try:
        try:
            root_fd = os.open(
                output_dir,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0),
            )
            root_stat = os.fstat(root_fd)
            if not stat.S_ISDIR(root_stat.st_mode):
                raise TrialUploadError(f"trial output directory is not a directory: {output_dir}")
        except OSError as exc:
            raise TrialUploadError(f"cannot safely open trial output directory: {output_dir}") from exc
        snapshotted_paths: list[tuple[Path, str]] = []
        for path, relative in paths:
            with tempfile.NamedTemporaryFile(prefix="paper-trial-upload-", delete=False) as handle:
                snapshot = Path(handle.name)
                temporary_paths.append(snapshot)
                with _open_upload_source(root_fd, Path(relative)) as source:
                    before = os.fstat(source.fileno())
                    if not stat.S_ISREG(before.st_mode):
                        raise TrialUploadError(f"refusing non-regular trial upload file: {relative}")
                    shutil.copyfileobj(source, handle)
                    after = os.fstat(source.fileno())
                    if (
                        before.st_dev,
                        before.st_ino,
                        before.st_size,
                        before.st_mtime_ns,
                        before.st_ctime_ns,
                    ) != (
                        after.st_dev,
                        after.st_ino,
                        after.st_size,
                        after.st_mtime_ns,
                        after.st_ctime_ns,
                    ):
                        raise TrialUploadError(f"trial upload file changed while reading: {relative}")
            _validate_upload_file(snapshot, relative)
            upload_handles[relative] = _open_upload_snapshot(snapshot, relative)
            snapshotted_paths.append((snapshot, relative))
        paths = snapshotted_paths
        remote_files = set()
        list_repo_files = getattr(api, "list_repo_files", None)
        if callable(list_repo_files):
            remote_files = set(list_repo_files(repo_id, repo_type="dataset", revision=revision))
        remote_enabled = callable(list_repo_files) or downloader is not None
        by_name = {relative: path for path, relative in paths}
        trial_index_for_check: Path | None = None
        for filename in ("data/trials.jsonl", "data/events.jsonl"):
            local = by_name.get(filename)
            remote = None
            if filename in remote_files:
                remote = _remote_file(
                    repo_id,
                    filename,
                    revision,
                    enabled=remote_enabled,
                    downloader=remote_downloader,
                )
                if remote is None:
                    raise TrialUploadError(f"remote index is unavailable: {filename}")
            if local is None:
                if remote is not None:
                    _merge_jsonl(remote, None, events=filename.endswith("events.jsonl"))
                    if filename == "data/trials.jsonl":
                        trial_index_for_check = remote
                continue
            merged = _merge_jsonl(local, remote, events=filename.endswith("events.jsonl"))
            try:
                _check_secret_bytes(merged.encode("utf-8"), Path(filename))
                _check_jsonl_values(merged, Path(filename))
            except TrialExportError as exc:
                raise TrialUploadError(str(exc)) from exc
            with tempfile.NamedTemporaryFile(prefix="paper-trial-index-", delete=False) as handle:
                temporary = Path(handle.name)
            temporary.write_text(merged, encoding="utf-8")
            temporary_paths.append(temporary)
            by_name[filename] = temporary
            previous_handle = upload_handles.pop(filename, None)
            if previous_handle is not None:
                previous_handle.close()
            upload_handles[filename] = _open_upload_snapshot(temporary, filename)
            if filename == "data/trials.jsonl":
                trial_index_for_check = temporary

        remote_manifest_paths = {
            relative
            for relative in remote_files
            if relative.startswith("manifests/")
            and relative.endswith(".json")
            and relative != "manifests/release.json"
        }
        remote_archive_paths = {
            relative
            for relative in remote_files
            if relative.startswith("artifacts/") and relative.endswith(".tar.gz")
        }
        expected_remote_archives = {
            f"artifacts/{PurePosixPath(relative).stem}.tar.gz"
            for relative in remote_manifest_paths
        }
        expected_remote_manifests = {
            f"manifests/{PurePosixPath(relative).name.removesuffix('.tar.gz')}.json"
            for relative in remote_archive_paths
        }
        if (
            expected_remote_archives != remote_archive_paths
            or expected_remote_manifests != remote_manifest_paths
        ):
            raise TrialUploadError("remote trial manifest/archive mapping is incomplete")
        manifest_trials: dict[str, dict[str, Any]] = {}
        for relative in remote_manifest_paths:
            remote_manifest = _remote_file(
                repo_id,
                relative,
                revision,
                enabled=remote_enabled,
                downloader=remote_downloader,
            )
            if remote_manifest is None:
                raise TrialUploadError(f"remote trial manifest is unavailable: {relative}")
            try:
                remote_data = json.loads(remote_manifest.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TrialUploadError(f"invalid remote trial manifest: {relative}") from exc
            trial_id, archive = _validate_manifest(remote_data, relative)
            if archive not in remote_archive_paths:
                raise TrialUploadError(f"remote trial manifest archive is missing: {archive}")
            remote_archive = _remote_file(
                repo_id,
                archive,
                revision,
                enabled=remote_enabled,
                downloader=remote_downloader,
            )
            if remote_archive is None or _sha256_file(remote_archive) != remote_data["artifact_sha256"]:
                raise TrialUploadError(f"remote archive conflicts for {archive}")
            manifest_trials[trial_id] = remote_data

        local_manifests: dict[str, tuple[str, dict[str, Any]]] = {}
        for relative, path in by_name.items():
            if not relative.startswith("manifests/"):
                continue
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TrialUploadError(f"invalid local trial manifest: {relative}") from exc
            trial_id, archive = _validate_manifest(manifest, relative)
            if (
                ".." in PurePosixPath(archive).parts
                or not isinstance(manifest.get("artifact_sha256"), str)
                or not re.fullmatch(r"[0-9a-fA-F]{64}", manifest["artifact_sha256"])
            ):
                raise TrialUploadError(f"invalid local trial manifest: {relative}")
            if archive in local_manifests:
                raise TrialUploadError(f"duplicate local manifest for archive: {archive}")
            local_manifests[archive] = (relative, manifest)
            manifest_trials[trial_id] = manifest
        for relative in by_name:
            if relative.startswith("artifacts/") and relative not in local_manifests:
                raise TrialUploadError(f"local archive has no manifest: {relative}")
        for archive, (_manifest_path, local_manifest) in local_manifests.items():
            local_archive = by_name.get(archive)
            if local_archive is not None and _sha256_file(local_archive) != local_manifest[
                "artifact_sha256"
            ]:
                raise TrialUploadError(f"local archive conflicts for {archive}")
            if local_archive is not None:
                _verify_archive_manifest(local_archive, local_manifest, archive)
            if local_archive is None and archive not in remote_files:
                raise TrialUploadError(f"local manifest archive is not selected: {archive}")
            if archive in remote_files:
                remote_archive = _remote_file(
                    repo_id,
                    archive,
                    revision,
                    enabled=remote_enabled,
                    downloader=remote_downloader,
                )
                if remote_archive is None or _sha256_file(remote_archive) != local_manifest[
                    "artifact_sha256"
                ]:
                    raise TrialUploadError(f"remote archive conflicts for {archive}")
        if trial_index_for_check is not None:
            for line in trial_index_for_check.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line, parse_constant=_reject_json_constant)
                if not isinstance(row, dict):
                    raise TrialUploadError("trial index row is not an object")
                trial_id = row.get("trial_id")
                manifest = manifest_trials.get(trial_id)
                if manifest is None:
                    raise TrialUploadError(f"trial index has no manifest for {trial_id}")
                if (
                    row.get("artifact_archive") != manifest.get("artifact_archive")
                    or row.get("artifact_sha256") != manifest.get("artifact_sha256")
                ):
                    raise TrialUploadError(f"trial index conflicts with manifest for {trial_id}")
        filtered: list[tuple[Path, str]] = []
        for relative, path in by_name.items():
            if relative.startswith("manifests/"):
                remote_manifest = _remote_file(
                    repo_id,
                    relative,
                    revision,
                    enabled=remote_enabled,
                    downloader=remote_downloader,
                )
                if remote_manifest is not None:
                    local_manifest = json.loads(path.read_text(encoding="utf-8"))
                    remote_data = json.loads(remote_manifest.read_text(encoding="utf-8"))
                    if local_manifest != remote_data:
                        raise TrialUploadError(f"remote trial conflicts for {relative}")
                    archive = local_manifest.get("artifact_archive")
                    if isinstance(archive, str) and archive in remote_files:
                        remote_archive = _remote_file(
                            repo_id,
                            archive,
                            revision,
                            enabled=remote_enabled,
                            downloader=remote_downloader,
                        )
                        if remote_archive is None or _sha256_file(remote_archive) != local_manifest.get(
                            "artifact_sha256"
                        ):
                            raise TrialUploadError(f"remote archive conflicts for {archive}")
                        continue
            if relative.startswith("artifacts/") and relative in remote_files:
                manifest_entry = local_manifests.get(relative)
                if manifest_entry is None:
                    raise TrialUploadError(f"remote archive has no local manifest: {relative}")
                _manifest_path, local_manifest = manifest_entry
                remote_archive = _remote_file(
                    repo_id,
                    relative,
                    revision,
                    enabled=remote_enabled,
                    downloader=remote_downloader,
                )
                if remote_archive is None or _sha256_file(remote_archive) != local_manifest.get(
                    "artifact_sha256"
                ):
                    raise TrialUploadError(f"remote archive conflicts for {relative}")
                continue
            filtered.append((path, relative))
        paths = filtered
        if not paths:
            if isinstance(current_sha, str) and re.fullmatch(r"[0-9a-fA-F]{40}", current_sha):
                return current_sha
            raise TrialUploadError("all selected trial files are already published")

        operations = []
        for path, relative in paths:
            handle = upload_handles[relative]
            handle.seek(0)
            operations.append(CommitOperationAdd(path_or_fileobj=handle, path_in_repo=relative))
        try:
            commit = api.create_commit(
                repo_id=repo_id,
                repo_type="dataset",
                operations=operations,
                commit_message=commit_message,
                revision=revision,
                parent_commit=parent_commit or current_sha,
            )
        except Exception as exc:
            raise TrialUploadError(f"Hugging Face upload failed for {repo_id}: {exc}") from exc
    finally:
        for handle in upload_handles.values():
            handle.close()
        for temporary in temporary_paths:
            temporary.unlink(missing_ok=True)
        if root_fd is not None:
            os.close(root_fd)
    commit_sha = getattr(commit, "oid", None)
    if not isinstance(commit_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", commit_sha):
        raise TrialUploadError("Hugging Face upload returned no immutable commit SHA")
    return commit_sha
