"""Create and verify a source-only Paper-Writing Exam archive release."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from paperbench_harbor.provenance.archive import build_source_archive, verify_source_archive


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dataset-repo")
    parser.add_argument("--dataset-revision")
    parser.add_argument("--converter-revision")
    parser.add_argument("--paperwrite-source", type=Path)
    parser.add_argument("--paperwritingbench-source", type=Path)
    parser.add_argument("--lifesci-source", type=Path)
    parser.add_argument(
        "--config",
        dest="configs",
        action="append",
        help="Published dataset configuration to include. Repeat to exclude local staging residue.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify an existing archive instead of creating one.",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.verify_only:
        result = verify_source_archive(args.output_dir)
    else:
        required = (
            "release_root",
            "dataset_repo",
            "dataset_revision",
            "converter_revision",
            "paperwrite_source",
            "paperwritingbench_source",
            "lifesci_source",
        )
        missing = [name.replace("_", "-") for name in required if getattr(args, name) is None]
        if missing:
            _parser().error(f"the following arguments are required unless --verify-only: {', '.join(missing)}")
        result = build_source_archive(
            release_root=args.release_root,
            output_dir=args.output_dir,
            dataset_repo=args.dataset_repo,
            dataset_revision=args.dataset_revision,
            converter_revision=args.converter_revision,
            paperwrite_source=args.paperwrite_source,
            paperwritingbench_source=args.paperwritingbench_source,
            lifesci_source=args.lifesci_source,
            included_configs=set(args.configs) if args.configs else None,
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
