"""Content-addressed manifests for the raw source trees consumed by a workflow."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from paperbench_harbor.common.manifest import sha256_file
from paperbench_harbor.source_archive.registry import SourceArchiveError


def _tree_digest(records: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(str(record["path"]).encode())
        digest.update(b"\0")
        digest.update(str(record["sha256"]).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _write(destination: Path, *, source_type: str, records: list[dict[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "source_type": source_type,
        "file_count": len(records),
        "tree_sha256": _tree_digest(records),
        "files": records,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def write_directory_tree_manifest(*, source_root: Path, destination: Path) -> dict[str, object]:
    """Hash every regular file beneath a raw source directory, in stable order."""
    if not source_root.is_dir():
        raise SourceArchiveError(f"source directory does not exist: {source_root}")
    records = [
        {
            "path": path.relative_to(source_root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(source_root.rglob("*"))
        if path.is_file()
    ]
    return _write(destination, source_type="directory", records=records)


def write_zip_tree_manifest(*, source_zip: Path, destination: Path) -> dict[str, object]:
    """Hash uncompressed regular members of a source zip without extracting it."""
    if not source_zip.is_file():
        raise SourceArchiveError(f"source zip does not exist: {source_zip}")
    try:
        with zipfile.ZipFile(source_zip) as archive:
            members = sorted(
                (member for member in archive.infolist() if not member.is_dir()),
                key=lambda member: member.filename,
            )
            records = [
                {
                    "path": member.filename,
                    "bytes": member.file_size,
                    "sha256": hashlib.sha256(archive.read(member)).hexdigest(),
                }
                for member in members
            ]
    except zipfile.BadZipFile as error:
        raise SourceArchiveError(f"source zip is invalid: {source_zip}") from error
    return _write(destination, source_type="zip", records=records)
