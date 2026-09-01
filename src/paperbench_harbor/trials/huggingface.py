"""Host-side Hugging Face publication for sanitized trial files."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

DATASET_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")


class TrialUploadError(RuntimeError):
    """Raised when a sanitized local export cannot be published."""


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
    path = (root / Path(*posix.parts)).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise TrialUploadError(f"local export path escapes output directory: {relative!r}") from exc
    if not path.is_file() or path.is_symlink():
        raise TrialUploadError(f"local export file is missing or unsafe: {relative}")
    return path, normalized


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
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TrialUploadError(f"invalid trial index: {source}") from exc
            if not isinstance(row, dict):
                raise TrialUploadError(f"trial index row is not an object: {source}")
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
    repo_id: str, filename: str, revision: str, *, enabled: bool
) -> Path | None:
    """Download one remote index/manifest when a real Hub client is in use."""
    try:
        from huggingface_hub import EntryNotFoundError, hf_hub_download
    except ImportError as exc:  # pragma: no cover
        raise TrialUploadError("huggingface-hub is required for upload") from exc
    if enabled:
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
        paths.append(_local_file(output_dir, relative))
    if not paths:
        raise TrialUploadError("no local export files selected for upload")

    injected_api = api is not None
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
    try:
        by_name = {relative: path for path, relative in paths}
        for filename in ("data/trials.jsonl", "data/events.jsonl"):
            local = by_name.get(filename)
            if local is None:
                continue
            remote = _remote_file(repo_id, filename, revision, enabled=not injected_api)
            merged = _merge_jsonl(local, remote, events=filename.endswith("events.jsonl"))
            with tempfile.NamedTemporaryFile(prefix="paper-trial-index-", delete=False) as handle:
                temporary = Path(handle.name)
            temporary.write_text(merged, encoding="utf-8")
            temporary_paths.append(temporary)
            by_name[filename] = temporary

        remote_files = set()
        list_repo_files = getattr(api, "list_repo_files", None)
        if callable(list_repo_files):
            remote_files = set(list_repo_files(repo_id, repo_type="dataset", revision=revision))
        filtered: list[tuple[Path, str]] = []
        for relative, path in by_name.items():
            if relative.startswith("manifests/"):
                remote_manifest = _remote_file(api, repo_id, relative, revision)
                if remote_manifest is not None:
                    local_manifest = json.loads(path.read_text(encoding="utf-8"))
                    remote_data = json.loads(remote_manifest.read_text(encoding="utf-8"))
                    if local_manifest.get("artifact_sha256") != remote_data.get("artifact_sha256"):
                        raise TrialUploadError(f"remote trial conflicts for {relative}")
                    archive = local_manifest.get("artifact_archive")
                    if isinstance(archive, str) and archive in remote_files:
                        continue
            if relative.startswith("artifacts/") and relative in remote_files:
                continue
            filtered.append((path, relative))
        paths = filtered
        if not paths:
            if isinstance(current_sha, str) and re.fullmatch(r"[0-9a-fA-F]{40}", current_sha):
                return current_sha
            raise TrialUploadError("all selected trial files are already published")

        operations = [
            CommitOperationAdd(path_or_fileobj=path, path_in_repo=relative)
            for path, relative in paths
        ]
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
        for temporary in temporary_paths:
            temporary.unlink(missing_ok=True)
    commit_sha = getattr(commit, "oid", None)
    if not isinstance(commit_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", commit_sha):
        raise TrialUploadError("Hugging Face upload returned no immutable commit SHA")
    return commit_sha
