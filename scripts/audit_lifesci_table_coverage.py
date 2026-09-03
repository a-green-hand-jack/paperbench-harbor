#!/usr/bin/env python3
"""Audit LifeSci source-table coverage before converting a corpus to Harbor.

The report is derived from the complete reachable TeX source tree, not from a
`tables/` directory. It is intended as a release gate for PaperSmith rebuilds:
each source table must have a matching immutable public fragment, inventory
record and summary entry. The script does not repair corpus files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperbench_harbor.construction.core.validate import (
    TABLE_INVENTORY_FILENAME,
    collect_source_tables,
)


def _public_table_paths(resources: Path) -> set[str]:
    table_dir = resources / "tables"
    if not table_dir.is_dir():
        return set()
    return {
        f"tables/{path.relative_to(table_dir).as_posix()}"
        for path in table_dir.rglob("*")
        if path.is_file()
    }


def _safe_public_path(value: object) -> Path | None:
    if not isinstance(value, str):
        return None
    path = Path(value)
    if (
        path.is_absolute()
        or len(path.parts) < 2
        or path.parts[0] != "tables"
        or ".." in path.parts
    ):
        return None
    return path


def _published_paper_ids(manifest_path: Path) -> list[str]:
    """Read upstream ids in task order from a published dataset manifest."""

    if not manifest_path.is_file():
        raise ValueError(f"published manifest does not exist: {manifest_path}")
    paper_ids: list[str] = []
    seen: set[str] = set()
    for line_number, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"published manifest {manifest_path}:{line_number} is invalid JSON: {error.msg}"
            ) from error
        paper_id = record.get("upstream_paper_id") if isinstance(record, dict) else None
        if not isinstance(paper_id, str) or not paper_id:
            raise ValueError(
                f"published manifest {manifest_path}:{line_number} has no upstream_paper_id"
            )
        if paper_id in seen:
            raise ValueError(
                f"published manifest {manifest_path}:{line_number} repeats {paper_id!r}"
            )
        seen.add(paper_id)
        paper_ids.append(paper_id)
    if not paper_ids:
        raise ValueError(f"published manifest has no task records: {manifest_path}")
    return paper_ids


def audit_paper(paper_dir: Path) -> dict[str, object]:
    """Return one deterministic coverage record for a source corpus paper."""

    original = paper_dir / "original"
    resources = paper_dir / "resources"
    source_tables = collect_source_tables(original)
    actual_paths = _public_table_paths(resources)
    summary_path = resources / "table_summary.txt"
    summary_text = (
        summary_path.read_text(encoding="utf-8", errors="replace")
        if summary_path.is_file()
        else ""
    )
    mismatches: list[str] = []
    inventory_path = resources / TABLE_INVENTORY_FILENAME
    records_by_id: dict[str, dict[str, object]] = {}
    if not inventory_path.is_file():
        mismatches.append(f"missing resources/{TABLE_INVENTORY_FILENAME}")
    else:
        try:
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            mismatches.append(f"invalid inventory JSON: {error.msg}")
            inventory = None
        if inventory is not None:
            if (
                not isinstance(inventory, dict)
                or inventory.get("schema_version") != 1
                or not isinstance(inventory.get("tables"), list)
            ):
                mismatches.append("inventory schema is not schema_version=1 with a tables list")
            else:
                for record in inventory["tables"]:
                    table_id = record.get("id") if isinstance(record, dict) else None
                    if not isinstance(record, dict) or not isinstance(table_id, str):
                        mismatches.append("inventory contains a record without a string id")
                        continue
                    if table_id in records_by_id:
                        mismatches.append(f"inventory has duplicate id {table_id}")
                        continue
                    records_by_id[table_id] = record

    expected_ids = {table.id for table in source_tables}
    unexpected_ids = sorted(set(records_by_id) - expected_ids)
    if unexpected_ids:
        mismatches.append("inventory-only ids: " + ", ".join(unexpected_ids))

    referenced_paths: set[str] = set()
    for table in source_tables:
        record = records_by_id.get(table.id)
        if record is None:
            mismatches.append(
                f"{table.id} missing for source {table.source_path}:{table.line_start}"
            )
            continue
        expected = {
            "source_path": table.source_path,
            "line_start": table.line_start,
            "environment": table.environment,
            "caption": table.caption,
            "label": table.label,
            "content_sha256": table.content_sha256,
        }
        differing = [key for key, value in expected.items() if record.get(key) != value]
        if differing:
            mismatches.append(f"{table.id} source metadata differs: {', '.join(differing)}")
        relative = _safe_public_path(record.get("public_path"))
        if relative is None:
            mismatches.append(f"{table.id} has unsafe or missing public_path")
            continue
        public_path = relative.as_posix()
        if public_path in referenced_paths:
            mismatches.append(f"{table.id} duplicates public path: {public_path}")
            continue
        referenced_paths.add(public_path)
        material = resources / relative
        if not material.is_file():
            mismatches.append(f"{table.id} material missing: {public_path}")
        elif hashlib.sha256(material.read_bytes()).hexdigest() != table.content_sha256:
            mismatches.append(f"{table.id} material content differs: {public_path}")
        if public_path not in summary_text:
            mismatches.append(f"{table.id} summary omits path: {public_path}")
        if table.caption and table.caption not in summary_text:
            mismatches.append(f"{table.id} summary omits caption")

    untracked_paths = sorted(actual_paths - referenced_paths)
    if untracked_paths:
        mismatches.append("untracked public tables: " + ", ".join(untracked_paths))
    if source_tables:
        if "no table" in summary_text.lower():
            mismatches.append("summary falsely says no tables")
    elif records_by_id:
        mismatches.append("inventory has tables although source has none")
    elif "no table" not in summary_text.lower():
        mismatches.append("empty source inventory has no explicit no-tables summary")

    source_locations = Counter(
        "main_tex" if table.source_path == "main.tex" else "included_tex"
        for table in source_tables
    )
    environments = Counter(table.environment for table in source_tables)
    return {
        "paper_id": paper_dir.name,
        "source_table_count": len(source_tables),
        "public_table_count": len(actual_paths),
        "source_locations": dict(sorted(source_locations.items())),
        "source_environments": dict(sorted(environments.items())),
        "mismatches": mismatches,
        "status": "ok" if not mismatches else "mismatch",
    }


def audit_corpus(source: Path, paper_ids: list[str] | None = None) -> dict[str, object]:
    """Audit all direct paper directories under ``source`` in a stable order."""

    available = {
        path.name: path
        for path in sorted(
        path
        for path in source.iterdir()
        if path.is_dir() and (path / "original").is_dir() and (path / "resources").is_dir()
        )
    }
    selected_ids = paper_ids if paper_ids is not None else sorted(available)
    records: list[dict[str, object]] = []
    for paper_id in selected_ids:
        paper = available.get(paper_id)
        if paper is None:
            records.append(
                {
                    "paper_id": paper_id,
                    "source_table_count": 0,
                    "public_table_count": 0,
                    "source_locations": {},
                    "source_environments": {},
                    "mismatches": ["paper directory is absent from the source corpus"],
                    "status": "mismatch",
                }
            )
        else:
            records.append(audit_paper(paper))
    failed = [record["paper_id"] for record in records if record["status"] != "ok"]
    return {
        "schema_version": 1,
        "source": str(source),
        "total_tasks": len(records),
        "total_source_tables": sum(record["source_table_count"] for record in records),
        "total_public_tables": sum(record["public_table_count"] for record in records),
        "mismatched_tasks": failed,
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Validated LifeSci source corpus")
    parser.add_argument("--output", type=Path, required=True, help="Coverage report JSON path")
    parser.add_argument(
        "--published-manifest",
        type=Path,
        default=None,
        help="Dataset-manifest.jsonl selecting exactly the currently published tasks.",
    )
    args = parser.parse_args()
    source = args.source.resolve()
    if not source.is_dir():
        parser.error(f"source corpus does not exist: {source}")

    try:
        paper_ids = (
            _published_paper_ids(args.published_manifest) if args.published_manifest else None
        )
    except ValueError as error:
        parser.error(str(error))
    report = audit_corpus(source, paper_ids)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "records"}))
    return 1 if report["mismatched_tasks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
