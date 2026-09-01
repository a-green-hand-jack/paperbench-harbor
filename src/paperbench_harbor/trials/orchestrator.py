"""Host-side orchestration for optional sanitized Harbor trial publication."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from paperbench_harbor.trials.export import (
    TrialExportConfig,
    TrialExportError,
    export_trial,
    validate_existing_export,
)
from paperbench_harbor.trials.huggingface import upload_export, validate_dataset_repo

logger = logging.getLogger(__name__)


class TrialPublicationError(RuntimeError):
    """Raised after publishing has completed with one or more per-trial errors."""


@dataclass(frozen=True)
class TrialPublicationConfig:
    output_dir: Path
    benchmark_hf_revision: str
    harbor_repo_commit: str
    integration_commit: str
    benchmark: str = "PaperWrite-Bench"
    protocol: str = "short"
    benchmark_hf_repo: str = "Jack-Jieke-Wu/Paper-Writing-Exam"
    agent_config_hash: str | None = None
    agent_config_file: Path | None = None
    private_manifest: Path | None = None
    private_manifest_map: Path | None = None
    upload: bool = False
    dataset_repo: str = "Jack-Jieke-Wu/Paper-Writing-Exam-Trials"
    revision: str = "main"
    parent_commit: str | None = None
    include_failed: bool = False
    include_cancelled: bool = False
    model: str | None = None
    provider: str | None = None

    def validate(self) -> None:
        if not self.output_dir:
            raise ValueError("output_dir is required")
        if not self.benchmark_hf_revision:
            raise ValueError("benchmark_hf_revision is required")
        if not self.harbor_repo_commit:
            raise ValueError("harbor_repo_commit is required")
        if not self.integration_commit:
            raise ValueError("integration_commit is required")
        if self.agent_config_hash is None and self.agent_config_file is None:
            raise ValueError("agent_config_hash or agent_config_file is required")
        if self.agent_config_hash is not None and self.agent_config_file is not None:
            raise ValueError("agent_config_hash and agent_config_file are mutually exclusive")
        if self.upload:
            validate_dataset_repo(self.dataset_repo)


@dataclass
class TrialPublication:
    trial_id: str
    status: str
    error: str | None = None
    artifact_sha256: str | None = None


def _value(value: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _exception_types(trial_result: Any) -> list[str]:
    types: list[str] = []
    exception = _value(trial_result, "exception_info")
    if exception is not None:
        exception_type = _value(exception, "exception_type")
        if isinstance(exception_type, str):
            types.append(exception_type)
    step_results = _value(trial_result, "step_results", default=[])
    for step in step_results or []:
        nested = _value(step, "exception_info")
        if nested is not None:
            exception_type = _value(nested, "exception_type")
            if isinstance(exception_type, str):
                types.append(exception_type)
    return types


def _trial_dir(trial_result: Any) -> Path:
    uri = _value(trial_result, "trial_uri")
    if isinstance(uri, str) and uri:
        parsed = urlparse(uri)
        if parsed.scheme in ("", "file"):
            path = Path(unquote(parsed.path if parsed.scheme else uri))
            if path.is_dir():
                return path
    config = _value(trial_result, "config")
    trials_dir = _value(config, "trials_dir")
    trial_name = _value(trial_result, "trial_name")
    if trials_dir is not None and trial_name:
        path = Path(trials_dir) / str(trial_name)
        if path.is_dir():
            return path
    raise TrialExportError("Harbor final result does not identify an existing trial directory")


def _task_manifest(trial_result: Any, config: TrialPublicationConfig) -> Path:
    keys = [
        str(_value(trial_result, "task_name", "task_id", default="")),
        str(_value(trial_result, "task_id", default="")),
        str(_value(trial_result, "source", default="")),
    ]
    if config.private_manifest_map is not None:
        mapping = json.loads(config.private_manifest_map.read_text(encoding="utf-8"))
        if not isinstance(mapping, dict):
            raise TrialExportError("private_manifest_map must contain a JSON object")
        for key in keys:
            selected = mapping.get(key)
            if isinstance(selected, str):
                return Path(selected)
        raise TrialExportError(f"no private manifest mapping for task {keys[0]!r}")
    if config.private_manifest is not None:
        return config.private_manifest
    task_path = _task_path(trial_result)
    if task_path is not None:
        candidate = task_path / "tests" / "private" / "source_manifest.json"
        if candidate.is_file():
            return candidate
    raise TrialExportError("could not resolve task tests/private/source_manifest.json")


def _task_path(trial_result: Any) -> Path | None:
    trial_config = _value(trial_result, "config")
    task_config = _value(trial_config, "task")
    if task_config is None:
        return None
    getter = getattr(task_config, "get_local_path", None)
    if callable(getter):
        try:
            return Path(getter())
        except (OSError, ValueError):
            pass
    path = _value(task_config, "path")
    if path:
        return Path(path)
    return None


def _agent_fields(
    trial_result: Any, config: TrialPublicationConfig
) -> tuple[str, str, str | None, str | None]:
    info = _value(trial_result, "agent_info", default={})
    model_info = _value(info, "model_info", default={})
    return (
        str(_value(info, "name", default="")),
        str(_value(info, "version", default="")),
        _value(model_info, "name") or config.model,
        _value(model_info, "provider") or config.provider,
    )


def _export_args(trial_result: Any, config: TrialPublicationConfig) -> TrialExportConfig:
    agent_name, agent_version, model, provider = _agent_fields(trial_result, config)
    return TrialExportConfig(
        trial_dir=_trial_dir(trial_result),
        output_dir=config.output_dir,
        private_manifest=_task_manifest(trial_result, config),
        task_id=str(_value(trial_result, "task_name", "task_id", default="")),
        task_checksum=str(_value(trial_result, "task_checksum", default="") or ""),
        benchmark=config.benchmark,
        protocol=config.protocol,
        benchmark_hf_repo=config.benchmark_hf_repo,
        benchmark_hf_revision=config.benchmark_hf_revision,
        harbor_repo_commit=config.harbor_repo_commit,
        agent_name=agent_name,
        agent_version=agent_version,
        integration_commit=config.integration_commit,
        model=model,
        provider=provider,
        agent_config_hash=config.agent_config_hash,
        agent_config_file=config.agent_config_file,
        trial_id=str(_value(trial_result, "id", "trial_name", default="")),
        run_id=str(_value(trial_result, "trial_name", default="")),
    )


def _existing_export(
    output_dir: Path,
    trial_id: str,
    *,
    private_manifest: Path | None,
    expected_result_sha256: str | None,
) -> dict[str, Any] | None:
    manifest = output_dir / "manifests" / f"{trial_id}.json"
    archive = output_dir / "artifacts" / f"{trial_id}.tar.gz"
    records = output_dir / "data" / "trials.jsonl"
    if not (manifest.is_file() and archive.is_file() and records.is_file()):
        return None
    if not (manifest.is_file() or archive.is_file() or records.is_file()):
        return None
    return validate_existing_export(
        output_dir,
        trial_id,
        private_manifest=private_manifest,
        expected_result_sha256=expected_result_sha256,
    )


def publish_job(job: Any, job_result: Any, config: TrialPublicationConfig, *, uploader=upload_export) -> dict[str, Any]:
    """Export final Harbor results and optionally publish their local files."""
    config.validate()
    publications: list[TrialPublication] = []
    upload_records: list[dict[str, Any]] = []
    for trial_result in _value(job_result, "trial_results", default=[]):
        trial_id = str(_value(trial_result, "id", "trial_name", default=""))
        exception_types = _exception_types(trial_result)
        if "CancelledError" in exception_types and not config.include_cancelled:
            publications.append(TrialPublication(trial_id, "skipped_cancelled"))
            continue
        non_cancellation_errors = [
            exception_type for exception_type in exception_types if exception_type != "CancelledError"
        ]
        if non_cancellation_errors and not config.include_failed:
            publications.append(TrialPublication(trial_id, "skipped_failed"))
            continue
        try:
            export_args = _export_args(trial_result, config)
            source_result = export_args.trial_dir / "result.json"
            expected_result_sha256 = (
                hashlib.sha256(source_result.read_bytes()).hexdigest()
                if source_result.is_file()
                else None
            )
            record = _existing_export(
                config.output_dir,
                trial_id,
                private_manifest=export_args.private_manifest,
                expected_result_sha256=expected_result_sha256,
            )
            if record is None:
                record = export_trial(export_args)
                status = "exported"
            else:
                status = "reused_existing_export"
            publications.append(
                TrialPublication(trial_id, status, artifact_sha256=record.get("artifact_sha256"))
            )
            upload_records.append(record)
        except Exception as exc:  # noqa: BLE001 - isolate one trial's failure
            logger.error("trial export failed for %s: %s", trial_id, exc)
            publications.append(TrialPublication(trial_id, "export_failed", str(exc)))

    upload_sha = None
    upload_error = None
    if config.upload and upload_records:
        relative_paths = [
            record["artifact_archive"] for record in upload_records
        ] + [
            f"manifests/{record['trial_id']}.json" for record in upload_records
        ]
        if (config.output_dir / "data" / "trials.jsonl").is_file():
            relative_paths.append("data/trials.jsonl")
        if (config.output_dir / "data" / "events.jsonl").is_file():
            relative_paths.append("data/events.jsonl")
        try:
            upload_sha = uploader(
                config.output_dir,
                config.dataset_repo,
                relative_paths,
                revision=config.revision,
                parent_commit=config.parent_commit,
                commit_message="Add sanitized Harbor trial export",
            )
            for publication in publications:
                if publication.status in {"exported", "reused_existing_export"}:
                    publication.status = "uploaded"
        except Exception as exc:  # noqa: BLE001 - upload must not alter reward
            upload_error = str(exc)
            for publication in publications:
                if publication.status in {"exported", "reused_existing_export"}:
                    publication.status = "upload_failed"
                    publication.error = upload_error
            logger.error("trial upload failed for %s: %s", config.dataset_repo, exc)

    report = {
        "schema_version": "1.0",
        "output_dir": str(config.output_dir),
        "upload": config.upload,
        "dataset_repo": config.dataset_repo if config.upload else None,
        "dataset_revision": upload_sha,
        "trials": [asdict(item) for item in publications],
    }
    job_dir = _value(job, "job_dir")
    if job_dir is not None:
        report_path = Path(job_dir) / "trial-export-report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if any(item.status in {"export_failed", "upload_failed"} for item in publications):
        raise TrialPublicationError("one or more trial publication operations failed")
    return report


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean plugin kwarg: {value!r}")


class SanitizedTrialExportPlugin:
    """Harbor JobPlugin that exports only final, host-side trial results."""

    def __init__(self, **kwargs: Any) -> None:
        if not kwargs.get("output_dir"):
            raise ValueError("output_dir is required")
        self.config = TrialPublicationConfig(
            output_dir=Path(kwargs.get("output_dir", "")),
            benchmark_hf_revision=str(kwargs.get("benchmark_hf_revision", "")),
            harbor_repo_commit=str(kwargs.get("harbor_repo_commit", os.environ.get("PAPERBENCH_HARBOR_REPO_COMMIT", ""))),
            integration_commit=str(kwargs.get("integration_commit", os.environ.get("PAPERBENCH_INTEGRATION_COMMIT", ""))),
            benchmark=str(kwargs.get("benchmark", "PaperWrite-Bench")),
            protocol=str(kwargs.get("protocol", "short")),
            benchmark_hf_repo=str(kwargs.get("benchmark_hf_repo", "Jack-Jieke-Wu/Paper-Writing-Exam")),
            agent_config_hash=kwargs.get("agent_config_hash"),
            agent_config_file=Path(kwargs["agent_config_file"]) if kwargs.get("agent_config_file") else None,
            private_manifest=Path(kwargs["private_manifest"]) if kwargs.get("private_manifest") else None,
            private_manifest_map=Path(kwargs["private_manifest_map"]) if kwargs.get("private_manifest_map") else None,
            upload=_bool(kwargs.get("upload")),
            dataset_repo=str(kwargs.get("dataset_repo", kwargs.get("trial_dataset", "Jack-Jieke-Wu/Paper-Writing-Exam-Trials"))),
            revision=str(kwargs.get("revision", "main")),
            parent_commit=kwargs.get("parent_commit"),
            include_failed=_bool(kwargs.get("include_failed")),
            include_cancelled=_bool(kwargs.get("include_cancelled")),
            model=kwargs.get("model"),
            provider=kwargs.get("provider"),
        )
        self._job = None

    async def on_job_start(self, job: Any) -> None:
        self.config.validate()
        self._job = job
        logger.info(
            "sanitized trial export enabled: output_dir=%s upload=%s dataset=%s",
            self.config.output_dir,
            self.config.upload,
            self.config.dataset_repo if self.config.upload else "disabled",
        )

    async def on_job_end(self, job_result: Any) -> None:
        import asyncio

        await asyncio.to_thread(publish_job, self._job, job_result, self.config)
