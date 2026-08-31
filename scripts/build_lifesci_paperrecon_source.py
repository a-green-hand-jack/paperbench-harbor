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
from paperbench_harbor.construction.core.spec import PaperSpec
from paperbench_harbor.construction.lifesci_paperrecon.papers import (
    PILOT_BY_ID,
    PILOT_PAPERS,
)
from paperbench_harbor.construction.lifesci_paperrecon.plugin import LIFESCI_PLUGIN


def _log(message: str) -> None:
    print(message, flush=True)


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
    parser.add_argument("--papers", nargs="*", default=None, help="Paper ids (default: all pilot papers).")
    parser.add_argument("--model", default=DEFAULT_MODEL)
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
    if args.papers:
        unknown = [name for name in args.papers if name not in PILOT_BY_ID]
        if unknown:
            parser.error(f"unknown paper id(s): {', '.join(unknown)}")
        specs = [PILOT_BY_ID[name] for name in args.papers]
    else:
        specs = list(PILOT_PAPERS)

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
        log=_log,
    )

    summary = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": args.model,
        "corpus_root": str(corpus_root),
        "scratch_root": str(scratch_root),
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
