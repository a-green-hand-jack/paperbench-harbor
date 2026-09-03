#!/usr/bin/env python3
"""Verify and materialize a human-approved generic benchmark layout.

This is the hand-off from the read-only onboarding agent to a normal release
operator. It reruns public candidate verification, validates that a human
approved the exact candidate and layout bytes, then creates a task tree whose
structural and semantic fidelity audits must pass before reporting success.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperbench_harbor.fidelity.review import default_conversion_reviewer_model
from paperbench_harbor.onboarding.candidate import OnboardingError, parse_candidate
from paperbench_harbor.onboarding.converter import (
    OnboardedConversionConfig,
    audit_approved_benchmark,
    convert_approved_benchmark,
    determinism_approved_benchmark,
    write_approved_audit_evidence,
)
from paperbench_harbor.onboarding.layout import load_approved_layout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--layout-spec", type=Path, required=True)
    parser.add_argument("--human-approval", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--upstream-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--review-log-dir", type=Path, required=True)
    parser.add_argument("--reviewer-model", default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    verify = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "verify_benchmark_candidate.py"),
        "--candidate",
        str(args.candidate),
    ]
    if subprocess.run(verify, check=False).returncode:
        return 1
    try:
        candidate = parse_candidate(args.candidate)
        approved_layout = load_approved_layout(
            args.layout_spec,
            candidate_path=args.candidate,
            approval_path=args.human_approval,
            candidate=candidate,
        )
        config = OnboardedConversionConfig(
            source=args.source,
            output_dir=args.output,
            upstream_revision=args.upstream_revision,
            candidate=candidate,
            approved_layout=approved_layout,
            overwrite=args.overwrite,
        )
        converted = convert_approved_benchmark(config)
        reviewer_model = args.reviewer_model or default_conversion_reviewer_model()
        reports = audit_approved_benchmark(
            config,
            semantic_review=True,
            reviewer_model=reviewer_model,
            review_log_dir=args.review_log_dir,
        )
        determinism = determinism_approved_benchmark(config)
        if not determinism["determinism_ok"]:
            raise RuntimeError("approved generic conversion is not deterministic")
        write_approved_audit_evidence(
            config,
            reports,
            output=args.audit_output,
            determinism=determinism,
            reviewer_model=reviewer_model,
        )
    except (OSError, OnboardingError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Converted and semantically audited {converted} task(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
