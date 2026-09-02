#!/usr/bin/env python3
"""Canonicalise a proposed paper-writing benchmark before human review.

The restricted ``benchmark-onboard`` agent may discover a benchmark and write a
proposal only in its isolated scratch area. This program makes that output a
strict ``benchmark_candidate.json`` hand-off; it never promotes a benchmark or
writes a layout into the repository.

Usage:
    uv run scripts/screen_benchmark_candidate.py \
      --proposal /scratch/proposal.json --output /scratch/benchmark_candidate.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperbench_harbor.construction.core.opencode_agent import (
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    ScratchLocationError,
    check_opencode_available,
    prepare_scratch,
    run_agent_session,
)
from paperbench_harbor.onboarding.candidate import (
    BenchmarkCandidate,
    OnboardingError,
    parse_candidate,
    write_candidate,
)


def template() -> dict[str, object]:
    """The exact shape an isolated screening session must substantiate."""

    return {
        "benchmark_id": "lowercase-stable-id",
        "source_repository": "https://github.com/owner/repository",
        "source_revision": "40-character immutable Git commit SHA",
        "source_license": "repository license verified from the GitHub API",
        "dataset_manifest_url": (
            "https://raw.githubusercontent.com/owner/repository/40-character-commit/samples.json"
        ),
        "dataset_manifest_sha256": "SHA-256 of the exact manifest bytes",
        "benchmark_license": "license permitting the task materials",
        "sample_count": 1,
        "writer_deliverable": True,
        "requires_experiments": False,
        "requires_code": False,
        "input_protocol": "prepared materials given to a writing agent",
        "evaluator": "official evaluator and immutable version",
        "selection_record_url": "https://github.com/a-green-hand-jack/paperbench-harbor/issues/2",
        "rationale": "Evidence that the official benchmark is a fixed public writing benchmark.",
    }


def _summary(candidate: BenchmarkCandidate) -> dict[str, object]:
    return {
        "benchmark_id": candidate.benchmark_id,
        "source_revision": candidate.source_revision,
        "sample_count": candidate.sample_count,
        "writer_deliverable": candidate.writer_deliverable,
        "requires_experiments": candidate.requires_experiments,
        "requires_code": candidate.requires_code,
        "selection_record_url": candidate.selection_record_url,
    }


def build_prompt(request: str, output_path: Path) -> str:
    """Prompt an isolated session to propose one candidate, never a layout."""

    return f"""\
You are screening one public benchmark candidate for Harbor. The user request is:

{request}

Find a candidate only if it is a fixed public benchmark whose graded deliverable
is a scientific manuscript produced from prepared materials. Reject candidates
that require the agent to run experiments or write code. Read facts from the
live source rather than memory. This is a proposal, not permission to build,
modify a repository, or promote anything.

Write exactly one JSON object to `{output_path}` with these exact keys and no
others:

```json
{json.dumps(template(), indent=2)}
```

`source_revision` must be the complete Git commit SHA. `source_license` must
match the GitHub repository API. The public sample-manifest URL must be an
immutable or content-addressed JSON list (or object containing `samples` or
`tasks`) and its SHA-256/count must match your claims. `selection_record_url`
must point to the human selection record in issue #2. Do not create a layout
spec and do not write anywhere except this output file.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--proposal", type=Path, help="Agent-produced candidate JSON in scratch.")
    source.add_argument("--request", help="Free-text request for an isolated screening session.")
    parser.add_argument("--output", type=Path, help="Canonical benchmark_candidate.json.")
    parser.add_argument("--scratch-root", type=Path, default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--log-dir", type=Path, default=None)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--print-template",
        action="store_true",
        help="Print the exact proposal shape and exit without writing files.",
    )
    args = parser.parse_args()

    if args.print_template:
        print(json.dumps(template(), indent=2) + "\n")
        return 0
    if (args.proposal is None and args.request is None) or args.output is None:
        parser.error("one of --proposal/--request and --output are required")

    proposal = args.proposal
    if args.request is not None:
        if args.scratch_root is None:
            parser.error("--scratch-root is required with --request")
        try:
            workspace = prepare_scratch(args.scratch_root, "benchmark-screening")
            proposal = workspace / "benchmark_candidate.proposal.json"
            prompt = build_prompt(args.request, proposal)
            if args.dry_run:
                print(prompt)
                return 0
            check_opencode_available(args.model)
            run = run_agent_session(
                paper_id="benchmark-screening",
                prompt=prompt,
                workspace=workspace,
                log_dir=args.log_dir or args.scratch_root / "_logs",
                model=args.model,
                timeout=args.timeout,
            )
            if not run.ok:
                print(f"ERROR: screening session failed; inspect {run.log_path}", file=sys.stderr)
                return 1
        except ScratchLocationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1

    try:
        candidate = parse_candidate(proposal)
        write_candidate(args.output, candidate)
    except OnboardingError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(_summary(candidate), sort_keys=True))
    print(f"candidate proposal -> {args.output}")
    print("Human review is still required before any layout spec is promoted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
