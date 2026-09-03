#!/usr/bin/env python3
"""Fail closed unless every task config has full audit and archive evidence.

Run this immediately before uploading a runnable Paper-Writing-Exam release.
It does not upload anything itself: the success report is the durable gate that
the release documentation and the two Hugging Face dataset cards must cite.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperbench_harbor.source_archive import SourceArchiveError, validate_release_provenance


def _audit_summary(value: str) -> tuple[str, Path]:
    config, separator, path = value.partition("=")
    if not separator or not config or not path:
        raise argparse.ArgumentTypeError("--audit-summary must be CONFIG=/path/to/summary.json")
    return config, Path(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument(
        "--audit-summary",
        type=_audit_summary,
        action="append",
        required=True,
        metavar="CONFIG=PATH",
        help="version-bound summary.json produced by scripts/audit_fidelity.py",
    )
    args = parser.parse_args()
    summaries = dict(args.audit_summary)
    if len(summaries) != len(args.audit_summary):
        parser.error("--audit-summary config names must be unique")
    try:
        report = validate_release_provenance(
            plan_path=args.plan,
            dataset_root=args.dataset_root,
            archive_root=args.archive_root,
            audit_summaries=summaries,
        )
    except SourceArchiveError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
