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
from paperbench_harbor.fidelity.audit import run_fidelity_audit, summarize
from paperbench_harbor.fidelity.transforms import sha256


def _load_manifest(dataset: Path) -> list[dict]:
    manifest = dataset / "dataset-manifest.jsonl"
    if not manifest.is_file():
        raise SystemExit(f"dataset manifest not found: {manifest}")
    entries = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.is_dir():
        return "missing"
    for rel in sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()):
        digest.update(rel.encode())
        digest.update(sha256(root / rel).encode())
    return digest.hexdigest()


def _audit_paperwrite(args: argparse.Namespace) -> int:
    entries = _load_manifest(args.dataset)
    reports = []
    for entry in entries:
        task_id = entry["task_id"]
        upstream_paper_id = entry["upstream_paper_id"]
        task_dir = args.dataset / task_id
        if not task_dir.is_dir():
            raise SystemExit(f"task dir missing: {task_dir}")
        report = run_fidelity_audit(
            benchmark="PaperWrite-Bench",
            task_id=task_id,
            upstream_paper_id=upstream_paper_id,
            upstream_root=args.source,
            task_dir=task_dir,
            protocol=args.overview,
            venue=None,
        )
        reports.append(report)
    return _write_reports(args, reports, _determinism_paperwrite)


def _audit_lifesci_paperrecon(args: argparse.Namespace) -> int:
    """Audit the biology corpus against its generated source tree.

    The upstream root here is the corpus produced by
    `scripts/build_lifesci_paperrecon_source.py`, not a third-party dataset: this
    benchmark is built in-repo, so "fidelity" means the Harbor tasks preserve
    the pinned source corpus exactly.
    """
    entries = _load_manifest(args.dataset)
    reports = []
    for entry in entries:
        task_id = entry["task_id"]
        upstream_paper_id = entry["upstream_paper_id"]
        task_dir = args.dataset / task_id
        if not task_dir.is_dir():
            raise SystemExit(f"task dir missing: {task_dir}")
        reports.append(
            run_fidelity_audit(
                benchmark=LSPR_BENCHMARK,
                task_id=task_id,
                upstream_paper_id=upstream_paper_id,
                upstream_root=args.source,
                task_dir=task_dir,
                protocol=args.overview,
                venue=None,
            )
        )
    return _write_reports(args, reports, _determinism_lifesci_paperrecon)


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


def _audit_paperwritingbench(args: argparse.Namespace) -> int:
    entries = _load_manifest(args.dataset)
    reports = []
    for entry in entries:
        task_id = entry["task_id"]
        upstream_paper_id = entry["upstream_paper_id"]
        venue = entry.get("venue")
        task_dir = args.dataset / task_id
        if not task_dir.is_dir():
            raise SystemExit(f"task dir missing: {task_dir}")
        report = run_fidelity_audit(
            benchmark="PaperWritingBench",
            task_id=task_id,
            upstream_paper_id=upstream_paper_id,
            upstream_root=args.source,
            task_dir=task_dir,
            protocol=args.protocol,
            venue=venue,
        )
        reports.append(report)
    return _write_reports(args, reports, _determinism_paperwritingbench)


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


def _write_reports(args: argparse.Namespace, reports, determinism_fn) -> int:
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    for report in reports:
        (output_dir / f"{report.task_id}.json").write_text(
            json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8"
        )
    summary = summarize(reports)
    determinism_fn(args, summary)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: summary[k] for k in ("total_tasks", "passed_tasks", "failed_tasks", "determinism_ok")}))
    return 0 if summary["failed_tasks"] == 0 and summary.get("determinism_ok") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    pwb = sub.add_parser("paperwrite-bench", help="Audit PaperWrite-Bench dataset")
    pwb.add_argument("--source", type=Path, required=True, help="upstream PaperWrite-Bench root")
    pwb.add_argument("--dataset", type=Path, required=True, help="Harbor dataset root")
    pwb.add_argument("--upstream-revision", required=True, help="pinned upstream revision")
    pwb.add_argument("--overview", default="short", choices=["short", "long"])
    pwb.add_argument("--output", type=Path, required=True, help="report output directory")
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
    bio.set_defaults(func=_audit_lifesci_paperrecon)

    pwbw = sub.add_parser("paperwritingbench", help="Audit PaperWritingBench dataset")
    pwbw.add_argument("--source", type=Path, required=True, help="upstream PaperWritingBench root")
    pwbw.add_argument("--dataset", type=Path, required=True, help="Harbor dataset root")
    pwbw.add_argument("--upstream-revision", required=True, help="pinned upstream revision")
    pwbw.add_argument("--protocol", default="sparse-plotoff", choices=["sparse-plotoff"])
    pwbw.add_argument("--output", type=Path, required=True, help="report output directory")
    pwbw.set_defaults(func=_audit_paperwritingbench)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
