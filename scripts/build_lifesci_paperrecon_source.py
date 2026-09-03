#!/usr/bin/env python3
"""Build the LifeSci-PaperRecon source corpus, one opencode session per paper.

    build_lifesci_paperrecon_source.py \\
        --scratch-root /home/user/lifesci-paperrecon-scratch \\
        --corpus-root  .cache/lifesci-paperrecon/corpus

Per paper the loop is: run the agent, run the deterministic gate, and on
failure hand the gate's own findings back to the same agent session for another
turn. A paper is copied into the corpus only after it passes; a paper that
never passes is reported, never patched into shape here. That split is the
whole point of the design — see
`src/paperbench_harbor/construction/lifesci_paperrecon/__init__.py`.

The loop itself is domain-agnostic and lives in
`paperbench_harbor.construction.core.pipeline`; this script is the
life-sciences entry point into it, supplying the approved pilot papers and
`LIFESCI_PLUGIN`. A future domain's build script is this file with two imports
changed — see `docs/papersmith-architecture.md`.

Requires: the `opencode` CLI with a configured provider, and a `pdflatex` /
`bibtex` matching the Harbor verifier's TeX Live. Both live on the build host,
not necessarily on a developer's laptop.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperbench_harbor.construction.core.opencode_agent import (
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    check_opencode_available,
)
from paperbench_harbor.construction.core.pipeline import build_corpus
from paperbench_harbor.construction.core.review import default_reviewer_model
from paperbench_harbor.construction.core.spec import PaperSpec
from paperbench_harbor.construction.lifesci_paperrecon.papers import (
    APPROVED_BY_ID,
    APPROVED_PAPERS,
)
from paperbench_harbor.construction.lifesci_paperrecon.plugin import LIFESCI_PLUGIN


def _log(message: str) -> None:
    print(message, flush=True)


def _published_paper_ids(manifest_path: Path) -> list[str]:
    """Read published upstream ids in task order from a dataset manifest."""

    if not manifest_path.is_file():
        raise ValueError(f"published manifest does not exist: {manifest_path}")
    paper_ids: list[str] = []
    seen: set[str] = set()
    for line_number, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"published manifest {manifest_path}:{line_number} is invalid JSON: {error.msg}"
            ) from error
        paper_id = record.get("upstream_paper_id") if isinstance(record, dict) else None
        if not isinstance(paper_id, str) or not paper_id:
            raise ValueError(
                f"published manifest {manifest_path}:{line_number} has no upstream_paper_id"
            )
        if paper_id in seen:
            raise ValueError(
                f"published manifest {manifest_path}:{line_number} repeats {paper_id!r}"
            )
        seen.add(paper_id)
        paper_ids.append(paper_id)
    if not paper_ids:
        raise ValueError(f"published manifest has no task records: {manifest_path}")
    return paper_ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--scratch-root",
        type=Path,
        required=True,
        help="Isolated agent workspaces. Must be outside any git working tree.",
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        required=True,
        help="Where validated papers land, in the layout the converter reads.",
    )
    parser.add_argument("--build-root", type=Path, default=None, help="Scratch for compile checks.")
    parser.add_argument("--log-dir", type=Path, default=None, help="Agent transcripts.")
    parser.add_argument("--papers", nargs="*", default=None, help="Paper ids (default: all approved papers).")
    parser.add_argument(
        "--published-manifest",
        type=Path,
        default=None,
        help=(
            "Dataset-manifest.jsonl whose upstream_paper_id values select exactly the "
            "currently published tasks; mutually exclusive with --papers."
        ),
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--reviewer-model",
        default=None,
        help=(
            "Model for the stage-3 reconstructability review. Must not be the "
            "construction model: a model grading its own output ratifies its own "
            "misreadings. Falls back to $REVIEWER_MODEL, then "
            f"{default_reviewer_model()!r}."
        ),
    )
    parser.add_argument(
        "--skip-review",
        action="store_true",
        help=(
            "Skip stage 3. For cheap structural iteration only: a paper admitted "
            "with this flag was never checked for semantic faithfulness."
        ),
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=3,
        help="Agent turns per paper, including retries driven by the validation gate.",
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="Per-turn seconds.")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help=(
            "Papers to build at once, each in its own scratch workspace and agent "
            "session. Default 1; the real ceiling is the model gateway's rate limit."
        ),
    )
    parser.add_argument("--fresh", action="store_true", help="Discard existing scratch workspaces first.")
    parser.add_argument("--dry-run", action="store_true", help="Print the commands without running the agent.")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Re-run the gate against existing workspaces without invoking the agent.",
    )
    parser.add_argument("--report", type=Path, default=None, help="Write the run summary here as JSON.")
    args = parser.parse_args()

    if args.concurrency < 1:
        parser.error("--concurrency must be >= 1")

    specs: list[PaperSpec]
    if args.papers and args.published_manifest:
        parser.error("--papers and --published-manifest cannot be used together")
    if args.published_manifest:
        try:
            paper_ids = _published_paper_ids(args.published_manifest)
        except ValueError as error:
            parser.error(str(error))
        unknown = [name for name in paper_ids if name not in APPROVED_BY_ID]
        if unknown:
            parser.error("published manifest has unknown paper id(s): " + ", ".join(unknown))
        specs = [APPROVED_BY_ID[name] for name in paper_ids]
    elif args.papers:
        unknown = [name for name in args.papers if name not in APPROVED_BY_ID]
        if unknown:
            parser.error(f"unknown paper id(s): {', '.join(unknown)}")
        specs = [APPROVED_BY_ID[name] for name in args.papers]
    else:
        specs = list(APPROVED_PAPERS)

    scratch_root = args.scratch_root.resolve()
    corpus_root = args.corpus_root.resolve()
    build_root = (args.build_root or scratch_root / "_build").resolve()
    log_dir = (args.log_dir or scratch_root / "_logs").resolve()

    if not args.dry_run and not args.validate_only:
        check_opencode_available(args.model)

    outcomes = build_corpus(
        specs,
        LIFESCI_PLUGIN,
        scratch_root=scratch_root,
        corpus_root=corpus_root,
        build_root=build_root,
        log_dir=log_dir,
        concurrency=args.concurrency,
        model=args.model,
        max_turns=args.max_turns,
        timeout=args.timeout,
        fresh=args.fresh,
        dry_run=args.dry_run,
        validate_only=args.validate_only,
        skip_review=args.skip_review,
        reviewer_model=args.reviewer_model,
        log=_log,
    )

    summary = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": args.model,
        "reviewer_model": (
            None if args.skip_review else (args.reviewer_model or default_reviewer_model())
        ),
        "corpus_root": str(corpus_root),
        "scratch_root": str(scratch_root),
        "published_manifest": str(args.published_manifest) if args.published_manifest else None,
        "papers": outcomes,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        _log(f"report -> {args.report}")

    _log("")
    for outcome in outcomes:
        _log(f"{outcome['paper_id']}: {outcome['status']}")

    failed = [outcome for outcome in outcomes if outcome["status"] not in {"ok", "dry-run"}]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
