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
    root: Path | None = None,
    source_root: Path | None = None,
    material_provenance: dict[Path, tuple[str, Path]] | None = None,
) -> None:
    """Write a verifier-only provenance manifest for one generated task.

    File hashes are keyed by paths relative to `root` (the task directory when
    provided, otherwise inferred from the manifest location
    `<task>/tests/private/source_manifest.json`). This keeps the manifest
    deterministic and portable across machines: the same fixed input must
    produce the same manifest regardless of the absolute output directory.

    `material_provenance` sources are relative to `source_root` for the same
    reason. Without it they were written absolute, which put the build host's
    directory layout into a public dataset and made byte-identical
    reproduction require converting from that same absolute path. The audit's
    determinism check converts twice from one source path, so it could not see
    this.

    A source outside `source_root` keeps its absolute path rather than being
    silently rewritten: that is a conversion reaching somewhere unexpected, and
    the manifest is where it should be visible.
    """

    if root is None:
        # Fall back to the task directory inferred from the manifest location
        # <task>/tests/private/source_manifest.json.
        root = destination.parent.parent.parent

    def _relative_to(path: Path, base: Path | None) -> str:
        if base is None:
            return str(path)
        try:
            return path.resolve().relative_to(base.resolve()).as_posix()
        except ValueError:
            return str(path)

    def relative(path: Path) -> str:
        return _relative_to(path, root)

    payload: dict[str, Any] = {
        "benchmark": benchmark,
        "upstream_id": upstream_id,
        "protocol": protocol,
        "upstream_revision": upstream_revision,
        "public_file_hashes": {relative(path): sha256_file(path) for path in public_files},
        "private_file_hashes": {relative(path): sha256_file(path) for path in private_files},
    }
    if material_provenance:
        payload["material_provenance"] = {
            relative(destination_path): {
                "origin": origin,
                "source_path": _relative_to(source_path, source_root),
                "source_sha256": sha256_file(source_path),
            }
            for destination_path, (origin, source_path) in sorted(
                material_provenance.items(), key=lambda item: relative(item[0])
            )
        }
    if extra:
        payload["extra"] = extra

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
