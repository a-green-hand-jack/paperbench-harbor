"""The per-paper turn loop, and the pool that runs it over a whole corpus.

Extracted from ``scripts/build_lifesci_paperrecon_source.py`` when PaperSmith
was split into a core and per-domain plugins: the loop below never was
biology-specific, it was merely living in a biology-specific script, so every
future domain's build script would have had to copy it. Now a domain script is
argument parsing plus a plugin.

The loop is one instance of a well-understood shape — generate, check with a
deterministic evaluator, feed the counter-example back, repeat — and its two
rules are the ones that make the shape safe:

* **The gate is not negotiable.** A paper enters the corpus only after
  :func:`~.validate.validate_paper` passes it. Nothing here patches an agent's
  output into shape; a paper that never passes is reported as failed.
* **A refusal is not a failure.** The prompt tells the agent to stop rather
  than substitute when a paper no longer qualifies. That refusal surfaces as a
  distinct ``blocked`` outcome, because the two need different human responses:
  one is a re-selection decision, the other is a retry.

:func:`build_corpus` runs :func:`build_paper` per spec in a thread pool. Threads
rather than processes because every expensive thing here waits on something
else — the agent's API calls, ``pdflatex``, a git checkout — and each paper
already owns a separate scratch workspace, so the workers share no mutable
state. ``concurrency=1`` stays the default: the ceiling that matters is the
model gateway's rate limit, which is a property of the deployment, not of this
code.

An eventual reconstructability review (a second model reading the overview back
against the paper) belongs in this loop, between a passing validation and
admission to the corpus — deliberately not implemented here.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from paperbench_harbor.construction.core.opencode_agent import (
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    AgentRun,
    prepare_scratch,
    run_construction,
    tail_log,
)
from paperbench_harbor.construction.core.plugin import DomainPlugin
from paperbench_harbor.construction.core.prompt import build_prompt, build_retry_prompt
from paperbench_harbor.construction.core.spec import PaperSpec
from paperbench_harbor.construction.core.validate import ValidationReport, validate_paper

#: Where a paper's own build log goes. `print` by default, so the existing CLI
#: behaves exactly as it did; :func:`build_corpus` swaps in a prefixing logger
#: when workers would otherwise interleave.
Logger = Callable[[str], None]


def _default_log(message: str) -> None:
    print(message, flush=True)


def blocked_reason(workspace: Path) -> str:
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
    plugin: DomainPlugin,
    *,
    scratch_root: Path,
    corpus_root: Path,
    build_root: Path,
    log_dir: Path,
    model: str = DEFAULT_MODEL,
    max_turns: int = 3,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    fresh: bool = False,
    dry_run: bool = False,
    validate_only: bool = False,
    log: Logger = _default_log,
) -> dict:
    """Run the agent/validate loop for one paper and return its outcome record."""

    workspace = prepare_scratch(scratch_root, spec.paper_id, fresh=fresh)
    runs: list[AgentRun] = []
    report: ValidationReport | None = None

    for turn in range(1, max_turns + 1):
        if not validate_only:
            if turn == 1:
                prompt = build_prompt(spec, str(workspace), plugin)
            else:
                assert report is not None
                prompt = build_retry_prompt(spec, report, str(workspace), plugin)
            log(f"  turn {turn}: opencode run ({model})")
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
                log(f"  turn {turn}: agent exited {run.returncode} (timed_out={run.timed_out})")
                log("  --- agent log tail ---")
                log(tail_log(run))
            if dry_run:
                return {
                    "paper_id": spec.paper_id,
                    "status": "dry-run",
                    "workspace": str(workspace),
                    "runs": [asdict(run) | {"log_path": str(run.log_path)} for run in runs],
                }

        blocked = blocked_reason(workspace)
        if blocked:
            log(f"  BLOCKED: {blocked}")
            return {
                "paper_id": spec.paper_id,
                "status": "blocked",
                "reason": blocked,
                "workspace": str(workspace),
                "runs": [asdict(run) | {"log_path": str(run.log_path)} for run in runs],
            }

        log(f"  turn {turn}: validating")
        report = validate_paper(
            workspace, spec, plugin, build_root=build_root / spec.paper_id
        )
        log("  " + report.summary().replace("\n", "\n  "))
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
        log(f"  admitted -> {destination}")
    else:
        log("  NOT admitted to the corpus")

    return outcome


def build_corpus(
    specs: list[PaperSpec],
    plugin: DomainPlugin,
    *,
    scratch_root: Path,
    corpus_root: Path,
    build_root: Path,
    log_dir: Path,
    concurrency: int = 1,
    model: str = DEFAULT_MODEL,
    max_turns: int = 3,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    fresh: bool = False,
    dry_run: bool = False,
    validate_only: bool = False,
    log: Logger = _default_log,
) -> list[dict]:
    """Build every spec, up to `concurrency` papers at a time.

    Outcomes come back in `specs` order regardless of completion order, so a
    report is reproducible. Each paper gets its own scratch workspace
    (`<scratch_root>/<paper_id>/`), its own compile build root and its own
    agent session, which is what makes running them at once safe.

    A worker that raises does not take the others down: the exception is
    recorded as that paper's outcome, since a crash in one paper's build is
    exactly as much a "this paper did not make it" as a failed validation.
    """

    if concurrency < 1:
        raise ValueError(f"concurrency must be >= 1, got {concurrency}")

    def run_one(spec: PaperSpec) -> dict:
        prefix = "" if concurrency == 1 else f"[{spec.paper_id}] "
        paper_log: Logger = log if not prefix else lambda line: log(f"{prefix}{line}")
        log(f"{prefix}{spec.paper_id}: arXiv {spec.arxiv_id}{spec.expected_version} "
            f"({spec.paper_type})")
        try:
            return build_paper(
                spec,
                plugin,
                scratch_root=scratch_root,
                corpus_root=corpus_root,
                build_root=build_root,
                log_dir=log_dir,
                model=model,
                max_turns=max_turns,
                timeout=timeout,
                fresh=fresh,
                dry_run=dry_run,
                validate_only=validate_only,
                log=paper_log,
            )
        except Exception as error:  # noqa: BLE001 - one paper must not sink the run
            log(f"{prefix}ERROR: {type(error).__name__}: {error}")
            return {
                "paper_id": spec.paper_id,
                "status": "error",
                "reason": f"{type(error).__name__}: {error}",
            }

    if concurrency == 1:
        return [run_one(spec) for spec in specs]

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(run_one, specs))
