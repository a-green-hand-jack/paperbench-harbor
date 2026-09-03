#!/usr/bin/env python3
"""Create a portable content-hash manifest for a raw workflow source tree."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperbench_harbor.source_archive import (
    SourceArchiveError,
    write_directory_tree_manifest,
    write_zip_tree_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-root", type=Path)
    source.add_argument("--source-zip", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.source_root:
            report = write_directory_tree_manifest(
                source_root=args.source_root,
                destination=args.output,
            )
        else:
            report = write_zip_tree_manifest(source_zip=args.source_zip, destination=args.output)
    except SourceArchiveError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps({key: report[key] for key in ("file_count", "tree_sha256")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
