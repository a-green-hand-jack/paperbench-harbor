#!/usr/bin/env python3
"""Diff a freshly converted dataset against the published release, byte for byte.

The first test of any converter refactor is that it still produces exactly the
bytes people are already running. `v0.3.1` is the current release, at immutable
revision `bfe2471c41f416d877e74bfa73cf0f29165c7567`; nothing in `adapters/` may
change what comes out of it.

This is deliberately not a pytest: it needs the upstream corpora and a local
copy of the published dataset, neither of which is in the repository, and a
full run converts hundreds of papers. It is the gate a refactor PR reports,
not something CI can run.

Usage:
    uv run --extra datasets scripts/regress_release.py paperwrite-bench \\
        --source /path/to/upstream-data/PaperWrite-Bench \\
        --published /path/to/v0.3.1/paperwrite-bench-short \\
        --upstream-revision <rev-recorded-in-the-release>

Exit status is 0 only when every file matches. Anything else is a regression.

A change that is *meant* to alter the release is named with `--ignore` at the
call site rather than hidden in this file, so the run someone reports shows
exactly which guarantees were relaxed. As of the network-policy and
reproducibility fixes, reproducing v0.3.1 needs:

    --ignore '*/tests/private/source_manifest.json' \
    --ignore '*/__pycache__/*' \
    --ignore '*/task.toml'
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from fnmatch import fnmatch
from pathlib import Path

from paperbench_harbor.adapters.lifesci_paperrecon.harbor import (
    lifesci_paperrecon_conversion_config,
)
from paperbench_harbor.adapters.paperwrite_bench.converter import (
    PaperWriteBenchConversionConfig,
    convert_paperwrite_bench,
)
from paperbench_harbor.adapters.paperwritingbench.converter import (
    PaperWritingBenchConversionConfig,
    convert_paperwritingbench,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _index(root: Path, ignore: tuple[str, ...]) -> dict[str, str]:
    return {
        rel: _sha256(root / rel)
        for path in root.rglob("*")
        if path.is_file()
        for rel in [path.relative_to(root).as_posix()]
        if not any(fnmatch(rel, pattern) for pattern in ignore)
    }


def _convert(args: argparse.Namespace, out: Path) -> None:
    if args.command == "paperwrite-bench":
        convert_paperwrite_bench(
            PaperWriteBenchConversionConfig(
                source=args.source,
                output_dir=out,
                overview=args.overview,
                overwrite=True,
                upstream_revision=args.upstream_revision,
            )
        )
    elif args.command == "lifesci-paperrecon":
        convert_paperwrite_bench(
            lifesci_paperrecon_conversion_config(
                source=args.source,
                output_dir=out,
                overview=args.overview,
                overwrite=True,
                upstream_revision=args.upstream_revision,
            )
        )
    else:
        convert_paperwritingbench(
            PaperWritingBenchConversionConfig(
                source=args.source,
                output_dir=out,
                protocol=args.protocol,
                overwrite=True,
                upstream_revision=args.upstream_revision,
            )
        )


def _report(fresh: dict[str, str], published: dict[str, str], limit: int) -> dict:
    missing = sorted(set(published) - set(fresh))
    added = sorted(set(fresh) - set(published))
    changed = sorted(
        rel for rel in set(fresh) & set(published) if fresh[rel] != published[rel]
    )
    result = {
        "published_files": len(published),
        "converted_files": len(fresh),
        "identical": len(set(fresh) & set(published)) - len(changed),
        "missing_from_conversion": len(missing),
        "added_by_conversion": len(added),
        "content_changed": len(changed),
        "ok": not (missing or added or changed),
    }
    for label, items in (
        ("missing_from_conversion", missing),
        ("added_by_conversion", added),
        ("content_changed", changed),
    ):
        if items:
            result[f"{label}_sample"] = items[:limit]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("paperwrite-bench", "lifesci-paperrecon", "paperwritingbench"):
        p = sub.add_parser(name)
        p.add_argument("--source", type=Path, required=True)
        p.add_argument("--published", type=Path, required=True)
        p.add_argument("--upstream-revision", required=True)
        p.add_argument("--limit", type=int, default=20, help="paths to show per category")
        p.add_argument(
            "--ignore",
            action="append",
            metavar="GLOB",
            help=(
                "Exclude matching paths from BOTH sides. Use only for a delta you "
                "intend, and name it on the command line so it appears in the run "
                "you report -- never bury one in this file."
            ),
        )
        if name == "paperwritingbench":
            p.add_argument("--protocol", default="sparse-plotoff")
        else:
            p.add_argument("--overview", default="short")
    args = parser.parse_args()

    if not args.published.is_dir():
        raise SystemExit(f"published dataset not found: {args.published}")

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "converted"
        _convert(args, out)
        ignore = tuple(args.ignore or ())
        result = _report(
            _index(out, ignore), _index(args.published, ignore), args.limit
        )
        if ignore:
            result["ignored_globs"] = list(ignore)

    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
