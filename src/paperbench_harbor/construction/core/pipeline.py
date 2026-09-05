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

The reconstructability review (:mod:`.review`) is the third rule, added once
the structural gate had proved it could not see semantic problems: a paper that
passes :func:`~.validate.validate_paper` is handed to a *different* model to be
read back against its own overview, and a failing verdict is recorded on the
same :class:`~.validate.ValidationReport` as any other contract violation. That
is the whole integration — no second report type, no second retry loop. The
existing feedback path carries the reviewer's concerns into the next turn
because ``report.agent_feedback()`` renders every issue it is given.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from paperbench_harbor.construction.core.evidence import (
    ResearchEvidence,
    file_hash,
    source_fingerprint,
    synchronize_research_materials,
    tree_hash,
    validate_research_evidence,
)
from paperbench_harbor.construction.core.knowledge import get_knowledge_package
from paperbench_harbor.construction.core.opencode_agent import (
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    AgentRun,
    prepare_scratch,
    run_agent_session,
    tail_log,
)
from paperbench_harbor.construction.core.plugin import DomainPlugin
from paperbench_harbor.construction.core.prompt import build_prompt, build_retry_prompt
from paperbench_harbor.construction.core.review import (
    ReviewVerdict,
    default_reviewer_model,
    run_review,
    write_review_record,
)
from paperbench_harbor.construction.core.spec import PaperSpec
from paperbench_harbor.construction.core.state import StageState, fingerprint
from paperbench_harbor.construction.core.validate import (
    ValidationReport,
    synchronize_source_table_materials,
    validate_paper,
)

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
    skip_review: bool = False,
    reviewer_model: str | None = None,
    resume: bool = False,
    rerun_stage: str | None = None,
    log: Logger = _default_log,
) -> dict:
    """Run the agent/validate/review loop for one paper and return its outcome.

    `skip_review` turns off stage 3 for cheap structural iteration. Note what it
    does *not* interact with: the plan called for review to run only when
    compilation is also being checked, but `run_compile` is not a parameter of
    this loop — :func:`~.validate.validate_paper` is always called with its
    default `run_compile=True`, and `validate_only` skips the *agent*, not the
    compile. So the guard reduces to `skip_review` alone, which is the flag that
    actually controls the cost.
    """

    workspace = prepare_scratch(scratch_root, spec.paper_id, fresh=fresh)
    if max_turns < 1:
        raise ValueError("max_turns must be positive")
    package = get_knowledge_package(plugin.name, spec.research_type) if spec.research_type else None
    state = StageState(build_root / spec.paper_id / "stages.json", {
        "spec": asdict(spec), "package": package.as_dict() if package else None,
        "plugin": fingerprint(asdict(plugin)),
        "packaging": tree_hash(Path(__file__).parents[4] / "packaging"),
        "model": model, "reviewer_model": reviewer_model or default_reviewer_model(),
        "timeout": timeout, "max_turns": max_turns, "skip_review": skip_review,
        "implementation": fingerprint({str(p.relative_to(Path(__file__).parents[2])): file_hash(p)
                                       for p in Path(__file__).parents[2].rglob("*")
                                       if p.is_file() and p.suffix in (".py", ".j2", ".md", ".json")
                                       and not {"vendor", "__pycache__"} & set(p.parts)}),
    })
    inputs = fingerprint(state.config)
    destination = corpus_root / spec.paper_id
    if resume and not fresh and not rerun_stage and destination.is_dir():
        digest = tree_hash(destination)
        if state.reusable("delivery", inputs, digest) and tree_hash(workspace) == digest:
            return state.record["stages"]["delivery"]["outcome"]
    if rerun_stage in ("materials", "validate", "review"):
        validate_only = True
    if package and not validate_only and not dry_run:
        extraction_path = workspace / "original" / "research_evidence.json"
        existing_hash = source_fingerprint(workspace) if extraction_path.is_file() else ""
        reuse = resume and rerun_stage not in ("evidence",) and state.reusable("evidence", inputs, existing_hash)
        if rerun_stage == "build" and extraction_path.is_file():
            # An explicit material rebuild rechecks the current extraction and every source hash.
            # It does not need another generative extraction of unchanged pinned assets.
            validate_research_evidence(workspace, plugin.name, spec.research_type, public_ready=False)
            state.save("evidence", "passed", inputs, source_fingerprint(workspace))
            reuse = True
        if not reuse:
            state.save("evidence", "running", inputs)
            extraction_prompt = (
                f"Extract research evidence for {spec.arxiv_abs_url} into {workspace}. "
                "Do not generate overviews or writer materials yet. Fetch the pinned LaTeX, PDF, "
                "supplementary assets and code; record license, immutable version and SHA-256 "
                "for every source asset, with explicit missing/excluded reasons. "
                "Keep all source answers in original/. Never substitute a different version. "
                "Write original/research_evidence.json matching this schema: "
                + json.dumps(ResearchEvidence.model_json_schema())
                + "\nKnowledge package: " + json.dumps(package.as_dict())
                + "\nFor each required_facts entry, include a Fact with kind EXACTLY equal "
                "to that entry (including plural spelling), not merely a matching ID. "
                "Locators must be exact schema strings like lines:40-44, not prose or "
                "comma-separated ranges; use separate Location objects for separate ranges. "
                "Asset revision must be a bare immutable ID such as 2609.02220v1 or a full "
                "commit SHA, without dates or explanatory prose. Public support must point "
                "to the planned resources/research_overview_short.md, summary.txt, references.bib "
                "or figures/tables/code assets, NOT an original article HTML/PDF answer. "
                + "\nAll source locations must exist and match their hashes. public_support is "
                "a planned resources/ location with a zero SHA-256 placeholder until construction. "
                "Question, methods, assumptions, claims, limitations and requirements must be "
                "located in the actual source. Never invent absent facts. For an ineligible "
                "paper write original/provenance.json with a blocked reason and stop."
            )
            extraction_error = ""
            for attempt in range(1, max_turns + 1):
                run = run_agent_session(
                    paper_id=f"{spec.paper_id}.evidence", prompt=extraction_prompt + extraction_error,
                    workspace=workspace, log_dir=log_dir, model=model, turn=attempt,
                    timeout=timeout, continue_session=False,
                )
                try:
                    if not run.ok:
                        raise ValueError(f"extraction process failed: {run.returncode}")
                    validate_research_evidence(workspace, plugin.name, spec.research_type, public_ready=False)
                    state.save("evidence", "passed", inputs, source_fingerprint(workspace))
                    break
                except (ValueError, OSError) as error:
                    extraction_error = f"\nRepair the previous extraction failure: {error}"
                    state.save("evidence", "failed", inputs, error=str(error))
            else:
                reason = blocked_reason(workspace) or extraction_error.strip()
                return {"paper_id": spec.paper_id, "status": "blocked" if blocked_reason(workspace) else "failed", "reason": reason}
    runs: list[AgentRun] = []
    report: ValidationReport | None = None
    verdict: ReviewVerdict | None = None
    if resume and (workspace / "resources" / "template.tex").is_file():
        report = validate_paper(workspace, spec, plugin, build_root=build_root / spec.paper_id)

    for turn in range(1, max_turns + 1):
        if not validate_only:
            state.save("build", "running", inputs, turn=turn)
            if turn == 1 and (report is None or report.ok):
                prompt = build_prompt(spec, str(workspace), plugin)
            else:
                assert report is not None
                prompt = build_retry_prompt(spec, report, str(workspace), plugin)
            log(f"  turn {turn}: opencode run ({model})")
            run = run_agent_session(
                paper_id=spec.paper_id,
                prompt=prompt,
                workspace=workspace,
                log_dir=log_dir,
                model=model,
                turn=turn,
                continue_session=turn > 1 and not spec.research_type,
                timeout=timeout,
                dry_run=dry_run,
            )
            runs.append(run)
            state.save("build", "passed" if run.ok else "failed", inputs, tree_hash(workspace),
                       returncode=run.returncode, log_path=str(run.log_path))
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

        if plugin.require_table_inventory and not validate_only:
            tables = synchronize_source_table_materials(workspace)
            log(f"  turn {turn}: synchronized {len(tables)} source table(s)")

        synchronization_error = None
        if spec.research_type and (not validate_only or rerun_stage == "materials"):
            try:
                synchronize_research_materials(workspace)
            except (ValueError, OSError) as error:
                synchronization_error = str(error)

        log(f"  turn {turn}: validating")
        report = validate_paper(
            workspace, spec, plugin, build_root=build_root / spec.paper_id
        )
        if synchronization_error:
            report.fail("public-material-bindings", synchronization_error, remedy="Supply the located public material; do not substitute private evidence.")
        state.save("validate", "passed" if report.ok else "failed", tree_hash(workspace),
                   issues=[asdict(issue) for issue in report.issues])
        # Stage 3 runs only on a structurally sound sample: asking a model
        # whether an overview is faithful is pointless when the gate already
        # knows a required file is missing, and it would burn a reviewer call
        # per turn to say so.
        if report.ok and not skip_review:
            log(f"  turn {turn}: reconstructability review "
                f"({reviewer_model or default_reviewer_model()})")
            verdict = run_review(
                spec,
                plugin,
                workspace,
                build_root=build_root,
                model=reviewer_model,
                log_dir=log_dir,
                dry_run=dry_run,
                timeout=timeout,
            )
            state.save("review", "passed" if verdict.ok else "blocked" if verdict.blocked else "failed", tree_hash(workspace),
                       report=verdict.as_dict())
            if not verdict.ok:
                report.fail(
                    "reconstructability-review",
                    verdict.reasoning,
                    remedy=verdict.remedy(),
                )
        log("  " + report.summary().replace("\n", "\n  "))
        if report.ok:
            break
        if validate_only or (verdict is not None and verdict.blocked):
            break

    assert report is not None
    outcome = {
        "paper_id": spec.paper_id,
        "status": "ok" if report.ok else "blocked" if verdict is not None and verdict.blocked else "failed",
        "workspace": str(workspace),
        "turns": len(runs),
        "issues": [asdict(issue) for issue in report.issues],
        "compiles": [
            {"tex_name": result.tex_name, "ok": result.ok} for result in report.compiles
        ],
        "runs": [asdict(run) | {"log_path": str(run.log_path)} for run in runs],
    }
    if verdict is not None:
        outcome["review"] = verdict.as_dict()

    if report.ok:
        destination = corpus_root / spec.paper_id
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Written into the workspace before the copy rather than into the
        # corpus after it, so the audit trail travels with the paper by the
        # same mechanism as everything else it carries.
        if verdict is not None:
            write_review_record(workspace, verdict)
        # `.git` would carry the code repo's full history into every Harbor
        # task's build context; the checked-out tree plus a recorded commit is
        # what provenance needs. `symlinks=True`: a `resources/code/` checkout
        # can contain symlinks with dead targets outside the tree (an author's
        # own machine, an external drive) — copy the link, not its target, or
        # this raises `shutil.Error` on an otherwise-successful build.
        shutil.copytree(
            workspace,
            destination,
            symlinks=True,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".opencode"),
        )
        outcome["corpus_dir"] = str(destination)
        state.save("delivery", "passed", inputs, tree_hash(destination), outcome=outcome)
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
    skip_review: bool = False,
    reviewer_model: str | None = None,
    resume: bool = False,
    rerun_stage: str | None = None,
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
                skip_review=skip_review,
                reviewer_model=reviewer_model,
                resume=resume,
                rerun_stage=rerun_stage,
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
