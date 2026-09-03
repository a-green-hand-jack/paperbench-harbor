"""Merge same-domain PaperRecon screening reports into one immutable set.

The merge is deliberately deterministic: candidate records are sorted by
arXiv id, exact duplicates are collapsed, and conflicting duplicates fail
closed.  A sidecar manifest records the input and output hashes without making
the candidate JSON itself depend on a wall-clock timestamp.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperbench_harbor.construction.core.screen import ScreeningError
from paperbench_harbor.construction.domains import get_domain
from scripts.promote_lifesci_paperrecon_candidates import read_candidates


class ConsolidationError(RuntimeError):
    """The reports cannot be merged without losing auditability."""


_IDENTITY_FIELDS = (
    "arxiv_id",
    "expected_version",
    "code_status",
    "code_repo",
    "expected_license",
    "code_license",
    "code_not_applicable_reason",
    "expected_category",
    "paper_type",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path, domain_name: str) -> tuple[list[dict], str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConsolidationError(f"cannot read {path}: {error}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
        raise ConsolidationError(f"{path} must be a screening report object with candidates")
    if payload.get("domain") != domain_name:
        raise ConsolidationError(f"{path} is for domain {payload.get('domain')!r}, not {domain_name!r}")
    domain = get_domain(domain_name)
    try:
        parsed = read_candidates(path, policy=domain.screening_policy, exclude_ids=domain.exclude_ids)
    except ScreeningError as error:
        raise ConsolidationError(f"{path} failed policy validation: {error}") from error
    discovery = payload.get("lkm_discovery")
    return [candidate.as_dict() for candidate in parsed], discovery if isinstance(discovery, str) else None


def consolidate(
    reports: list[Path], *, domain_name: str, output: Path, minimum: int = 20, reserve: int = 0
) -> dict:
    if not reports:
        raise ConsolidationError("at least one candidate report is required")
    if minimum < 1 or reserve < 0:
        raise ConsolidationError("minimum must be positive and reserve must be non-negative")

    merged: dict[str, dict] = {}
    inputs: list[dict[str, object]] = []
    discoveries: set[str] = set()
    for report in reports:
        records, discovery = _load(report.resolve(), domain_name)
        inputs.append({"path": str(report.resolve()), "sha256": _sha256(report.resolve())})
        if discovery:
            discovery_path = Path(discovery)
            if discovery_path.is_file():
                discoveries.add(str(discovery_path.resolve()))
        for record in records:
            arxiv_id = record["arxiv_id"]
            previous = merged.get(arxiv_id)
            if previous is not None:
                if any(previous[field] != record[field] for field in _IDENTITY_FIELDS):
                    raise ConsolidationError(f"conflicting records for arxiv_id {arxiv_id}")
                # Notes and rationales are narrative evidence, not identity.
                # Pick one canonically so rerun wording cannot block a merge.
                merged[arxiv_id] = min(
                    previous,
                    record,
                    key=lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")),
                )
            else:
                merged[arxiv_id] = record

    candidates = [merged[key] for key in sorted(merged)]
    required = minimum + reserve
    if len(candidates) < required:
        raise ConsolidationError(
            f"only {len(candidates)} unique candidates; need at least {required} (minimum={minimum}, reserve={reserve})"
        )
    payload = {
        "schema_version": 2,
        "domain": domain_name,
        "minimum_count": minimum,
        "reserve_count": reserve,
        "input_reports": inputs,
        "discovery_snapshots": [
            {"path": path, "sha256": _sha256(Path(path))} for path in sorted(discoveries)
        ],
        "candidates": candidates,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "domain": domain_name,
        "candidate_set": str(output.resolve()),
        "candidate_set_sha256": _sha256(output),
        "input_reports": inputs,
        "discovery_snapshots": payload["discovery_snapshots"],
        "merge_tool": "consolidate_paperrecon_candidates:v1",
    }
    manifest_path = output.with_name(f"{output.stem}.manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**manifest, "count": len(candidates), "manifest": str(manifest_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", choices=("lifesci", "physics", "chemistry", "mathematics"), required=True)
    parser.add_argument("--report", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum", type=int, default=20)
    parser.add_argument("--reserve", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        result = consolidate(args.report, domain_name=args.domain, output=args.output, minimum=args.minimum, reserve=args.reserve)
    except ConsolidationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
