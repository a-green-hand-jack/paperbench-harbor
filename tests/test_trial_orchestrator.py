from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperbench_harbor.trials import orchestrator
from paperbench_harbor.trials.orchestrator import (
    SanitizedTrialExportPlugin,
    TrialPublicationConfig,
    TrialPublicationError,
    publish_job,
)
from tests.test_export_trial import _trial, _write_private_manifest


def _config(tmp_path: Path, **updates: object) -> TrialPublicationConfig:
    values: dict[str, object] = {
        "output_dir": tmp_path / "exports",
        "benchmark_hf_revision": "a" * 40,
        "harbor_repo_commit": "harbor-commit",
        "integration_commit": "integration-commit",
        "agent_config_hash": "0" * 64,
        "private_manifest": tmp_path / "source_manifest.json",
    }
    values.update(updates)
    return TrialPublicationConfig(**values)


def _result(tmp_path: Path, trial_id: str = "trial-0001", *, failed: bool = False):
    trial_dir = tmp_path / trial_id
    trial_dir.mkdir()
    exception = {"exception_type": "RuntimeError"} if failed else None
    return SimpleNamespace(
        id=trial_id,
        task_name="pwb-0001",
        task_id="pwb-0001",
        task_checksum="task-sha256",
        trial_name=trial_id,
        trial_uri=trial_dir.as_uri(),
        source="PaperWrite-Bench",
        agent_info=SimpleNamespace(
            name="codex",
            version="0.146.0",
            model_info=SimpleNamespace(name="openai/gpt-5.6-sol", provider="openai"),
        ),
        exception_info=exception,
    )


def test_default_policy_skips_failed_trial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def fail_if_called(_args):
        nonlocal called
        called = True
        raise AssertionError("failed trial should be skipped")

    monkeypatch.setattr(orchestrator, "export_trial", fail_if_called)
    report = publish_job(
        SimpleNamespace(job_dir=tmp_path / "job"),
        SimpleNamespace(trial_results=[_result(tmp_path, failed=True)]),
        _config(tmp_path),
    )
    assert not called
    assert report["trials"][0]["status"] == "skipped_failed"


def test_include_cancelled_exports_cancelled_trial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = {
        "trial_id": "trial-0001",
        "artifact_archive": "artifacts/trial-0001.tar.gz",
        "artifact_sha256": "b" * 64,
    }
    monkeypatch.setattr(orchestrator, "export_trial", lambda _args: record)
    result = _result(tmp_path)
    result.exception_info = {"exception_type": "CancelledError"}

    report = publish_job(
        SimpleNamespace(job_dir=tmp_path / "job"),
        SimpleNamespace(trial_results=[result]),
        _config(tmp_path, include_cancelled=True),
    )

    assert report["trials"][0]["status"] == "exported"


def test_final_results_are_exported_and_upload_failure_preserves_local_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = {
        "trial_id": "trial-0001",
        "artifact_archive": "artifacts/trial-0001.tar.gz",
        "artifact_sha256": "b" * 64,
    }
    monkeypatch.setattr(orchestrator, "export_trial", lambda _args: records)

    def fail_upload(*_args, **_kwargs):
        raise RuntimeError("network unavailable")

    job_dir = tmp_path / "job"
    job_dir.mkdir()
    with pytest.raises(TrialPublicationError):
        publish_job(
            SimpleNamespace(job_dir=job_dir),
            SimpleNamespace(trial_results=[_result(tmp_path)]),
            _config(tmp_path, upload=True),
            uploader=fail_upload,
        )
    report = json.loads((job_dir / "trial-export-report.json").read_text())
    assert report["trials"][0]["status"] == "upload_failed"
    assert report["dataset_revision"] is None


def test_local_only_publish_uses_the_real_sanitized_exporter(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    result = _result(tmp_path)
    result.trial_uri = trial.as_uri()
    (tmp_path / "private-source.txt").write_text("verifier private\n")
    private_manifest = tmp_path / "private-manifest.json"
    args = SimpleNamespace(private_manifest=private_manifest)
    _write_private_manifest(args)
    config = _config(tmp_path, private_manifest=private_manifest)

    report = publish_job(SimpleNamespace(job_dir=tmp_path / "job"), SimpleNamespace(trial_results=[result]), config)

    assert report["trials"][0]["status"] == "exported"
    assert (config.output_dir / "artifacts" / "trial-0001.tar.gz").is_file()
    reused = publish_job(
        SimpleNamespace(job_dir=tmp_path / "job"), SimpleNamespace(trial_results=[result]), config
    )
    assert reused["trials"][0]["status"] == "reused_existing_export"


def test_custom_dataset_and_plugin_validation() -> None:
    plugin = SanitizedTrialExportPlugin(
        output_dir="/tmp/trials",
        benchmark_hf_revision="a" * 40,
        harbor_repo_commit="harbor",
        integration_commit="integration",
        agent_config_hash="0" * 64,
        private_manifest="/tmp/source_manifest.json",
        upload="true",
        dataset_repo="my-org/my-trials",
    )
    assert plugin.config.dataset_repo == "my-org/my-trials"
    with pytest.raises(ValueError, match="namespace/name"):
        SanitizedTrialExportPlugin(
            output_dir="/tmp/trials",
            benchmark_hf_revision="a" * 40,
            harbor_repo_commit="harbor",
            integration_commit="integration",
            agent_config_hash="0" * 64,
            private_manifest="/tmp/source_manifest.json",
            upload="true",
            dataset_repo="not-a-repo",
        ).config.validate()


def test_plugin_runs_post_job_on_host_side(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[object] = []

    def fake_publish(job, result, config):
        seen.extend([job, result, config])
        return {"trials": []}

    monkeypatch.setattr(orchestrator, "publish_job", fake_publish)
    plugin = SanitizedTrialExportPlugin(
        output_dir=str(tmp_path / "exports"),
        benchmark_hf_revision="a" * 40,
        harbor_repo_commit="harbor",
        integration_commit="integration",
        agent_config_hash="0" * 64,
        private_manifest=str(tmp_path / "source_manifest.json"),
    )
    job = SimpleNamespace(job_dir=tmp_path / "job")

    async def run() -> None:
        await plugin.on_job_start(job)
        await plugin.on_job_end(SimpleNamespace(trial_results=[]))

    asyncio.run(run())
    assert seen[0] is job
