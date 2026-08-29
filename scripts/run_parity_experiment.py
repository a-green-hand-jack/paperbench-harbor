#!/usr/bin/env python3
"""Compare writer-visible task surfaces between two Harbor dataset roots."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def files(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and "solution" not in path.parts and "tests" not in path.parts:
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    left, right = files(args.left), files(args.right)
    shared = sorted(set(left) & set(right))
    report = {
        "left": str(args.left),
        "right": str(args.right),
        "left_file_count": len(left),
        "right_file_count": len(right),
        "missing_from_right": sorted(set(left) - set(right)),
        "missing_from_left": sorted(set(right) - set(left)),
        "hash_mismatches": [name for name in shared if left[name] != right[name]],
        "identical_writer_surface": left == right,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("left_file_count", "right_file_count", "identical_writer_surface")}))
    return 0 if report["identical_writer_surface"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
