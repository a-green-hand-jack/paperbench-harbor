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

Requires: the `opencode` CLI with a configured provider, and a `pdflatex` /
`bibtex` matching the Harbor verifier's TeX Live. Both live on the build host,
not necessarily on a developer's laptop.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperbench_harbor.construction.lifesci_paperrecon.opencode_agent import (
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    AgentRun,
    check_opencode_available,
    prepare_scratch,
    run_construction,
    tail_log,
)
from paperbench_harbor.construction.lifesci_paperrecon.papers import (
    PILOT_BY_ID,
    PILOT_PAPERS,
    PaperSpec,
)
from paperbench_harbor.construction.lifesci_paperrecon.prompt import (
    build_prompt,
    build_retry_prompt,
)
from paperbench_harbor.construction.lifesci_paperrecon.validate import (
    ValidationReport,
    validate_paper,
)


def _log(message: str) -> None:
    print(message, flush=True)


def _blocked_reason(workspace: Path) -> str:
    """Read the agent's own stop-condition report, if it wrote one.

    The prompt tells the agent to refuse rather than substitute when a paper no
    longer qualifies. That refusal has to surface as a distinct outcome, not as
    a generic validation failure, because the two need different human
    responses: one is a re-selection decision, the other is a retry.
    """

    provenance = workspace / "original" / "provenance.json"
    if not provenance.is_file():
        return ""
    try:
        record = json.loads(provenance.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    if isinstance(record, dict):
        return str(record.get("blocked", "")).strip()
    return ""


def build_paper(
    spec: PaperSpec,
    *,
    scratch_root: Path,
    corpus_root: Path,
    build_root: Path,
    log_dir: Path,
    model: str,
    max_turns: int,
    timeout: int,
    fresh: bool,
    dry_run: bool,
    validate_only: bool,
) -> dict:
    """Run the agent/validate loop for one paper and return its outcome record."""

    workspace = prepare_scratch(scratch_root, spec.paper_id, fresh=fresh)
    runs: list[AgentRun] = []
    report: ValidationReport | None = None

    for turn in range(1, max_turns + 1):
        if not validate_only:
            if turn == 1:
                prompt = build_prompt(spec, str(workspace))
            else:
                assert report is not None
                prompt = build_retry_prompt(spec, report, str(workspace))
            _log(f"  turn {turn}: opencode run ({model})")
            run = run_construction(
                paper_id=spec.paper_id,
                prompt=prompt,
                workspace=workspace,
                log_dir=log_dir,
                model=model,
                turn=turn,
                continue_session=turn > 1,
                timeout=timeout,
                dry_run=dry_run,
            )
            runs.append(run)
            if not run.ok:
                _log(f"  turn {turn}: agent exited {run.returncode} (timed_out={run.timed_out})")
                _log("  --- agent log tail ---")
                _log(tail_log(run))
            if dry_run:
                return {
                    "paper_id": spec.paper_id,
                    "status": "dry-run",
                    "workspace": str(workspace),
                    "runs": [asdict(run) | {"log_path": str(run.log_path)} for run in runs],
                }

        blocked = _blocked_reason(workspace)
        if blocked:
            _log(f"  BLOCKED: {blocked}")
            return {
                "paper_id": spec.paper_id,
                "status": "blocked",
                "reason": blocked,
                "workspace": str(workspace),
                "runs": [asdict(run) | {"log_path": str(run.log_path)} for run in runs],
            }

        _log(f"  turn {turn}: validating")
        report = validate_paper(
            workspace, spec, build_root=build_root / spec.paper_id
        )
        _log("  " + report.summary().replace("\n", "\n  "))
        if report.ok:
            break
        if validate_only:
            break

    assert report is not None
    outcome = {
        "paper_id": spec.paper_id,
        "status": "ok" if report.ok else "failed",
        "workspace": str(workspace),
        "turns": len(runs),
        "issues": [asdict(issue) for issue in report.issues],
        "compiles": [
            {"tex_name": result.tex_name, "ok": result.ok} for result in report.compiles
        ],
        "runs": [asdict(run) | {"log_path": str(run.log_path)} for run in runs],
    }

    if report.ok:
        destination = corpus_root / spec.paper_id
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # `.git` would carry the code repo's full history into every Harbor
        # task's build context; the checked-out tree plus a recorded commit is
        # what provenance needs.
        shutil.copytree(
            workspace,
            destination,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".opencode"),
        )
        outcome["corpus_dir"] = str(destination)
        _log(f"  admitted -> {destination}")
    else:
        _log("  NOT admitted to the corpus")

    return outcome


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
    parser.add_argument("--fresh", action="store_true", help="Discard existing scratch workspaces first.")
    parser.add_argument("--dry-run", action="store_true", help="Print the commands without running the agent.")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Re-run the gate against existing workspaces without invoking the agent.",
    )
    parser.add_argument("--report", type=Path, default=None, help="Write the run summary here as JSON.")
    args = parser.parse_args()

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

    outcomes: list[dict] = []
    for spec in specs:
        _log(f"{spec.paper_id}: arXiv {spec.arxiv_id}{spec.expected_version} ({spec.paper_type})")
        outcomes.append(
            build_paper(
                spec,
                scratch_root=scratch_root,
                corpus_root=corpus_root,
                build_root=build_root,
                log_dir=log_dir,
                model=args.model,
                max_turns=args.max_turns,
                timeout=args.timeout,
                fresh=args.fresh,
                dry_run=args.dry_run,
                validate_only=args.validate_only,
            )
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
