"""Atomic stage records bound to configuration and exact material hashes."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class StageState:
    ORDER = ("evidence", "build", "materials", "validate", "review", "delivery")
    def __init__(self, path: Path, config: dict):
        self.path = path
        self.config = config
        self.record = {"schema_version": 1, "config": config, "stages": {}}
        if path.is_file():
            previous = json.loads(path.read_text(encoding="utf-8"))
            if previous.get("config") == config:
                self.record = previous

    def reusable(self, stage: str, inputs: str, outputs: str) -> bool:
        entry = self.record["stages"].get(stage, {})
        return (entry.get("status") == "passed" and entry.get("input_sha256") == inputs
                and entry.get("output_sha256") == outputs)

    def save(self, stage: str, status: str, inputs: str, outputs: str = "", **details) -> None:
        stages = self.record["stages"]
        # Removing downstream records prevents stale acceptance after an upstream rerun.
        if stage not in self.ORDER:
            raise ValueError(f"unknown construction stage: {stage}")
        for downstream in self.ORDER[self.ORDER.index(stage) + 1:]:
            stages.pop(downstream, None)
        stages[stage] = {
            "status": status, "input_sha256": inputs, "output_sha256": outputs,
            "updated_at": datetime.now(UTC).isoformat(), **details,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.record, indent=2, sort_keys=True) + "\n")
        temporary.replace(self.path)
