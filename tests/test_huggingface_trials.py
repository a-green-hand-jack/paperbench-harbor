from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperbench_harbor.trials import huggingface
from paperbench_harbor.trials.huggingface import (
    TrialUploadError,
    _merge_jsonl,
    upload_export,
    validate_dataset_repo,
)


def _manifest(archive: str, artifact_sha256: str, trial_id: str = "trial") -> dict[str, object]:
    result = b"{}"
    return {
        "schema_version": "1.0",
        "trial_id": trial_id,
        "artifact_archive": archive,
        "artifact_sha256": artifact_sha256,
        "files": [
            {
                "path": "harbor/result.json",
                "size_bytes": len(result),
                "sha256": hashlib.sha256(result).hexdigest(),
            }
        ],
        "source_result_sha256": hashlib.sha256(result).hexdigest(),
        "sanitization_version": "1.2",
    }


def _write_archive(path: Path, payload: bytes = b"{}", *, mtime: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as handle:
        info = tarfile.TarInfo("harbor/result.json")
        info.mtime = mtime
        info.size = len(payload)
        handle.addfile(info, io.BytesIO(payload))


def test_validate_dataset_repo() -> None:
    assert validate_dataset_repo("my-org/my-trials") == "my-org/my-trials"
    with pytest.raises(ValueError):
        validate_dataset_repo("my-org")
    with pytest.raises(ValueError):
        validate_dataset_repo("https://huggingface.co/datasets/my-org/my-trials")


def test_upload_uses_exact_files_and_returns_commit_sha(tmp_path: Path) -> None:
    from huggingface_hub import CommitOperationAdd

    (tmp_path / "artifacts").mkdir()
    _write_archive(tmp_path / "artifacts" / "trial.tar.gz")
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / "trial.json").write_text(
        json.dumps(
            _manifest(
                "artifacts/trial.tar.gz", _sha256(tmp_path / "artifacts" / "trial.tar.gz")
            )
        ),
        encoding="utf-8",
    )
    api = SimpleNamespace()
    calls: list[object] = []

    def create_repo(*args, **kwargs):
        calls.append(("create_repo", args, kwargs))

    def create_commit(**kwargs):
        calls.append(("create_commit", kwargs))
        assert all(isinstance(item, CommitOperationAdd) for item in kwargs["operations"])
        return SimpleNamespace(oid="a" * 40)

    api.create_repo = create_repo
    api.create_commit = create_commit
    sha = upload_export(
        tmp_path,
        "my-org/my-trials",
        ["artifacts/trial.tar.gz", "manifests/trial.json"],
        revision="main",
        parent_commit="b" * 40,
        api=api,
    )
    assert sha == "a" * 40
    assert calls[0][0] == "create_repo"
    assert calls[1][1]["repo_id"] == "my-org/my-trials"
    assert calls[1][1]["parent_commit"] == "b" * 40


def test_upload_rejects_missing_or_unsafe_file(tmp_path: Path) -> None:
    with pytest.raises(TrialUploadError, match="missing or unsafe"):
        upload_export(tmp_path, "my-org/my-trials", ["missing.tar.gz"], api=object())


def test_upload_rejects_symlinked_file_inside_output(tmp_path: Path) -> None:
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "secret.txt").write_text("not for upload", encoding="utf-8")
    (tmp_path / "artifacts" / "trial.tar.gz").symlink_to("../secret.txt")
    with pytest.raises(TrialUploadError, match="missing or unsafe"):
        upload_export(tmp_path, "my-org/my-trials", ["artifacts/trial.tar.gz"], api=object())


def test_upload_rejects_unsupported_or_unscanned_path(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("API_KEY=actual-secret\n", encoding="utf-8")

    with pytest.raises(TrialUploadError, match="unsupported trial upload path"):
        upload_export(tmp_path, "my-org/my-trials", [".env"], api=object())


def test_upload_rescans_archive_contents(tmp_path: Path) -> None:
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "manifests").mkdir()
    archive = tmp_path / "artifacts" / "trial.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        info = tarfile.TarInfo("workspace/.env")
        payload = b"API_KEY=actual-secret\n"
        info.size = len(payload)
        handle.addfile(info, io.BytesIO(payload))
    (tmp_path / "manifests" / "trial.json").write_text(
        json.dumps(_manifest("artifacts/trial.tar.gz", _sha256(archive))), encoding="utf-8"
    )

    with pytest.raises(TrialUploadError, match="forbidden credential/private file"):
        upload_export(
            tmp_path,
            "my-org/my-trials",
            ["artifacts/trial.tar.gz", "manifests/trial.json"],
            api=object(),
        )


def test_upload_rejects_mismatched_existing_remote_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "manifests").mkdir()
    local_archive = tmp_path / "artifacts" / "trial.tar.gz"
    _write_archive(local_archive)
    local_hash = hashlib.sha256(local_archive.read_bytes()).hexdigest()
    (tmp_path / "manifests" / "trial.json").write_text(
        json.dumps(_manifest("artifacts/trial.tar.gz", local_hash)),
        encoding="utf-8",
    )
    remote_archive = tmp_path / "remote-trial.tar.gz"
    _write_archive(remote_archive, mtime=1)
    remote_manifest = tmp_path / "remote-manifest.json"
    remote_manifest.write_text(
        json.dumps(_manifest("artifacts/trial.tar.gz", local_hash)), encoding="utf-8"
    )
    api = SimpleNamespace(
        create_repo=lambda *args, **kwargs: None,
        list_repo_files=lambda *args, **kwargs: [
            "artifacts/trial.tar.gz",
            "manifests/trial.json",
        ],
    )

    def remote_file(_repo_id: str, filename: str, _revision: str, **_kwargs: object):
        return remote_archive if filename.startswith("artifacts/") else remote_manifest

    monkeypatch.setattr(huggingface, "_remote_file", remote_file)
    with pytest.raises(TrialUploadError, match="remote archive conflicts"):
        upload_export(
            tmp_path,
            "my-org/my-trials",
            ["artifacts/trial.tar.gz", "manifests/trial.json"],
            api=api,
        )


def test_manifest_only_upload_still_verifies_remote_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "manifests").mkdir()
    local_archive = tmp_path / "artifacts" / "trial.tar.gz"
    _write_archive(local_archive)
    local_hash = hashlib.sha256(local_archive.read_bytes()).hexdigest()
    (tmp_path / "manifests" / "trial.json").write_text(
        json.dumps(_manifest("artifacts/trial.tar.gz", local_hash)),
        encoding="utf-8",
    )
    remote_archive = tmp_path / "remote-trial.tar.gz"
    _write_archive(remote_archive, mtime=1)
    remote_manifest = tmp_path / "remote-manifest.json"
    remote_manifest.write_text(
        json.dumps(_manifest("artifacts/trial.tar.gz", local_hash)), encoding="utf-8"
    )
    api = SimpleNamespace(
        create_repo=lambda *args, **kwargs: None,
        list_repo_files=lambda *args, **kwargs: [
            "artifacts/trial.tar.gz", "manifests/trial.json"
        ],
    )
    monkeypatch.setattr(
        huggingface,
        "_remote_file",
        lambda _repo_id, filename, _revision, **_kwargs: remote_archive
        if filename == "artifacts/trial.tar.gz"
        else remote_manifest,
    )

    with pytest.raises(TrialUploadError, match="remote archive conflicts"):
        upload_export(tmp_path, "my-org/my-trials", ["manifests/trial.json"], api=api)


def test_archive_only_upload_rejects_remote_archive_without_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "artifacts").mkdir()
    archive = tmp_path / "artifacts" / "trial.tar.gz"
    _write_archive(archive)
    api = SimpleNamespace(
        create_repo=lambda *args, **kwargs: None,
        list_repo_files=lambda *args, **kwargs: ["artifacts/trial.tar.gz"],
    )
    monkeypatch.setattr(
        huggingface,
        "_remote_file",
        lambda *_args, **_kwargs: archive,
    )

    with pytest.raises(TrialUploadError, match="manifest/archive mapping is incomplete"):
        upload_export(tmp_path, "my-org/my-trials", ["artifacts/trial.tar.gz"], api=api)


def test_upload_rejects_local_archive_manifest_hash_mismatch(tmp_path: Path) -> None:
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "manifests").mkdir()
    _write_archive(tmp_path / "artifacts" / "trial.tar.gz", b"actual archive")
    (tmp_path / "manifests" / "trial.json").write_text(
        json.dumps(_manifest("artifacts/trial.tar.gz", "0" * 64)),
        encoding="utf-8",
    )
    api = SimpleNamespace(create_repo=lambda *args, **kwargs: None)

    with pytest.raises(TrialUploadError, match="local archive conflicts"):
        upload_export(
            tmp_path,
            "my-org/my-trials",
            ["artifacts/trial.tar.gz", "manifests/trial.json"],
            api=api,
        )


def test_upload_rejects_corrupt_unrelated_remote_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "manifests").mkdir()
    archive = tmp_path / "artifacts" / "trial.tar.gz"
    _write_archive(archive, b"local archive")
    (tmp_path / "manifests" / "trial.json").write_text(
        json.dumps(_manifest("artifacts/trial.tar.gz", _sha256(archive))), encoding="utf-8"
    )
    remote_archive = tmp_path / "remote.tar.gz"
    _write_archive(remote_archive)
    remote_manifest = tmp_path / "remote.json"
    remote_manifest.write_text(
        json.dumps(_manifest("artifacts/remote.tar.gz", "0" * 64, trial_id="remote")),
        encoding="utf-8",
    )
    api = SimpleNamespace(
        create_repo=lambda *args, **kwargs: None,
        list_repo_files=lambda *args, **kwargs: [
            "artifacts/remote.tar.gz",
            "manifests/remote.json",
        ],
    )
    monkeypatch.setattr(
        huggingface,
        "_remote_file",
        lambda _repo_id, filename, _revision, **_kwargs: remote_archive
        if filename == "artifacts/remote.tar.gz"
        else remote_manifest,
    )

    with pytest.raises(TrialUploadError, match="remote archive conflicts"):
        upload_export(
            tmp_path,
            "my-org/my-trials",
            ["artifacts/trial.tar.gz", "manifests/trial.json"],
            api=api,
        )


def _valid_trial_index_row() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "trial_id": "trial-0001",
        "task_id": "pwb-0001",
        "benchmark": "PaperWrite-Bench",
        "benchmark_protocol": "short",
        "benchmark_hf_repo": "Jack-Jieke-Wu/Paper-Writing-Exam",
        "benchmark_hf_revision": "a" * 40,
        "harbor_repo_commit": "harbor-commit",
        "task_checksum": "task-sha256",
        "agent_name": "codex",
        "agent_version": "0.151.0",
        "integration_commit": "integration-commit",
        "model": "openai/gpt-5.6-terra",
        "provider": "openai",
        "agent_config_hash": "0" * 64,
        "status": "completed",
        "official_metrics": {},
        "artifact_archive": "artifacts/trial-0001.tar.gz",
        "artifact_sha256": "b" * 64,
        "sanitization_version": "1.2",
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_upload_rejects_trial_index_without_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "trials.jsonl").write_text(
        json.dumps(_valid_trial_index_row()) + "\n", encoding="utf-8"
    )
    api = SimpleNamespace(
        create_repo=lambda *args, **kwargs: None,
        list_repo_files=lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(huggingface, "_remote_file", lambda *_args, **_kwargs: None)

    with pytest.raises(TrialUploadError, match="trial index has no manifest"):
        upload_export(tmp_path, "my-org/my-trials", ["data/trials.jsonl"], api=api)


def test_upload_validates_unselected_remote_trial_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "manifests").mkdir()
    archive = tmp_path / "artifacts" / "trial.tar.gz"
    _write_archive(archive)
    (tmp_path / "manifests" / "trial.json").write_text(
        json.dumps(_manifest("artifacts/trial.tar.gz", _sha256(archive))), encoding="utf-8"
    )
    remote_index = tmp_path / "remote-trials.jsonl"
    remote_index.write_text(json.dumps(_valid_trial_index_row()) + "\n", encoding="utf-8")
    api = SimpleNamespace(
        create_repo=lambda *args, **kwargs: None,
        list_repo_files=lambda *args, **kwargs: ["data/trials.jsonl"],
    )
    monkeypatch.setattr(huggingface, "_remote_file", lambda *_args, **_kwargs: remote_index)

    with pytest.raises(TrialUploadError, match="trial index has no manifest"):
        upload_export(
            tmp_path,
            "my-org/my-trials",
            ["artifacts/trial.tar.gz", "manifests/trial.json"],
            api=api,
        )


@pytest.mark.parametrize("filename, events", [("data/trials.jsonl", False), ("data/events.jsonl", True)])
def test_upload_rejects_encoded_credentials_in_aggregate_indexes(
    tmp_path: Path, filename: str, events: bool
) -> None:
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "manifests").mkdir()
    (tmp_path / "data").mkdir()
    archive = tmp_path / "artifacts" / "trial-0001.tar.gz"
    _write_archive(archive)
    (tmp_path / "manifests" / "trial-0001.json").write_text(
        json.dumps(
            _manifest(
                "artifacts/trial-0001.tar.gz",
                hashlib.sha256(archive.read_bytes()).hexdigest(),
                trial_id="trial-0001",
            )
        ),
        encoding="utf-8",
    )
    encoded = base64.b64encode(
        json.dumps({"X-Auth-Token": "actual-secret"}).encode("utf-8")
    ).decode("ascii")
    row = (
        {
            "schema_version": "1.0",
            "trial_id": "trial-0001",
            "trajectory_path": "agent/trajectory.json",
            "sequence": 0,
            "step_id": 1,
            "source": "agent",
            "event": {"note": encoded},
        }
        if events
        else {**_valid_trial_index_row(), "official_metrics": {"note": encoded}}
    )
    Path(tmp_path / filename).write_text(json.dumps(row) + "\n", encoding="utf-8")
    api = SimpleNamespace(create_repo=lambda *args, **kwargs: None)

    with pytest.raises(TrialUploadError, match="sensitive credential"):
        upload_export(tmp_path, "my-org/my-trials", ["artifacts/trial-0001.tar.gz", "manifests/trial-0001.json", filename], api=api)


@pytest.mark.parametrize(
    "events, mutate, message",
    [
        (False, lambda row: row.update(trial_id=""), "provenance"),
        (False, lambda row: row.update(harbor_reward=True), "reward"),
        (False, lambda row: row.update(duration_seconds=float("nan")), "invalid trial index"),
        (True, lambda row: row.update(trial_id=""), "identity"),
    ],
)
def test_aggregate_indexes_reject_invalid_schema_values(
    tmp_path: Path, events: bool, mutate, message: str
) -> None:
    row = (
        {
            "schema_version": "1.0",
            "trial_id": "trial-0001",
            "trajectory_path": "agent/trajectory.json",
            "sequence": 0,
            "step_id": 1,
            "source": "agent",
            "event": {},
        }
        if events
        else _valid_trial_index_row()
    )
    mutate(row)
    source = tmp_path / "index.jsonl"
    source.write_text(json.dumps(row, allow_nan=True) + "\n", encoding="utf-8")
    with pytest.raises(TrialUploadError, match=message):
        _merge_jsonl(source, None, events=events)


def test_aggregate_indexes_reject_nested_non_finite_values(tmp_path: Path) -> None:
    row = _valid_trial_index_row()
    row["official_metrics"] = {"nested": [float("inf")]}
    source = tmp_path / "trials.jsonl"
    source.write_text(json.dumps(row, allow_nan=True) + "\n", encoding="utf-8")
    with pytest.raises(TrialUploadError, match="invalid trial index"):
        _merge_jsonl(source, None, events=False)


def test_upload_rejects_remote_manifest_identity_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "manifests").mkdir()
    archive = tmp_path / "artifacts" / "trial.tar.gz"
    _write_archive(archive)
    artifact_hash = _sha256(archive)
    local_manifest = _manifest("artifacts/trial.tar.gz", artifact_hash, trial_id="trial")
    (tmp_path / "manifests" / "trial.json").write_text(
        json.dumps(local_manifest), encoding="utf-8"
    )
    remote_manifest = tmp_path / "remote-manifest.json"
    remote_manifest.write_text(
        json.dumps({**local_manifest, "source_result_sha256": "1" * 64}),
        encoding="utf-8",
    )
    api = SimpleNamespace(
        create_repo=lambda *args, **kwargs: None,
        list_repo_files=lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        huggingface,
        "_remote_file",
        lambda _repo_id, filename, _revision, **_kwargs: remote_manifest
        if filename.startswith("manifests/")
        else None,
    )
    with pytest.raises(TrialUploadError, match="remote trial conflicts"):
        upload_export(
            tmp_path,
            "my-org/my-trials",
            ["artifacts/trial.tar.gz", "manifests/trial.json"],
            api=api,
        )
