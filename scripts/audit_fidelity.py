#!/usr/bin/env python3
"""Run the task-fidelity audit for Harbor paper-writing datasets.

The audit verifies, against a fixed upstream source tree and revision, that
every generated Harbor task preserves upstream writer-visible content and
verifier-only private material, respects the task contract, and that repeated
conversion of the full dataset is deterministic. It emits one report per task
plus an overall summary.

Usage:
    uv run scripts/audit_fidelity.py paperwrite-bench \
        --source /path/to/PaperWrite-Bench \
        --dataset /path/to/paperwrite-bench-short \
        --upstream-revision <rev> \
        --overview short \
        --output reports/pwb
    uv run scripts/audit_fidelity.py paperwritingbench \
        --source /path/to/PaperWritingBench \
        --dataset /path/to/paperwritingbench-sparse-plotoff \
        --upstream-revision <rev> \
        --protocol sparse-plotoff \
        --output reports/pwbw
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from paperbench_harbor.adapters.lifesci_paperrecon.harbor import (
    BENCHMARK as LSPR_BENCHMARK,
)
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
from paperbench_harbor.fidelity.audit import summarize
from paperbench_harbor.fidelity.dataset import DatasetAuditError, audit_dataset
from paperbench_harbor.fidelity.review import default_conversion_reviewer_model
from paperbench_harbor.fidelity.transforms import sha256


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.is_dir():
        return "missing"
    for rel in sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()):
        digest.update(rel.encode())
        digest.update(sha256(root / rel).encode())
    return digest.hexdigest()


def _code_revision() -> str | None:
    """The converter source revision that produced this audit evidence."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            check=True,
            encoding="utf-8",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _run(args: argparse.Namespace, benchmark: str, protocol: str, determinism_fn) -> int:
    source_tree_sha256 = _tree_digest(args.source)
    reviewer_model = args.reviewer_model or default_conversion_reviewer_model()
    try:
        reports = audit_dataset(
            benchmark=benchmark,
            source=args.source,
            dataset=args.dataset,
            protocol=protocol,
            semantic_review=args.semantic_review,
            reviewer_model=reviewer_model,
            review_log_dir=args.output / "review-logs",
        )
    except DatasetAuditError as exc:
        raise SystemExit(str(exc)) from exc
    return _write_reports(
        args,
        reports,
        determinism_fn,
        source_tree_sha256=source_tree_sha256,
        reviewer_model=reviewer_model,
    )


def _audit_paperwrite(args: argparse.Namespace) -> int:
    return _run(args, "PaperWrite-Bench", args.overview, _determinism_paperwrite)


def _audit_lifesci_paperrecon(args: argparse.Namespace) -> int:
    """Audit the biology corpus against its generated source tree.

    The upstream root here is the corpus produced by
    `scripts/build_lifesci_paperrecon_source.py`, not a third-party dataset: this
    benchmark is built in-repo, so "fidelity" means the Harbor tasks preserve
    the pinned source corpus exactly.
    """
    return _run(args, LSPR_BENCHMARK, args.overview, _determinism_lifesci_paperrecon)


def _audit_paperwritingbench(args: argparse.Namespace) -> int:
    return _run(args, "PaperWritingBench", args.protocol, _determinism_paperwritingbench)


def _determinism_lifesci_paperrecon(args: argparse.Namespace, summary: dict) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        digests = []
        for run in ("a", "b"):
            out = scratch / run
            convert_paperwrite_bench(
                lifesci_paperrecon_conversion_config(
                    source=args.source,
                    output_dir=out,
                    upstream_revision=args.upstream_revision,
                    overview=args.overview,
                    overwrite=True,
                )
            )
            digests.append(_tree_digest(out))
        manifest_a = (scratch / "a" / "dataset-manifest.jsonl").read_bytes()
        manifest_b = (scratch / "b" / "dataset-manifest.jsonl").read_bytes()
        summary["determinism_tree_identical"] = digests[0] == digests[1]
        summary["determinism_manifest_identical"] = manifest_a == manifest_b
        summary["determinism_ok"] = (
            summary["determinism_tree_identical"] and summary["determinism_manifest_identical"]
        )


def _determinism_paperwrite(args: argparse.Namespace, summary: dict) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        digests = []
        for run in ("a", "b"):
            out = scratch / run
            convert_paperwrite_bench(
                PaperWriteBenchConversionConfig(
                    source=args.source,
                    output_dir=out,
                    overview=args.overview,
                    overwrite=True,
                    upstream_revision=args.upstream_revision,
                )
            )
            digests.append(_tree_digest(out))
        manifest_a = (scratch / "a" / "dataset-manifest.jsonl").read_bytes()
        manifest_b = (scratch / "b" / "dataset-manifest.jsonl").read_bytes()
        summary["determinism_tree_identical"] = digests[0] == digests[1]
        summary["determinism_manifest_identical"] = manifest_a == manifest_b
        summary["determinism_ok"] = (
            summary["determinism_tree_identical"] and summary["determinism_manifest_identical"]
        )


def _determinism_paperwritingbench(args: argparse.Namespace, summary: dict) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        digests = []
        for run in ("a", "b"):
            out = scratch / run
            convert_paperwritingbench(
                PaperWritingBenchConversionConfig(
                    source=args.source,
                    output_dir=out,
                    protocol=args.protocol,
                    overwrite=True,
                    upstream_revision=args.upstream_revision,
                )
            )
            digests.append(_tree_digest(out))
        manifest_a = (scratch / "a" / "dataset-manifest.jsonl").read_bytes()
        manifest_b = (scratch / "b" / "dataset-manifest.jsonl").read_bytes()
        summary["determinism_tree_identical"] = digests[0] == digests[1]
        summary["determinism_manifest_identical"] = manifest_a == manifest_b
        summary["determinism_ok"] = (
            summary["determinism_tree_identical"] and summary["determinism_manifest_identical"]
        )


def _write_reports(
    args: argparse.Namespace,
    reports,
    determinism_fn,
    *,
    source_tree_sha256: str | None = None,
    reviewer_model: str | None = None,
) -> int:
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(reports)
    determinism_fn(args, summary)
    final_source_tree_sha256 = _tree_digest(args.source)
    if source_tree_sha256 is not None and final_source_tree_sha256 != source_tree_sha256:
        raise RuntimeError(
            "source tree changed during fidelity audit; discard the generated evidence and retry "
            "from an immutable input snapshot"
        )
    for report in reports:
        (output_dir / f"{report.task_id}.json").write_text(
            json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8"
        )
    summary["evidence"] = {
        "schema_version": 1,
        "benchmark": reports[0].benchmark if reports else None,
        "upstream_revision": args.upstream_revision,
        "upstream_tree_sha256": source_tree_sha256 or final_source_tree_sha256,
        "dataset_tree_sha256": _tree_digest(args.dataset),
        "converter_revision": _code_revision(),
        "semantic_review_required": args.semantic_review,
        "reviewer_model": reviewer_model,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: summary[key]
                for key in (
                    "total_tasks",
                    "passed_tasks",
                    "failed_tasks",
                    "determinism_ok",
                    "semantic_reviews",
                    "semantic_review_failures",
                )
            }
        )
    )
    return 0 if summary["failed_tasks"] == 0 and summary.get("determinism_ok") else 1


def _add_semantic_review_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--semantic-review",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="run the isolated semantic reviewer after deterministic audit checks",
    )
    parser.add_argument(
        "--reviewer-model",
        help="override the isolated semantic reviewer model",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    pwb = sub.add_parser("paperwrite-bench", help="Audit PaperWrite-Bench dataset")
    pwb.add_argument("--source", type=Path, required=True, help="upstream PaperWrite-Bench root")
    pwb.add_argument("--dataset", type=Path, required=True, help="Harbor dataset root")
    pwb.add_argument("--upstream-revision", required=True, help="pinned upstream revision")
    pwb.add_argument("--overview", default="short", choices=["short", "long"])
    pwb.add_argument("--output", type=Path, required=True, help="report output directory")
    _add_semantic_review_options(pwb)
    pwb.set_defaults(func=_audit_paperwrite)

    bio = sub.add_parser(
        "lifesci-paperrecon", help="Audit LifeSci-PaperRecon dataset"
    )
    bio.add_argument("--source", type=Path, required=True, help="generated bio source corpus root")
    bio.add_argument("--dataset", type=Path, required=True, help="Harbor dataset root")
    bio.add_argument(
        "--upstream-revision", required=True, help="pinned construction-pipeline revision"
    )
    bio.add_argument("--overview", default="short", choices=["short", "long"])
    bio.add_argument("--output", type=Path, required=True, help="report output directory")
    _add_semantic_review_options(bio)
    bio.set_defaults(func=_audit_lifesci_paperrecon)

    pwbw = sub.add_parser("paperwritingbench", help="Audit PaperWritingBench dataset")
    pwbw.add_argument("--source", type=Path, required=True, help="upstream PaperWritingBench root")
    pwbw.add_argument("--dataset", type=Path, required=True, help="Harbor dataset root")
    pwbw.add_argument("--upstream-revision", required=True, help="pinned upstream revision")
    pwbw.add_argument("--protocol", default="sparse-plotoff", choices=["sparse-plotoff"])
    pwbw.add_argument("--output", type=Path, required=True, help="report output directory")
    _add_semantic_review_options(pwbw)
    pwbw.set_defaults(func=_audit_paperwritingbench)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
