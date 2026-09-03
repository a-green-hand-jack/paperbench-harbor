"""Run the auditable PaperSmith workflow for one new PaperRecon domain.

Without ``--candidates`` this is the LKM-first discovery and OpenCode screening
stage.  With a SHA-bound ``--human-approval`` and the promotion/build flags it
continues through the deterministic construction and conversion gates.  It
never creates approval records and never uploads a public release.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperbench_harbor.adapters.paperrecon import paperrecon_conversion_config
from paperbench_harbor.adapters.paperwrite_bench.converter import convert_paperwrite_bench
from paperbench_harbor.construction.core.literature import discover_literature
from paperbench_harbor.construction.core.opencode_agent import (
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    check_opencode_available,
)
from paperbench_harbor.construction.core.pipeline import build_corpus
from paperbench_harbor.construction.core.review import default_reviewer_model
from paperbench_harbor.construction.core.screen import Candidate, ScreeningError, run_screening
from paperbench_harbor.construction.domains import get_domain
from paperbench_harbor.fidelity.dataset import DatasetAuditError
from paperbench_harbor.provenance.archive import build_source_archive
from scripts.promote_lifesci_paperrecon_candidates import (
    PromotionError,
    promote,
    read_candidates,
    read_human_approval,
)


def _summary(candidates: list[Candidate]) -> dict[str, object]:
    return {
        "count": len(candidates),
        "by_category": dict(sorted(Counter(item.expected_category for item in candidates).items())),
        "by_type": dict(sorted(Counter(item.paper_type for item in candidates).items())),
        "by_code_status": dict(sorted(Counter(item.code_status for item in candidates).items())),
    }


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _queries(domain: str, guidance: str) -> tuple[str, ...]:
    base = (
        f"{domain} research papers with public arXiv LaTeX source and reconstructable figures",
        f"{domain} papers public source materials reproducible analysis or theoretical derivation",
        f"{domain} paper reconstruction public figures tables bibliography",
    )
    return base + ((guidance,) if guidance else ())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", choices=("physics", "chemistry", "mathematics"), required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--target-count", type=int, default=20)
    parser.add_argument("--extra-guidance", default="")
    parser.add_argument("--lkm-default", action="store_true", default=True)
    parser.add_argument("--no-lkm", dest="lkm_default", action="store_false")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--reviewer-model", default=None)
    parser.add_argument("--max-turns", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--human-approval", type=Path)
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--convert", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--stage-candidate", action="store_true")
    return parser


def _screen(args: argparse.Namespace) -> int:
    domain = get_domain(args.domain)
    run_root = args.run_root.resolve()
    if args.target_count < 20:
        raise ValueError("--target-count must be at least 20 for a new-domain candidate release")
    discovery_context = ""
    discovery_path = run_root / "discovery.json"
    if args.lkm_default:
        snapshot = discover_literature(_queries(domain.name, args.extra_guidance))
        snapshot.write(discovery_path)
        discovery_context = snapshot.prompt_context()
    check_opencode_available(args.model)
    candidates = run_screening(
        domain.screening_policy,
        build_root=run_root / "screening-workspace",
        seed_candidates=domain.seed_candidates,
        target_count=args.target_count,
        exclude_ids=domain.exclude_ids,
        extra_guidance=args.extra_guidance,
        discovery_context=discovery_context,
        model=args.model,
        log_dir=run_root / "logs",
        timeout=args.timeout,
    )
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "domain": domain.name,
        "target_count": args.target_count,
        "lkm_discovery": str(discovery_path) if args.lkm_default else None,
        "summary": _summary(candidates),
        "candidates": [candidate.as_dict() for candidate in candidates],
    }
    output = run_root / "candidates.json"
    _write(output, payload)
    print(f"candidate proposal -> {output}")
    return 0 if len(candidates) >= args.target_count else 2


def _promote_and_build(args: argparse.Namespace) -> int:
    domain = get_domain(args.domain)
    if not all((args.candidates, args.human_approval, args.promote, args.build, args.convert, args.audit)):
        raise ValueError(
            "promotion requires --candidates --human-approval --promote --build --convert --audit"
        )
    candidates_path = args.candidates.resolve()
    candidates = read_candidates(
        candidates_path, policy=domain.screening_policy, exclude_ids=domain.exclude_ids
    )
    approval = read_human_approval(
        args.human_approval.resolve(), candidates_path=candidates_path, candidates=candidates
    )
    _outcomes, promoted, promotion_summary = promote(
        candidates,
        approved_file=args.run_root.resolve() / "approved_scaleup.jsonl",
        promote_now=True,
        limit=None,
        approved_arxiv_ids=approval.approved_arxiv_ids,
        human_reviewer=approval.reviewer,
        existing_specs=domain.approved_papers,
    )
    specs = [*domain.approved_papers, *promoted]
    if len(specs) < 20:
        raise ValueError(f"only {len(specs)} approved papers; a candidate release needs at least 20")
    check_opencode_available(args.model)
    run_root = args.run_root.resolve()
    corpus_root = run_root / "corpus"
    outcomes_build = build_corpus(
        specs,
        domain.plugin,
        scratch_root=run_root / "scratch",
        corpus_root=corpus_root,
        build_root=run_root / "build",
        log_dir=run_root / "logs",
        concurrency=args.concurrency,
        model=args.model,
        max_turns=args.max_turns,
        timeout=args.timeout,
        fresh=True,
        reviewer_model=args.reviewer_model or default_reviewer_model(),
    )
    failed = [item for item in outcomes_build if item["status"] != "ok"]
    if failed:
        _write(run_root / "run-summary.json", {"promotion": promotion_summary, "build": outcomes_build})
        return 1
    output_dir = run_root / "dataset" / domain.benchmark_config
    revision = __import__("subprocess").check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()
    converted = convert_paperwrite_bench(
        paperrecon_conversion_config(
            domain.name,
            source=corpus_root,
            output_dir=output_dir,
            upstream_revision=revision,
            overview="short",
            overwrite=True,
        )
    )
    audit_result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "audit_fidelity.py"),
            "paperrecon",
            "--domain",
            domain.name,
            "--source",
            str(corpus_root),
            "--dataset",
            str(output_dir),
            "--upstream-revision",
            revision,
            "--overview",
            "short",
            "--output",
            str(run_root / "reports" / "fidelity"),
        ],
        cwd=REPO_ROOT,
        check=False,
    )
    if audit_result.returncode:
        return audit_result.returncode
    source_archive = None
    if args.stage_candidate:
        source_archive_dir = run_root / "source-archive"
        build_source_archive(
            release_root=run_root / "dataset",
            output_dir=source_archive_dir,
            dataset_repo=f"candidate/{domain.benchmark_config}",
            dataset_revision=revision,
            converter_revision=revision,
            paperwrite_source=corpus_root,
            paperwritingbench_source=corpus_root,
            lifesci_source=corpus_root,
            paperrecon_sources={domain.name: corpus_root},
            included_configs={domain.benchmark_config},
        )
        source_archive = str(source_archive_dir)
    result = {
        "promotion": promotion_summary,
        "approval_sha256": approval.candidate_sha256,
        "built_tasks": len(outcomes_build),
        "converted_tasks": converted,
        "dataset": str(output_dir),
        "candidate_stage": bool(args.stage_candidate),
        "source_archive": source_archive,
    }
    _write(run_root / "run-summary.json", result)
    print(f"candidate corpus passed -> {run_root}")
    return 0


def main() -> int:
    args = _parser().parse_args()
    try:
        return _promote_and_build(args) if args.candidates else _screen(args)
    except (ValueError, PromotionError, ScreeningError, DatasetAuditError) as error:
        print(f"ERROR: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
