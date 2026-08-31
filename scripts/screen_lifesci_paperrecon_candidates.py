#!/usr/bin/env python3
"""Screen candidate papers for LifeSci-PaperRecon (PaperSmith stage 1).

    screen_lifesci_paperrecon_candidates.py \\
        --build-root /home/user/lifesci-paperrecon-scratch/_screening \\
        --target-count 35 \\
        --output .cache/lifesci-paperrecon/candidates-lifesci.json

One `opencode` session searches arXiv's `q-bio.*` categories with real network
access and proposes papers that satisfy `LIFESCI_SCREENING_POLICY`. What comes
back is a **proposal**: this script validates its shape and its policy
compliance and writes it out, and nothing here appends to `APPROVED_PAPERS`.
Promotion stays a human edit, because the construction gate's
`provenance-mismatch` check only means something while the approved list is a
human decision the agent cannot reach — see
`src/paperbench_harbor/construction/core/screen.py`.

The screening machinery is domain-agnostic and lives in
`paperbench_harbor.construction.core.screen`; this script is the life-sciences
entry point into it, supplying `LIFESCI_SCREENING_POLICY`, the seed list and
the already-built papers to exclude. A future domain's screening script is this
file with two imports changed — the same relationship
`build_lifesci_paperrecon_source.py` has to `core.pipeline`.

Requires: the `opencode` CLI with a configured provider, and outbound network
access to the arXiv and GitHub APIs. The build host, not a laptop.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperbench_harbor.construction.core.opencode_agent import check_opencode_available
from paperbench_harbor.construction.core.screen import (
    DEFAULT_SCREENING_MODEL,
    DEFAULT_SCREENING_TIMEOUT_SECONDS,
    Candidate,
    ScreeningError,
    build_screening_prompt,
    run_screening,
)
from paperbench_harbor.construction.lifesci_paperrecon.screening import (
    LIFESCI_EXCLUDE_IDS,
    LIFESCI_SCREENING_POLICY,
    LIFESCI_SEED_CANDIDATES,
)


def _log(message: str) -> None:
    print(message, flush=True)


def summarize(candidates: list[Candidate]) -> dict:
    """Counts a human deciding what to promote actually looks at first."""

    return {
        "count": len(candidates),
        "by_category": dict(
            sorted(Counter(entry.expected_category for entry in candidates).items())
        ),
        "by_paper_license": dict(
            sorted(Counter(entry.expected_license for entry in candidates).items())
        ),
        "by_code_license": dict(
            sorted(Counter(entry.code_license for entry in candidates).items())
        ),
        "by_paper_type": dict(
            sorted(Counter(entry.paper_type for entry in candidates).items())
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--build-root",
        type=Path,
        required=True,
        help=(
            "Isolated scratch for the screening session. Must be outside any git "
            "working tree: the agent runs with --auto."
        ),
    )
    parser.add_argument(
        "--target-count",
        type=int,
        default=35,
        help=(
            "How many qualifying candidates to ask for. A short honest list is an "
            "acceptable outcome; the agent is told so."
        ),
    )
    parser.add_argument("--model", default=DEFAULT_SCREENING_MODEL)
    parser.add_argument("--log-dir", type=Path, default=None, help="Agent transcripts.")
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_SCREENING_TIMEOUT_SECONDS, help="Seconds."
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=(),
        help=(
            "Extra arXiv ids to exclude, on top of the already-built papers, which "
            "are derived from APPROVED_PAPERS rather than restated."
        ),
    )
    parser.add_argument(
        "--extra-guidance",
        default="",
        help=(
            "Free-text topical steering for this run only (e.g. 'prefer genomics/"
            "protein work with public code'). Narrows which qualifying papers are "
            "preferred; never relaxes what qualifies. Not persisted anywhere."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the validated proposal plus a summary here as JSON.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the prompt the agent would receive and exit.",
    )
    args = parser.parse_args()

    if args.target_count < 1:
        parser.error("--target-count must be >= 1")

    build_root = args.build_root.resolve()
    log_dir = (args.log_dir or build_root / "_logs").resolve()
    exclude_ids = tuple(LIFESCI_EXCLUDE_IDS) + tuple(args.exclude)

    if args.dry_run:
        print(
            build_screening_prompt(
                LIFESCI_SCREENING_POLICY,
                seed_candidates=LIFESCI_SEED_CANDIDATES,
                target_count=args.target_count,
                exclude_ids=exclude_ids,
                extra_guidance=args.extra_guidance,
                output_path=build_root / "screening-lifesci" / "candidates.json",
            )
        )
        return 0

    check_opencode_available(args.model)

    _log(
        f"screening lifesci: target {args.target_count}, "
        f"excluding {len(exclude_ids)} already-built id(s), "
        f"{len(LIFESCI_SEED_CANDIDATES)} seed(s), model {args.model}"
        + (f", guidance: {args.extra_guidance!r}" if args.extra_guidance else "")
    )

    try:
        candidates = run_screening(
            LIFESCI_SCREENING_POLICY,
            build_root=build_root,
            seed_candidates=LIFESCI_SEED_CANDIDATES,
            target_count=args.target_count,
            exclude_ids=exclude_ids,
            extra_guidance=args.extra_guidance,
            model=args.model,
            log_dir=log_dir,
            timeout=args.timeout,
        )
    except ScreeningError as error:
        _log(f"ERROR: {error}")
        return 1

    summary = summarize(candidates)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "policy": LIFESCI_SCREENING_POLICY.name,
        "model": args.model,
        "target_count": args.target_count,
        "extra_guidance": args.extra_guidance,
        "excluded_arxiv_ids": list(exclude_ids),
        "summary": summary,
        "candidates": [entry.as_dict() for entry in candidates],
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        _log(f"proposal -> {args.output}")

    _log("")
    _log(f"{summary['count']} candidate(s) proposed (target {args.target_count})")
    for label in ("by_category", "by_paper_license", "by_code_license", "by_paper_type"):
        _log(f"  {label}: {summary[label]}")
    _log("")
    _log(
        "This is a proposal. Nothing was added to APPROVED_PAPERS; promoting a "
        "candidate is a human edit to "
        "src/paperbench_harbor/construction/lifesci_paperrecon/papers.py."
    )

    # Falling short is a reportable outcome, not a crash: the caller asked for a
    # number and did not get it, and a non-zero exit is how a batch script finds
    # that out without parsing the summary.
    return 0 if summary["count"] >= args.target_count else 2


if __name__ == "__main__":
    raise SystemExit(main())
