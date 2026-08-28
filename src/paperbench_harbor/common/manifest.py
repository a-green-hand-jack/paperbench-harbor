from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_source_manifest(
    *,
    destination: Path,
    benchmark: str,
    upstream_id: str,
    protocol: str,
    upstream_revision: str | None,
    public_files: list[Path],
    private_files: list[Path],
    extra: dict[str, Any] | None = None,
) -> None:
    """Write a verifier-only provenance manifest for one generated task."""

    payload: dict[str, Any] = {
        "benchmark": benchmark,
        "upstream_id": upstream_id,
        "protocol": protocol,
        "upstream_revision": upstream_revision,
        "public_file_hashes": {str(path): sha256_file(path) for path in public_files},
        "private_file_hashes": {str(path): sha256_file(path) for path in private_files},
    }
    if extra:
        payload["extra"] = extra

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
