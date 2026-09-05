"""Atomic stage records bound to configuration and exact material hashes."""

import hashlib
import inspect
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def implementation_hash(*paths: Path) -> str:
    """Hash actual source/template bytes, not the checkout's commit label."""
    from .evidence import file_hash

    return fingerprint({str(file): file_hash(file)
                        for path in paths for file in (sorted(path.rglob("*")) if path.is_dir() else [path])
                        if file.is_file() and "__pycache__" not in file.parts
                        and (file.suffix in (".py", ".j2", ".md", ".json", ".yaml", ".yml", ".toml", ".sh", ".txt", ".sty", ".bst", ".cls", ".tex", ".bib") or file.name == "Dockerfile")})


def function_hash(*functions) -> str:
    return fingerprint([inspect.getsource(function) for function in functions])


class StageState:
    ORDER = ("evidence", "build", "materials", "validate", "review", "delivery", "conversion", "audit", "archive", "trial")
    STATUSES = ("pending", "running", "passed", "failed", "blocked")
    def __init__(self, path: Path, config: dict):
        self.path = path
        self.config = json.loads(json.dumps(config, default=str))
        self.record = {"schema_version": 1, "config": self.config, "stages": {}}
        if path.is_file():
            previous = json.loads(path.read_text(encoding="utf-8"))
            self._validate(previous)
            self.record = previous
        previous_config = self.record.get("current_config", self.record["config"])
        metadata_changed = previous_config != self.config or "current_config" not in self.record or "config_history" not in self.record
        self.record.setdefault("config_history", [])
        if previous_config != self.config:
            self.record.setdefault("config_history", []).append({"config": previous_config, "updated_at": datetime.now(UTC).isoformat()})
        self.record["current_config"] = self.config
        if path.is_file() and metadata_changed:
            atomic_json(path, self.record)

    @classmethod
    def _validate(cls, record: object) -> None:
        if (not isinstance(record, dict) or type(record.get("schema_version")) is not int or record["schema_version"] != 1
            or set(record) - {"schema_version", "config", "current_config", "config_history", "stages", "history"}
            or not isinstance(record.get("config"), dict) or not isinstance(record.get("stages"), dict)
            or not isinstance(record.get("current_config", {}), dict)
            or not isinstance(record.get("history", []), list) or not isinstance(record.get("config_history", []), list)):
            raise ValueError("unknown or malformed stage checkpoint schema")
        for item in record.get("config_history", []):
            if not isinstance(item, dict) or not isinstance(item.get("config"), dict) or not isinstance(item.get("updated_at"), str):
                raise ValueError("malformed checkpoint config history")  # noqa: TRY004 - invalid persisted schema
        entries = list(record["stages"].items())
        for item in record.get("history", []):
            if not isinstance(item, dict):
                raise ValueError("malformed checkpoint stage history")  # noqa: TRY004 - invalid persisted schema
            entries.append((item.get("stage"), item))
        for stage, entry in entries:
            if (stage not in cls.ORDER or not isinstance(entry, dict) or entry.get("status") not in cls.STATUSES
                or any(not isinstance(entry.get(key), str) or (entry[key] and not re.fullmatch(r"[0-9a-f]{64}", entry[key])) for key in ("input_sha256", "output_sha256"))
                or not isinstance(entry.get("updated_at"), str)):
                raise ValueError(f"malformed checkpoint stage: {stage}")
            try:
                datetime.fromisoformat(entry["updated_at"])
            except ValueError as error:
                raise ValueError(f"malformed checkpoint timestamp: {stage}") from error
            for key, expected in (("report", dict), ("outcome", dict), ("issues", list), ("compiles", list), ("feedback", str), ("attempt_id", str)):
                if key in entry and not isinstance(entry[key], expected):
                    raise ValueError(f"malformed checkpoint {stage}.{key}")
            if "report" in entry:
                report = entry["report"]
                if (type(report.get("ok")) is not bool or not isinstance(report.get("reasoning"), str)
                    or not isinstance(report.get("concerns"), list) or not all(isinstance(item, str) for item in report["concerns"])
                    or ("blocked" in report and type(report["blocked"]) is not bool)):
                    raise ValueError(f"malformed checkpoint verdict: {stage}")
            for item in entry.get("compiles", []):
                if not isinstance(item, dict) or type(item.get("ok")) is not bool or not isinstance(item.get("tex_name"), str):
                    raise ValueError(f"malformed checkpoint compilation: {stage}")
            for item in entry.get("issues", []):
                if not isinstance(item, dict) or not all(isinstance(item.get(key), str) for key in ("code", "message", "remedy")):
                    raise ValueError(f"malformed checkpoint issue: {stage}")
            if entry["status"] == "passed":
                required = {"review": ("report", dict), "delivery": ("outcome", dict),
                            "conversion": ("result", int), "audit": ("result", dict),
                            "archive": ("result", str), "trial": ("result", dict)}
                if stage in required:
                    key, expected = required[stage]
                    if type(entry.get(key)) is not expected:
                        raise ValueError(f"missing or malformed checkpoint {stage}.{key}")

    def reusable(self, stage: str, inputs: str, outputs: str) -> bool:
        entry = self.record["stages"].get(stage, {})
        return (entry.get("status") == "passed" and entry.get("input_sha256") == inputs
                and entry.get("output_sha256") == outputs)

    def save(self, stage: str, status: str, inputs: str, outputs: str = "", **details) -> None:
        if stage not in self.ORDER or status not in self.STATUSES:
            raise ValueError(f"unknown checkpoint stage/status: {stage}/{status}")
        stages = self.record["stages"]
        previous = stages.get(stage, {})
        if previous:
            self.record.setdefault("history", []).append({"stage": stage, **previous})
        # Removing downstream records prevents stale acceptance after an upstream rerun.
        for downstream in self.ORDER[self.ORDER.index(stage) + 1:]:
            if downstream in stages:
                self.record.setdefault("history", []).append({"stage": downstream, **stages.pop(downstream)})
        stages[stage] = {
            "status": status, "input_sha256": inputs, "output_sha256": outputs,
            "updated_at": datetime.now(UTC).isoformat(),
            "attempt_id": previous.get("attempt_id", uuid4().hex) if status != "running" else uuid4().hex,
            "config_sha256": fingerprint(self.config),
            "implementation": self.config.get("implementation"),
            **details,
        }
        self._validate(self.record)
        atomic_json(self.path, self.record)
