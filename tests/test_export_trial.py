from __future__ import annotations

import base64
import bz2
import gzip
import hashlib
import io
import json
import lzma
import stat
import tarfile
import zipfile
from argparse import Namespace
from pathlib import Path

import pytest

from paperbench_harbor.trials.export import _check_json_values
from scripts.export_trial import TrialExportError, export_trial


def _args(trial_dir: Path, output_dir: Path) -> Namespace:
    private_source = trial_dir.parent / "private-source.txt"
    private_source.write_text("verifier private\n", encoding="utf-8")
    return Namespace(
        trial_dir=trial_dir,
        output_dir=output_dir,
        private_manifest=trial_dir.parent / "private-manifest.json",
        trial_id="trial-0001",
        run_id="run-0001",
        task_id="pwb-0001",
        task_checksum="task-sha256",
        benchmark="PaperWrite-Bench",
        protocol="short",
        benchmark_hf_repo="Jack-Jieke-Wu/Paper-Writing-Exam",
        benchmark_hf_revision="a" * 40,
        harbor_repo_commit="harbor-commit",
        agent_name="codex",
        agent_version="0.146.0",
        integration_commit="integration-commit",
        model="openai/gpt-5.6-sol",
        provider="openai",
        agent_config_file=None,
        agent_config_hash="0" * 64,
    )


def _write_private_manifest(args: Namespace) -> None:
    private_source = args.private_manifest.parent / "private-source.txt"
    args.private_manifest.write_text(
        json.dumps(
            {
                "private_file_hashes": {
                    "tests/private/ground_truth.txt": hashlib.sha256(
                        private_source.read_bytes()
                    ).hexdigest()
                },
                "public_file_hashes": {},
            }
        ),
        encoding="utf-8",
    )


def _trial(tmp_path: Path) -> Path:
    trial = tmp_path / "trial"
    artifacts = trial / "artifacts"
    (artifacts / "workspace" / "submission").mkdir(parents=True)
    (trial / "agent" / "paper-run").mkdir(parents=True)
    (trial / "verifier").mkdir(parents=True)
    result = {
        "id": "trial-0001",
        "task_name": "pwb-0001",
        "trial_name": "run-0001",
        "task_checksum": "task-sha256",
        "agent_info": {
            "name": "codex",
            "version": "0.146.0",
            "model_info": {"name": "openai/gpt-5.6-sol", "provider": "openai"},
        },
        "started_at": "2026-09-01T00:00:00+00:00",
        "finished_at": "2026-09-01T00:01:30+00:00",
        "verifier_result": {"reward": 1.0},
    }
    trial.mkdir(exist_ok=True)
    (trial / "result.json").write_text(json.dumps(result), encoding="utf-8")
    (artifacts / "workspace" / "submission" / "main.tex").write_text(
        "\\documentclass{article}\n", encoding="utf-8"
    )
    (artifacts / "workspace" / "submission" / "references.bib").write_text(
        "@article{example}\n", encoding="utf-8"
    )
    (trial / "agent" / "paper-run" / "run.log").write_text(
        "stage completed\n", encoding="utf-8"
    )
    (trial / "agent" / "trajectory.json").write_text(
        json.dumps(
            {
                "schema_version": "ATIF-v1.7",
                "agent": {"name": "codex", "version": "0.146.0"},
                "steps": [
                    {"step_id": 1, "source": "user", "message": "Write the paper."},
                    {"step_id": 2, "source": "agent", "message": "Completed."},
                ],
            }
        ),
        encoding="utf-8",
    )
    (trial / "verifier" / "evaluation.json").write_text(
        '{"citation_f1": 0.5}\n', encoding="utf-8"
    )
    return trial


def test_export_trial_writes_record_manifest_and_archive(tmp_path: Path) -> None:
    output = tmp_path / "export"
    args = _args(_trial(tmp_path), output)
    _write_private_manifest(args)
    record = export_trial(args)

    assert record["trial_id"] == "trial-0001"
    assert record["duration_seconds"] == 90.0
    assert record["harbor_reward"] == 1.0
    assert record["official_metrics"] == {"citation_f1": 0.5}
    assert record["event_count"] == 2
    assert (output / "data" / "trials.jsonl").is_file()
    assert (output / "manifests" / "trial-0001.json").is_file()

    with tarfile.open(output / "artifacts" / "trial-0001.tar.gz", "r:gz") as archive:
        names = sorted(member.name for member in archive.getmembers())
    assert names == [
        "agent/paper-run/run.log",
        "agent/trajectory.json",
        "artifacts/workspace/submission/main.tex",
        "artifacts/workspace/submission/references.bib",
        "harbor/result.json",
        "verifier/evaluation.json",
    ]
    events = [
        json.loads(line)
        for line in (output / "data" / "events.jsonl").read_text().splitlines()
    ]
    assert [event["source"] for event in events] == ["user", "agent"]
    assert all(event["trajectory_path"] == "agent/trajectory.json" for event in events)


def test_export_redacts_codex_session_ciphertext_and_credential_fields(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    session = trial / "agent" / "sessions" / "2026" / "09" / "01"
    session.mkdir(parents=True)
    original = {
        "type": "response_item",
        "payload": {
            "type": "reasoning",
            "encrypted_content": "hf_fixed-looking-ciphertext-value",
            "api_key": "sk-fixed-looking-key",
            "Authorization": "Bearer fixed-looking-token",
            "Cookie": "session=fixed-looking-cookie",
            "Set_Cookie": "session=fixed-looking-cookie",
            "Proxy_Authorization": "Bearer fixed-looking-token",
        },
    }
    source = session / "rollout.jsonl"
    source.write_text(json.dumps(original) + "\n", encoding="utf-8")
    nested_session = trial / "steps" / "draft" / "agent" / "sessions"
    nested_session.mkdir(parents=True)
    (nested_session / "rollout.jsonl").write_text(json.dumps(original) + "\n", encoding="utf-8")
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)

    export_trial(args)

    with tarfile.open(args.output_dir / "artifacts" / "trial-0001.tar.gz", "r:gz") as archive:
        payload = json.loads(archive.extractfile("agent/sessions/2026/09/01/rollout.jsonl").read())
        nested_payload = json.loads(
            archive.extractfile("steps/draft/agent/sessions/rollout.jsonl").read()
        )
    assert payload["payload"]["encrypted_content"] == "REDACTED"
    assert payload["payload"]["api_key"] == "REDACTED"
    assert payload["payload"]["Authorization"] == "REDACTED"
    assert payload["payload"]["Cookie"] == "REDACTED"
    assert payload["payload"]["Set_Cookie"] == "REDACTED"
    assert payload["payload"]["Proxy_Authorization"] == "REDACTED"
    assert nested_payload["payload"]["encrypted_content"] == "REDACTED"


def test_export_rejects_nonstandard_json_in_codex_session_log(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    session = trial / "agent" / "sessions" / "2026" / "09" / "01"
    session.mkdir(parents=True)
    (session / "rollout.jsonl").write_bytes(b'{"type":"response_item","value":NaN}\n')
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)

    with pytest.raises(TrialExportError, match="invalid Codex session record"):
        export_trial(args)


@pytest.mark.parametrize(
    "key",
    [
        "Authorization",
        "Cookie",
        "Set-Cookie",
        "Set_Cookie",
        "Proxy-Authorization",
        "Proxy_Authorization",
        "X-Auth-Token",
        "X_Auth_Token",
        "ID-Token",
        "ID_Token",
        "OAuth-Token",
        "OAuth_Token",
        "API-KEY",
        "AWS_SESSION_TOKEN",
        "AZURE_OPENAI_API_KEY",
    ],
)
def test_structured_header_credentials_are_rejected(key: str) -> None:
    with pytest.raises(TrialExportError, match="sensitive credential"):
        _check_json_values(json.dumps({key: "actual-secret"}), Path("session.jsonl"))


def test_structured_credential_containers_are_rejected() -> None:
    with pytest.raises(TrialExportError, match="sensitive credential"):
        _check_json_values(
            '{"Authorization":{"value":"actual-secret"}}', Path("session.jsonl")
        )


def test_export_trial_archive_is_deterministic(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    first_args = _args(trial, tmp_path / "export-one")
    _write_private_manifest(first_args)
    second_args = _args(trial, tmp_path / "export-two")
    _write_private_manifest(second_args)

    first = export_trial(first_args)
    second = export_trial(second_args)

    first_archive = first_args.output_dir / "artifacts" / "trial-0001.tar.gz"
    second_archive = second_args.output_dir / "artifacts" / "trial-0001.tar.gz"
    assert first["artifact_sha256"] == second["artifact_sha256"]
    assert first_archive.read_bytes() == second_archive.read_bytes()


def test_export_trial_preserves_multistep_harbor_directories(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    step_agent = trial / "steps" / "draft" / "agent"
    step_agent.mkdir(parents=True)
    (step_agent / "trajectory.json").write_text(
        json.dumps(
            {
                "schema_version": "ATIF-v1.7",
                "agent": {"name": "codex", "version": "0.146.0"},
                "steps": [{"step_id": 1, "source": "agent", "message": "Done."}],
            }
        ),
        encoding="utf-8",
    )

    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    record = export_trial(args)

    assert record["event_count"] == 3
    with tarfile.open(tmp_path / "export" / "artifacts" / "trial-0001.tar.gz", "r:gz") as archive:
        names = sorted(member.name for member in archive.getmembers())
    assert "steps/draft/agent/trajectory.json" in names


def test_export_trial_rejects_a_trial_without_outputs(tmp_path: Path) -> None:
    trial = tmp_path / "trial"
    trial.mkdir()
    (trial / "result.json").write_text("{}", encoding="utf-8")

    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    with pytest.raises(TrialExportError, match="no allowlisted"):
        export_trial(args)


@pytest.mark.parametrize("relative_path", ["artifacts/solution/private/gt.tex", "artifacts/.env"])
def test_export_trial_refuses_private_or_credential_files(tmp_path: Path, relative_path: str) -> None:
    trial = _trial(tmp_path)
    forbidden = trial / relative_path
    forbidden.parent.mkdir(parents=True, exist_ok=True)
    forbidden.write_text("private\n", encoding="utf-8")

    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    with pytest.raises(TrialExportError):
        export_trial(args)


def test_export_trial_refuses_recognizable_secret(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    secret_log = trial / "agent" / "paper-run" / "secret.log"
    secret_log.write_text("token=sk-abcdefghijklmnopqrstuvwxyz\n", encoding="utf-8")

    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    with pytest.raises(TrialExportError):
        export_trial(args)


def test_export_trial_allows_token_identifiers_in_code(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    (trial / "agent" / "paper-run" / "code.log").write_text(
        "in_token = list(new_output.prompt_token_ids)\n"
        "eos_token = tokenizer.eos_token\n",
        encoding="utf-8",
    )

    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)

    record = export_trial(args)

    assert record["trial_id"] == "trial-0001"


def test_export_trial_allows_escaped_empty_secret_fields_in_code(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    (trial / "agent" / "paper-run" / "code.log").write_text(
        'export WANDB_API_KEY=\\"\\"\\n'
        'export WANDB_API_KEY=\\"null\\"\\n'
        "if not wandb.api.api_key:\\\\n",
        encoding="utf-8",
    )

    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)

    record = export_trial(args)

    assert record["trial_id"] == "trial-0001"


def test_safe_secret_field_does_not_hide_later_secret(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    (trial / "agent" / "credential.log").write_text(
        "OPENAI_API_KEY=redacted\nOPENAI_API_KEY=actual-secret-value\n",
        encoding="utf-8",
    )
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)

    with pytest.raises(TrialExportError):
        export_trial(args)


def test_export_trial_rejects_shell_fallback_secret(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    (trial / "agent" / "credential.log").write_text(
        "OPENAI_API_KEY=${OPENAI_API_KEY:-actual-secret-value}\n",
        encoding="utf-8",
    )
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)

    with pytest.raises(TrialExportError):
        export_trial(args)


def test_export_trial_allows_bare_environment_reference(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    (trial / "agent" / "paper-run" / "config.log").write_text(
        "OPENAI_API_KEY=${OPENAI_API_KEY}\n",
        encoding="utf-8",
    )
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)

    record = export_trial(args)

    assert record["trial_id"] == "trial-0001"


@pytest.mark.parametrize(
    "value", ["$literal-secret", "${OPENAI_API_KEY}suffix", "${OPENAI_API_KEY:-fallback}"]
)
def test_export_trial_refuses_non_bare_environment_expansion(
    tmp_path: Path, value: str
) -> None:
    trial = _trial(tmp_path)
    (trial / "agent" / "credential.log").write_text(
        f"OPENAI_API_KEY={value}\n", encoding="utf-8"
    )
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)

    with pytest.raises(TrialExportError):
        export_trial(args)


def test_export_trial_allows_redacted_secret_fields(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    (trial / "config.json").write_text(
        json.dumps({"agent": {"env": {"OPENAI_API_KEY": "redacted"}}}),
        encoding="utf-8",
    )

    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    record = export_trial(args)

    assert record["trial_id"] == "trial-0001"


def test_export_trial_refuses_provenance_that_contradicts_result(tmp_path: Path) -> None:
    args = _args(_trial(tmp_path), tmp_path / "export")
    _write_private_manifest(args)
    args.agent_version = "wrong-version"

    with pytest.raises(TrialExportError, match="agent_version contradicts"):
        export_trial(args)


def test_export_trial_refuses_trial_id_that_contradicts_result(tmp_path: Path) -> None:
    args = _args(_trial(tmp_path), tmp_path / "export")
    _write_private_manifest(args)
    args.trial_id = "trial-0002"

    with pytest.raises(TrialExportError, match="trial_id contradicts"):
        export_trial(args)


@pytest.mark.parametrize(
    "payload",
    [
        "Authorization: Bearer redacted-but-still-an-auth-header\n",
        "-----BEGIN OPENSSH PRIVATE KEY-----\nprivate\n",
        "aws_access_key_id=AKIAIOSFODNN7EXAMPLE\n",
    ],
)
def test_export_trial_refuses_additional_credential_patterns(
    tmp_path: Path, payload: str
) -> None:
    trial = _trial(tmp_path)
    (trial / "agent" / "credential.log").write_text(payload, encoding="utf-8")

    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    with pytest.raises(TrialExportError):
        export_trial(args)


def test_export_trial_refuses_json_aws_secret(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    (trial / "agent" / "credential.log").write_text(
        '{"aws_secret_access_key": "not-a-real-but-secret-shaped-value"}\n',
        encoding="utf-8",
    )

    with pytest.raises(TrialExportError):
        export_trial(args)


def test_export_trial_allows_empty_aws_secret(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    (trial / "agent" / "paper-run" / "config.log").write_text(
        "aws_secret_access_key=\n",
        encoding="utf-8",
    )

    record = export_trial(args)

    assert record["trial_id"] == "trial-0001"


def test_export_trial_refuses_json_unicode_escaped_secret(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    key = "".join(f"\\u{ord(character):04x}" for character in "OPENAI_API_KEY")
    value = "".join(f"\\u{ord(character):04x}" for character in "sk-abcdefghijklmnopqrstuvwxyz")
    (trial / "agent" / "encoded.json").write_text(
        f'{{"{key}": "{value}"}}\n',
        encoding="ascii",
    )

    with pytest.raises(TrialExportError):
        export_trial(args)


def test_export_trial_refuses_bare_google_api_key(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    (trial / "agent" / "encoded.log").write_text(
        "AIza" + "a" * 35 + "\n",
        encoding="ascii",
    )

    with pytest.raises(TrialExportError):
        export_trial(args)


def test_export_trial_refuses_utf32_secret(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    (trial / "agent" / "encoded.log").write_bytes(
        "OPENAI_API_KEY=actual-secret-value\n".encode("utf-32")
    )

    with pytest.raises(TrialExportError):
        export_trial(args)


def test_export_trial_requires_private_manifest(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    args.private_manifest = None

    with pytest.raises(TrialExportError, match="private source manifest is required"):
        export_trial(args)


def test_export_trial_rejects_renamed_verifier_private_file(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    (trial / "artifacts" / "workspace" / "submission" / "notes.txt").write_text(
        "verifier private\n", encoding="utf-8"
    )

    with pytest.raises(TrialExportError, match="verifier-private source material"):
        export_trial(args)


def test_export_trial_allows_hash_shared_with_public_materials(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    public_copy = trial / "artifacts" / "workspace" / "submission" / "public.txt"
    public_copy.write_text("public duplicate\n", encoding="utf-8")
    payload = json.loads(args.private_manifest.read_text(encoding="utf-8"))
    public_hash = hashlib.sha256(public_copy.read_bytes()).hexdigest()
    payload["private_file_hashes"]["tests/private/public.txt"] = public_hash
    payload["public_file_hashes"]["materials/public.txt"] = public_hash
    args.private_manifest.write_text(json.dumps(payload), encoding="utf-8")

    record = export_trial(args)

    assert record["trial_id"] == "trial-0001"


@pytest.mark.parametrize(
    "payload",
    [
        b"OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz\n".decode("utf-8"),
        "OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz\n".encode("utf-16").decode("latin1"),
    ],
)
def test_export_trial_refuses_secret_in_text_encodings(
    tmp_path: Path, payload: str
) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    secret_path = trial / "agent" / "encoded.log"
    if "\x00" in payload:
        secret_path.write_bytes(payload.encode("latin1"))
    else:
        secret_path.write_text(payload, encoding="utf-8")

    with pytest.raises(TrialExportError):
        export_trial(args)


def test_export_trial_refuses_base64_secret(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    encoded = base64.b64encode(b"sk-abcdefghijklmnopqrstuvwxyz").decode("ascii")
    (trial / "agent" / "encoded.log").write_text(encoded, encoding="ascii")

    with pytest.raises(TrialExportError):
        export_trial(args)


def test_export_trial_refuses_secret_in_gzip(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    with gzip.open(trial / "agent" / "trace.gz", "wb") as handle:
        handle.write(b"OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz\n")

    with pytest.raises(TrialExportError):
        export_trial(args)


def test_export_trial_refuses_trailing_gzip_data(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    trace_path = trial / "agent" / "trace.gz"
    with gzip.open(trace_path, "wb") as handle:
        handle.write(b"redacted trace\n")
    trace_path.write_bytes(trace_path.read_bytes() + b"trailing data")

    with pytest.raises(TrialExportError, match="trailing gzip"):
        export_trial(args)


@pytest.mark.parametrize(
    ("suffix", "compress"),
    [(".bz2", bz2.compress), (".xz", lzma.compress)],
)
def test_export_trial_refuses_unsupported_standalone_compression(
    tmp_path: Path, suffix: str, compress
) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    (trial / "agent" / f"trace{suffix}").write_bytes(compress(b"redacted trace\n"))

    with pytest.raises(TrialExportError, match="unsupported standalone compressed"):
        export_trial(args)


def test_export_trial_refuses_secret_in_tar_metadata(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    with tarfile.open(
        trial / "agent" / "trace.tar.gz", "w:gz", format=tarfile.PAX_FORMAT
    ) as archive:
        member = tarfile.TarInfo("trace.txt")
        member.size = 4
        member.pax_headers = {"comment": "OPENAI_API_KEY=actual-secret-value"}
        archive.addfile(member, io.BytesIO(b"safe"))

    with pytest.raises(TrialExportError):
        export_trial(args)


def test_export_trial_allows_null_subagent_trajectories(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    trajectory_path = trial / "agent" / "trajectory.json"
    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    trajectory["subagent_trajectories"] = None
    trajectory_path.write_text(json.dumps(trajectory), encoding="utf-8")

    assert export_trial(args)["event_count"] == 2


def test_export_trial_refuses_generic_secret_in_zip(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    with zipfile.ZipFile(trial / "agent" / "trace.zip", "w") as archive:
        archive.writestr("trace.txt", "CUSTOM_API_KEY=not-a-recognizable-token-shape\n")

    with pytest.raises(TrialExportError):
        export_trial(args)


def test_export_trial_refuses_secret_in_zip_metadata(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    with zipfile.ZipFile(trial / "agent" / "trace.zip", "w") as archive:
        archive.comment = b"CUSTOM_API_KEY=not-a-recognizable-token-shape"
        member = zipfile.ZipInfo("safe.txt")
        member.comment = b"CUSTOM_API_KEY=not-a-recognizable-token-shape"
        archive.writestr(member, "safe")

    with pytest.raises(TrialExportError):
        export_trial(args)


def test_export_trial_refuses_secret_in_filename(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    (trial / "agent" / "OPENAI_API_KEY=actual-secret-value.log").write_text(
        "safe\n", encoding="utf-8"
    )

    with pytest.raises(TrialExportError):
        export_trial(args)


def test_export_trial_allows_escaped_redacted_secret_fields(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    (trial / "agent" / "paper-run" / "config.log").write_text(
        'WANDB_API_KEY=\\"\\"\nWANDB_API_KEY=\\"null\\"\n', encoding="utf-8"
    )
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)

    assert export_trial(args)["trial_id"] == "trial-0001"


def test_export_trial_refuses_zip_symlink_member(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    link = zipfile.ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(trial / "agent" / "trace.zip", "w") as archive:
        archive.writestr(link, "target")

    with pytest.raises(TrialExportError, match="non-regular archive member"):
        export_trial(args)


def test_export_trial_refuses_unsafe_zip_directory_member(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    with zipfile.ZipFile(trial / "agent" / "trace.zip", "w") as archive:
        archive.writestr("../../tests/private/", "")

    with pytest.raises(TrialExportError, match="unsafe archive member"):
        export_trial(args)


def test_export_trial_backfills_model_and_provider_from_result(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    args.model = None
    args.provider = None

    record = export_trial(args)

    assert record["model"] == "openai/gpt-5.6-sol"
    assert record["provider"] == "openai"


def test_export_trial_hashes_non_secret_config_file(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    config_path = tmp_path / "agent-config.json"
    config_path.write_text('{"reasoning_effort":"high"}\n', encoding="utf-8")
    args.agent_config_file = config_path
    args.agent_config_hash = None

    record = export_trial(args)

    assert record["agent_config_hash"] == hashlib.sha256(config_path.read_bytes()).hexdigest()


def test_export_trial_emits_root_subagent_trajectory_events(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    trajectory_path = trial / "agent" / "trajectory.json"
    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    trajectory["subagent_trajectories"] = [
        {
            "schema_version": "ATIF-v1.7",
            "trajectory_id": "sub-1",
            "agent": {"name": "researcher", "version": "1.0"},
            "steps": [{"step_id": 1, "source": "agent", "message": "Found a source."}],
        }
    ]
    trajectory_path.write_text(json.dumps(trajectory), encoding="utf-8")

    record = export_trial(args)

    assert record["event_count"] == 3
    events = [
        json.loads(line)
        for line in (args.output_dir / "data" / "events.jsonl").read_text().splitlines()
    ]
    assert events[-1]["trajectory_path"].endswith("#subagent/sub-1")


def test_export_trial_emits_external_subagent_trajectory_events(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    trajectory_path = trial / "agent" / "trajectory.json"
    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    trajectory["steps"][1]["observation"] = {
        "results": [
            {"subagent_trajectory_ref": [{"trajectory_path": "trajectory.child.json"}]}
        ]
    }
    trajectory_path.write_text(json.dumps(trajectory), encoding="utf-8")
    (trial / "agent" / "trajectory.child.json").write_text(
        json.dumps(
            {
                "schema_version": "ATIF-v1.7",
                "agent": {"name": "researcher", "version": "1.0"},
                "steps": [{"step_id": 1, "source": "agent", "message": "Done."}],
            }
        ),
        encoding="utf-8",
    )

    record = export_trial(args)

    assert record["event_count"] == 3


def test_export_trial_rejects_external_image_reference(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    trajectory_path = trial / "agent" / "trajectory.json"
    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    trajectory["steps"][0]["message"] = [
        {"type": "image", "source": {"media_type": "image/png", "path": "/etc/passwd"}}
    ]
    trajectory_path.write_text(json.dumps(trajectory), encoding="utf-8")

    with pytest.raises(TrialExportError, match="image source is not local"):
        export_trial(args)


def test_export_trial_rejects_missing_image_reference(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    trajectory_path = trial / "agent" / "trajectory.json"
    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    trajectory["steps"][0]["message"] = [
        {"type": "image", "source": {"media_type": "image/png", "path": "missing.png"}}
    ]
    trajectory_path.write_text(json.dumps(trajectory), encoding="utf-8")

    with pytest.raises(TrialExportError, match="not included"):
        export_trial(args)


def test_export_trial_rejects_missing_external_subagent_trajectory(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    trajectory_path = trial / "agent" / "trajectory.json"
    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    trajectory["steps"][1]["observation"] = {
        "results": [{"subagent_trajectory_ref": [{"trajectory_path": "missing.json"}]}]
    }
    trajectory_path.write_text(json.dumps(trajectory), encoding="utf-8")

    with pytest.raises(TrialExportError, match="reference is missing"):
        export_trial(args)


def test_export_trial_marks_multistep_exception_as_failed(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    result_path = trial / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["step_results"] = [{"exception_info": {"exception_type": "TimeoutError"}}]
    result_path.write_text(json.dumps(result), encoding="utf-8")

    record = export_trial(args)

    assert record["status"] == "failed"


def test_export_trial_rejects_duplicate_record_index_entry(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    output = tmp_path / "export"
    args = _args(trial, output)
    _write_private_manifest(args)
    output.joinpath("data").mkdir(parents=True)
    output.joinpath("data", "trials.jsonl").write_text(
        json.dumps({"trial_id": "trial-0001"}) + "\n", encoding="utf-8"
    )

    with pytest.raises(TrialExportError, match="already exists in output index"):
        export_trial(args)


def test_export_trial_rejects_secret_config_hash(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    args.agent_config_hash = "sk-abcdefghijklmnopqrstuvwxyz"

    with pytest.raises(TrialExportError, match="config hash"):
        export_trial(args)


def test_export_trial_requires_result_task_checksum(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    result_path = trial / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    del result["task_checksum"]
    result_path.write_text(json.dumps(result), encoding="utf-8")

    with pytest.raises(TrialExportError, match="result.json must contain"):
        export_trial(args)


def test_export_trial_rejects_empty_metadata(tmp_path: Path) -> None:
    args = _args(_trial(tmp_path), tmp_path / "export")
    _write_private_manifest(args)
    args.benchmark = ""

    with pytest.raises(TrialExportError, match="benchmark"):
        export_trial(args)


def test_export_trial_requires_immutable_benchmark_revision(tmp_path: Path) -> None:
    args = _args(_trial(tmp_path), tmp_path / "export")
    _write_private_manifest(args)
    args.benchmark_hf_revision = "main"

    with pytest.raises(TrialExportError, match="immutable commit SHA"):
        export_trial(args)


def test_export_trial_appends_multiple_trials(tmp_path: Path) -> None:
    output = tmp_path / "export"
    first_trial = _trial(tmp_path / "first")
    first_args = _args(first_trial, output)
    _write_private_manifest(first_args)
    export_trial(first_args)

    second_trial = _trial(tmp_path / "second")
    second_args = _args(second_trial, output)
    _write_private_manifest(second_args)
    second_args.trial_id = "trial-0002"
    second_args.run_id = "run-0002"
    second_result_path = second_trial / "result.json"
    second_result = json.loads(second_result_path.read_text(encoding="utf-8"))
    second_result["id"] = "trial-0002"
    second_result["trial_name"] = "run-0002"
    second_result_path.write_text(json.dumps(second_result), encoding="utf-8")

    export_trial(second_args)

    records = [
        json.loads(line)
        for line in (output / "data" / "trials.jsonl").read_text().splitlines()
    ]
    assert [record["trial_id"] for record in records] == ["trial-0001", "trial-0002"]
    assert (output / "artifacts" / "trial-0001.tar.gz").is_file()
    assert (output / "artifacts" / "trial-0002.tar.gz").is_file()


def test_export_trial_refuses_symlinked_trial_root(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    trial_link = tmp_path / "trial-link"
    trial_link.symlink_to(trial, target_is_directory=True)
    args = _args(trial_link, tmp_path / "export")
    _write_private_manifest(args)

    with pytest.raises(TrialExportError, match="symlinked trial"):
        export_trial(args)


def test_failed_export_leaves_no_partial_output(tmp_path: Path) -> None:
    trial = _trial(tmp_path)
    output = tmp_path / "export"
    args = _args(trial, output)
    _write_private_manifest(args)
    trajectory_path = trial / "agent" / "trajectory.json"
    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    trajectory["schema_version"] = "ATIF-invalid"
    trajectory_path.write_text(json.dumps(trajectory), encoding="utf-8")

    with pytest.raises(TrialExportError):
        export_trial(args)

    assert not output.exists()


@pytest.mark.parametrize(
    "mutator",
    [
        lambda trajectory: trajectory.update({"schema_version": "ATIF-v0.1"}),
        lambda trajectory: trajectory["steps"][0].update({"timestamp": "not-a-time"}),
        lambda trajectory: trajectory["steps"][0].update({"step_id": "one"}),
        lambda trajectory: trajectory.update(
            {
                "subagent_trajectories": [
                    {"schema_version": "ATIF-v0.1", "trajectory_id": "sub-1", "steps": []}
                ]
            }
        ),
    ],
)
def test_export_trial_rejects_invalid_atif(tmp_path: Path, mutator) -> None:
    trial = _trial(tmp_path)
    args = _args(trial, tmp_path / "export")
    _write_private_manifest(args)
    trajectory_path = trial / "agent" / "trajectory.json"
    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    mutator(trajectory)
    trajectory_path.write_text(json.dumps(trajectory), encoding="utf-8")

    with pytest.raises(TrialExportError, match="ATIF"):
        export_trial(args)
