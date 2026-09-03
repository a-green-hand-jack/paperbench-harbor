"""Independently verify and human-promote one non-LifeSci PaperRecon proposal."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperbench_harbor.construction.domains import get_domain
from scripts.promote_lifesci_paperrecon_candidates import (
    PromotionError,
    _report,
    promote,
    read_candidates,
    read_human_approval,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", choices=("physics", "chemistry", "mathematics"), required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--approved-file", type=Path, required=True)
    parser.add_argument("--human-approval", type=Path, required=True)
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--minimum-approved", type=int, default=20)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.minimum_approved < 1:
        parser.error("--minimum-approved must be >= 1")
    domain = get_domain(args.domain)
    try:
        candidates = read_candidates(
            args.candidates, policy=domain.screening_policy, exclude_ids=domain.exclude_ids
        )
        approval = read_human_approval(
            args.human_approval,
            candidates_path=args.candidates,
            candidates=candidates,
        )
        outcomes, written, summary = promote(
            candidates,
            approved_file=args.approved_file,
            promote_now=args.promote,
            limit=None,
            approved_arxiv_ids=approval.approved_arxiv_ids,
            human_reviewer=approval.reviewer,
            existing_specs=domain.approved_papers,
        )
    except (PromotionError, ValueError) as error:
        print(f"cannot promote: {error}")
        return 1
    _report(outcomes, summary, dry_run=not args.promote)
    summary["domain"] = domain.name
    summary["candidate_sha256"] = approval.candidate_sha256
    summary["approved_arxiv_ids"] = sorted(approval.approved_arxiv_ids)
    summary["minimum_approved"] = args.minimum_approved
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    approved_now = len(written) + len(domain.approved_papers)
    if args.promote and approved_now < args.minimum_approved:
        print(
            f"only {approved_now} approved {domain.name} paper(s); "
            f"need at least {args.minimum_approved} before construction"
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
