"""Real Harbor trials and evidence readers shared by delivery and publication."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from paperbench_harbor.common.audit import audit_public_materials
from paperbench_harbor.common.task_contract import assert_valid_task_contract

from .evidence import contained_path, file_hash, safe_file, tree_hash


def diagnose_trial(*, reward: float | None, exception: str | None, material_ok: bool) -> str:
    if exception:
        return "environment"
    if not material_ok:
        return "material_defect"
    if type(reward) in (int, float) and reward == 1:
        return "contract_passed_material_review_passed"
    return "model_or_task_unresolved"


def read_harbor_result(path: Path, *, task: Path, model: str, agent: str, agent_version: str) -> dict:
    """Validate completed native result identity without exposing embedded config/env."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("Harbor result must be an object")
    for key in ("started_at", "finished_at"):
        if not isinstance(data.get(key), str):
            raise TypeError(f"Harbor result lacks {key}")
        datetime.fromisoformat(data[key])
    if data.get("task_name") != task.name or data.get("task_id", {}).get("path") != str(task.resolve()):
        raise ValueError("Harbor result task identity mismatch")
    info = data.get("agent_info", {})
    config = data.get("config", {}).get("agent", {})
    if (info.get("name") != agent or info.get("version") != agent_version
        or config.get("name") != agent or config.get("model_name") != model
        or config.get("kwargs", {}).get("version") != agent_version):
        raise ValueError("Harbor result model/agent/version mismatch")
    provider, model_name = model.split("/", 1)
    if info.get("model_info") != {"provider": provider, "name": model_name}:
        raise ValueError("Harbor observed model identity mismatch")
    environment = data.get("config", {}).get("environment", {})
    if (environment.get("type") != "docker" or environment.get("mounts")
        or environment.get("extra_docker_compose")
        or data.get("config", {}).get("extra_instruction_paths")
        or data.get("config", {}).get("verifier", {}).get("disable") is not False):
        raise ValueError("Harbor result does not preserve isolated verified trial configuration")
    exception_info = data.get("exception_info")
    exception = None
    if exception_info is not None:
        if not isinstance(exception_info, dict) or not isinstance(exception_info.get("exception_type"), str):
            raise ValueError("invalid Harbor exception record")
        exception = exception_info["exception_type"]
    reward = (data.get("verifier_result") or {}).get("rewards", {}).get("reward")
    if reward is None and exception:
        return {"reward": None, "exception": exception, "trial_name": data.get("trial_name")}
    if type(reward) not in (int, float) or reward not in (0, 1):
        raise ValueError("Harbor result lacks binary numeric contract reward")
    return {"reward": reward, "exception": exception, "trial_name": data.get("trial_name")}


def verify_trial_evidence(reference: dict, *, root: Path, task: Path, paper: Path,
                          knowledge: dict, execution: dict) -> dict:
    report_path = contained_path(root / "trials" / task.name, Path(reference["evidence_path"]))
    if file_hash(report_path) != reference["evidence_sha256"]:
        raise ValueError("stale trial evidence")
    record = json.loads(report_path.read_text())
    if record.get("task_id") != task.name or record.get("task_sha256") != tree_hash(task):
        raise ValueError("trial task hash/identity mismatch")
    if record.get("status") != "completed" or record.get("exception") is not None or record.get("returncode") != 0:
        raise ValueError("trial is not completed without exceptions")
    for key in ("model", "agent", "agent_version"):
        if record.get(key) != execution[f"trial_{key}"]:
            raise ValueError(f"trial {key} mismatch")
    if record.get("knowledge") != knowledge:
        raise ValueError("trial knowledge package mismatch")
    review_path = contained_path(root / "corpus", Path(record["review_path"]))
    if review_path != paper / "original" / "reconstructability_review.json":
        raise ValueError("construction review path mismatch")
    if file_hash(review_path) != record.get("review_sha256"):
        raise ValueError("construction review hash mismatch")
    review = json.loads(review_path.read_text())
    if (review.get("ok") is not True or review.get("model") != execution["reviewer_model"]
        or review.get("knowledge") != knowledge
        or review.get("materials_sha256") != tree_hash(paper, exclude=("original/reconstructability_review.json",))):
        raise ValueError("construction review is stale or mismatched")
    result_path = contained_path(report_path.parent, Path(record["result_path"]))
    if file_hash(result_path) != record.get("result_sha256"):
        raise ValueError("trial result hash mismatch")
    result = read_harbor_result(result_path, task=task, model=record["model"],
                               agent=record["agent"], agent_version=record["agent_version"])
    if result["exception"] is not None or result["reward"] != 1:
        raise ValueError("Harbor result has an exception or contract reward is not 1")
    trajectories = record.get("trajectories")
    if not isinstance(trajectories, list) or not trajectories:
        raise ValueError("missing trajectory evidence")
    for trajectory in trajectories:
        path = contained_path(result_path.parent / "agent", Path(trajectory["path"]))
        if file_hash(path) != trajectory["sha256"] or path.stat().st_size == 0:
            raise ValueError("trajectory hash mismatch or empty artifact")
    return record


def run_trial(task: Path, *, output: Path, model: str, agent: str, agent_version: str,
              knowledge: dict, material_review: dict, review_path: Path, timeout: int) -> dict:
    assert_valid_task_contract(task)
    revision = tree_hash(task)
    environment = task / "environment"
    provenance_path = task / "tests" / "private" / "ground_truth_sources" / "provenance.json"
    code_approved = False
    if (environment / "materials" / "code").exists():
        import re

        provenance = json.loads(safe_file(task, provenance_path.relative_to(task).as_posix()).read_text())
        code_approved = (provenance.get("code_status", "available") == "available" and
                         bool(provenance.get("code_repo")) and
                         bool(re.fullmatch(r"[0-9a-f]{40}", provenance.get("code_commit", ""))))
    audit_public_materials(environment, code_prefix="materials/code", code_approved=code_approved)
    output.mkdir(parents=True, exist_ok=False)
    command = ["harbor", "run", "--path", str(task.resolve()), "--agent", agent,
               "--model", model, "--ak", f"version={agent_version}", "--env", "docker",
               "--jobs-dir", str(output.resolve()), "--job-name", "writer-trial",
               "--n-concurrent", "1", "--n-attempts", "1", "--max-retries", "0", "--yes"]
    if agent == "codex" and "CODEX_AUTH_JSON_PATH" in os.environ:
        # Harbor.utils.env.resolve_env_vars expands this, not the shell. Keep secrets out of argv.
        command.extend(["--ae", "CODEX_AUTH_JSON_PATH=${CODEX_AUTH_JSON_PATH}"])
    record = {"schema_version": 1, "task_id": task.name, "task_sha256": revision,
              "writer_environment_sha256": tree_hash(environment), "model": model,
              "agent": agent, "agent_version": agent_version, "knowledge": knowledge,
              "command": command, "timeout_seconds": timeout, "status": "running",
              "scientific_quality": "not_evaluated", "review_path": str(review_path.resolve()),
              "review_sha256": file_hash(review_path)}
    report_path = output / "trial-evidence.json"
    report_path.write_text(json.dumps(record, indent=2) + "\n")
    exception = None
    reward = None
    with (output / "harbor.log").open("w") as log:
        try:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=timeout, check=False)
            record["returncode"] = result.returncode
            if result.returncode:
                exception = f"harbor_exit_{result.returncode}"
        except (OSError, subprocess.TimeoutExpired) as error:
            exception = type(error).__name__
    try:
        results = list((output / "writer-trial").glob("*/result.json"))
        if len(results) != 1:
            raise ValueError("missing unique Harbor result")
        result_path = contained_path(output, results[0])
        parsed = read_harbor_result(result_path, task=task, model=model, agent=agent,
                                    agent_version=agent_version)
        reward = parsed["reward"]
        exception = exception or parsed["exception"]
        record.update(result_path=str(result_path), result_sha256=file_hash(result_path))
        paths = list(result_path.parent.glob("agent/trajectory*.json"))
        if not paths:
            raise ValueError("missing trajectory artifact")
        record["trajectories"] = [{"path": str(contained_path(result_path.parent / "agent", p)),
                                   "sha256": file_hash(p)} for p in paths if p.stat().st_size]
        if not record["trajectories"]:
            raise ValueError("empty trajectory artifacts")
        if tree_hash(task) != revision:
            raise ValueError("task changed during trial")
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        exception = exception or f"invalid_trial_evidence:{type(error).__name__}"
    record.update(status="blocked" if exception else "completed", exception=exception,
                  contract_reward=reward,
                  diagnosis=diagnose_trial(reward=reward, exception=exception, material_ok=material_review.get("ok") is True))
    report_path.write_text(json.dumps(record, indent=2) + "\n")
    return {**record, "evidence_path": str(report_path.resolve()), "evidence_sha256": file_hash(report_path)}
