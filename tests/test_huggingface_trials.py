from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from paperbench_harbor.trials.huggingface import (
    TrialUploadError,
    upload_export,
    validate_dataset_repo,
)


def test_validate_dataset_repo() -> None:
    assert validate_dataset_repo("my-org/my-trials") == "my-org/my-trials"
    with pytest.raises(ValueError):
        validate_dataset_repo("my-org")
    with pytest.raises(ValueError):
        validate_dataset_repo("https://huggingface.co/datasets/my-org/my-trials")


def test_upload_uses_exact_files_and_returns_commit_sha(tmp_path: Path) -> None:
    from huggingface_hub import CommitOperationAdd

    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "trial.tar.gz").write_bytes(b"archive")
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
        ["artifacts/trial.tar.gz"],
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
