"""Run the auditable PaperSmith workflow for one new PaperRecon domain.

Without ``--candidates`` this is the LKM-first discovery and OpenCode screening
stage.  With a SHA-bound ``--agent-approval`` and the promotion/build flags it
continues through the deterministic construction and conversion gates.  It
never creates approval records and never uploads a public release.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperbench_harbor.adapters.paperrecon import paperrecon_conversion_config
from paperbench_harbor.adapters.paperwrite_bench.converter import convert_paperwrite_bench
from paperbench_harbor.construction.core.evidence import file_hash, tree_hash
from paperbench_harbor.construction.core.knowledge import get_knowledge_package
from paperbench_harbor.construction.core.literature import discover_literature
from paperbench_harbor.construction.core.opencode_agent import (
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    _enclosing_git_root,
    check_opencode_available,
)
from paperbench_harbor.construction.core.pipeline import build_corpus
from paperbench_harbor.construction.core.request import ConstructionRequest
from paperbench_harbor.construction.core.review import default_reviewer_model
from paperbench_harbor.construction.core.screen import Candidate, ScreeningError, run_screening
from paperbench_harbor.construction.core.spec import PaperSpec
from paperbench_harbor.construction.core.state import (
    StageState,
    atomic_json,
    fingerprint,
    function_hash,
    implementation_hash,
)
from paperbench_harbor.construction.core.trial import run_trial, verify_trial_evidence
from paperbench_harbor.construction.domains import get_domain
from paperbench_harbor.fidelity.dataset import DatasetAuditError
from paperbench_harbor.fidelity.review import default_conversion_reviewer_model
from paperbench_harbor.provenance.archive import build_source_archive
from paperbench_harbor.provenance.implementation import implementation_provenance
from scripts.promote_lifesci_paperrecon_candidates import (
    PromotionError,
    promote,
    read_candidates,
    read_human_approval,
)
from scripts.verify_paperrecon_candidates import VerifierError, read_agent_approval


def _summary(candidates: list[Candidate]) -> dict[str, object]:
    return {
        "count": len(candidates),
        "by_category": dict(sorted(Counter(item.expected_category for item in candidates).items())),
        "by_type": dict(sorted(Counter(item.paper_type for item in candidates).items())),
        "by_code_status": dict(sorted(Counter(item.code_status for item in candidates).items())),
    }


def _write(path: Path, payload: dict[str, object]) -> None:
    if path.name == "run-summary.json":
        payload = {"checkpoint_path": str(path.parent / "stages.json"), **payload}
        execution = path.parent / "execution.json"
        if "implementation" not in payload and execution.is_file():
            payload["implementation"] = json.loads(execution.read_text()).get("implementation")
    atomic_json(path, payload)
    if path.name == "run-summary.json":
        keys = ("status", "construction_status", "task_ready_count", "trial_status", "checkpoint_path", "target_count", "approved_count", "failed_count", "blocked_count",
                "unfinished_count", "candidate_count", "dataset", "source_archive", "tasks", "reason")
        print(json.dumps({"summary_path": str(path), **{k: payload[k] for k in keys if k in payload}}))


def _queries(domain: str, guidance: str) -> tuple[str, ...]:
    base = (
        f"{domain} research papers with public arXiv LaTeX source and reconstructable figures",
        f"{domain} papers public source materials reproducible analysis or theoretical derivation",
        f"{domain} paper reconstruction public figures tables bibliography",
    )
    return base + ((guidance,) if guidance else ())


def _stage_source_archive(run_root: Path, **options) -> Path:
    """Replace the active archive only after a new build succeeds; retain prior versions."""
    destination = run_root / "source-archive"
    staging = run_root / f"source-archive.pending-{uuid4().hex}"
    build_source_archive(output_dir=staging, **options)
    if destination.exists():
        digest = tree_hash(destination)
        history = run_root / "archive-history" / f"{digest}-{uuid4().hex}"
        history.parent.mkdir(parents=True, exist_ok=True)
        destination.rename(history)
    staging.rename(destination)
    return destination


def _checkpoint(state: StageState, stage: str, inputs: str, output: Path, action, *, resume: bool):
    digest = tree_hash(output) if output.is_dir() else ""
    if resume and state.reusable(stage, inputs, digest):
        return state.record["stages"][stage]["result"]
    state.save(stage, "running", inputs)
    try:
        result = action()
        state.save(stage, "passed", inputs, tree_hash(output), result=result)
        return result
    except Exception as error:
        state.save(stage, "failed", inputs, error=f"{type(error).__name__}: {error}")
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", choices=("lifesci", "physics", "chemistry", "mathematics"), required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--target-count", type=int, default=1)
    parser.add_argument("--extra-guidance", default="")
    parser.add_argument("--lkm-default", action="store_true", default=True)
    parser.add_argument("--no-lkm", dest="lkm_default", action="store_false")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--reviewer-model", default=None)
    parser.add_argument("--conversion-reviewer-model", default=None)
    parser.add_argument("--max-turns", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="Optional construction subprocess seconds; default unlimited")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--human-approval", type=Path, help="legacy LifeSci approval record")
    parser.add_argument("--agent-approval", type=Path, help="independent verifier-agent approval manifest")
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--convert", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--stage-candidate", action="store_true")
    parser.add_argument("--request-json", help="Structured request JSON; echoed and saved before execution")
    parser.add_argument("--research-type", help="Explicit supported research type")
    parser.add_argument("--describe-request", action="store_true", help="Validate/display request without execution")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--rerun-stage", choices=("evidence", "build", "materials", "validate", "review", "conversion", "audit", "archive"))
    parser.add_argument("--trial-model", help="Optional downstream trial, required for trial acceptance/release, not task_ready")
    parser.add_argument("--trial-agent", choices=("codex", "opencode", "claude-code"), default="codex")
    parser.add_argument("--trial-agent-version", help="Pinned trial CLI version")
    parser.add_argument("--source-id", action="append", dest="source_ids", default=[])
    return parser


def batch_counts(outcomes: list[dict], trials: list[dict], manifest: list[dict], target: int) -> dict:
    by_paper = {entry["upstream_paper_id"]: entry["task_id"] for entry in manifest}
    by_task = {trial["task_id"]: trial for trial in trials}
    if len(by_task) != len(trials) or len(by_paper) != len(manifest):
        raise ValueError("duplicate task/paper identity in delivery evidence")
    tasks = []
    for outcome in outcomes:
        task_id = by_paper.get(outcome["paper_id"])
        trial = by_task.get(task_id)
        if outcome["status"] != "ok":
            status = "blocked" if outcome["status"] == "blocked" else "failed"
            reason = outcome.get("reason", "construction failed")
        elif trial is None or trial.get("status") != "completed" or trial.get("exception") is not None:
            status, reason = "blocked", trial.get("exception") if trial else "trial not run"
        elif type(trial.get("contract_reward")) in (int, float) and trial["contract_reward"] == 1 and trial.get("diagnosis") == "contract_passed_material_review_passed":
            status, reason = "approved", "contract and independent material review passed"
        else:
            status, reason = "failed", trial.get("diagnosis", "trial acceptance failed")
        tasks.append({"paper_id": outcome["paper_id"], "task_id": task_id, "status": status, "reason": reason})
    counts = Counter(task["status"] for task in tasks)
    return {"target_count": target, "approved_count": counts["approved"],
            "failed_count": counts["failed"], "blocked_count": counts["blocked"],
            "unfinished_count": max(0, target - counts["approved"]), "tasks": tasks,
            "status": "passed" if counts["approved"] >= target else "incomplete"}


def _screen(args: argparse.Namespace) -> int:
    domain = get_domain(args.domain)
    run_root = args.run_root.resolve()
    if args.target_count < 1:
        raise ValueError("--target-count must be positive; it counts accepted tasks, not candidates")
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
    _write(run_root / "run-summary.json", {
        "status": "awaiting_verification" if len(candidates) >= args.target_count else "blocked",
        "target_count": args.target_count, "candidate_count": len(candidates), "approved_count": 0,
        "failed_count": 0, "blocked_count": 0, "unfinished_count": args.target_count,
        "reason": "candidate proposals are not accepted tasks", "candidate_path": str(output),
    })
    print(f"candidate proposal -> {output}")
    return 0 if len(candidates) >= args.target_count else 2


def _promote_and_build(args: argparse.Namespace) -> int:
    domain = get_domain(args.domain)
    if not all((args.candidates, args.promote, args.build, args.convert, args.audit)) or not (args.agent_approval or args.human_approval):
        raise ValueError(
            "promotion requires --candidates --agent-approval --promote --build --convert --audit"
        )
    candidates_path = args.candidates.resolve()
    candidates = read_candidates(
        candidates_path, policy=domain.screening_policy, exclude_ids=domain.exclude_ids
    )
    if args.source_ids and {c.arxiv_id for c in candidates} - set(args.source_ids):
        raise ValueError("candidate proposal exceeds the explicit source-ID scope")
    if args.agent_approval:
        approval = read_agent_approval(
            args.agent_approval.resolve(), candidates_path=candidates_path, candidates=candidates
        )
    else:
        legacy = read_human_approval(
            args.human_approval.resolve(), candidates_path=candidates_path, candidates=candidates
        )
        approval = {"candidate_sha256": legacy.candidate_sha256, "approved_arxiv_ids": legacy.approved_arxiv_ids, "reviewer": legacy.reviewer}
    approved_file = args.run_root.resolve() / "approved_scaleup.jsonl"
    existing_specs = list(domain.approved_papers)
    if approved_file.is_file():
        existing_specs.extend(PaperSpec(**json.loads(line)) for line in approved_file.read_text().splitlines() if line.strip())
    existing_specs = list({spec.paper_id: spec for spec in existing_specs}.values())
    _outcomes, promoted, promotion_summary = promote(
        candidates,
        approved_file=approved_file,
        promote_now=True,
        limit=None,
        approved_arxiv_ids=approval["approved_arxiv_ids"],
        human_reviewer=approval["reviewer"],
        existing_specs=existing_specs,
    )
    selected = set(approval["approved_arxiv_ids"])
    specs = [replace(spec, research_type=args.research_type)
             for spec in (*existing_specs, *promoted) if spec.arxiv_id in selected]
    candidate_by_id = {candidate.arxiv_id: candidate for candidate in candidates}
    for spec in specs:
        candidate = candidate_by_id[spec.arxiv_id]
        if any(getattr(spec, key) != getattr(candidate, key) for key in (
            "expected_version", "expected_license", "expected_category", "paper_type", "code_repo", "code_status"
        )):
            raise ValueError(f"persisted promotion conflicts with approved candidate: {spec.arxiv_id}")
    if len(specs) < args.target_count:
        raise ValueError(f"only {len(specs)} approved papers for target {args.target_count}")
    run_root = args.run_root.resolve()
    if bool(args.trial_model) != bool(args.trial_agent_version):
        raise ValueError("downstream trial requires both --trial-model and --trial-agent-version")
    implementation = implementation_provenance()
    state = StageState(run_root / "stages.json", {"domain": domain.name, "research_type": args.research_type, "implementation": implementation})
    if args.rerun_stage in ("conversion", "audit", "archive"):
        state.save(args.rerun_stage, "pending", "")
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
        fresh=False,
        resume=args.resume,
        rerun_stage=args.rerun_stage if args.rerun_stage not in ("conversion", "audit", "archive") else None,
        reviewer_model=args.reviewer_model or default_reviewer_model(),
    )
    batch = {**batch_counts(outcomes_build, [], [], args.target_count),
             "build": outcomes_build, "research_type": args.research_type, "implementation": implementation}
    failed = [item for item in outcomes_build if item["status"] != "ok"]
    if failed:
        _write(run_root / "run-summary.json", {"promotion": promotion_summary, **batch})
        return 1
    output_dir = run_root / "dataset" / domain.benchmark_config
    revision = implementation["revision"]
    library = REPO_ROOT / "src" / "paperbench_harbor"
    if {p.name for p in corpus_root.iterdir() if p.is_dir()} != {spec.paper_id for spec in specs}:
        raise ValueError("corpus contains papers outside this approval; use a separate run-root for a different selection")
    conversion_options = {"source": corpus_root, "upstream_revision": revision, "overview": "short", "overwrite": True}

    def convert():
        staging = output_dir.with_name(f".conversion-{uuid4().hex}")
        converted = convert_paperwrite_bench(
            paperrecon_conversion_config(
                domain.name, output_dir=staging, **conversion_options,
            )
        )
        if output_dir.exists():
            history = run_root / "conversion-history" / uuid4().hex
            history.parent.mkdir(parents=True, exist_ok=True)
            output_dir.rename(history)
        staging.rename(output_dir)
        return converted

    conversion_inputs = fingerprint([domain.name, conversion_options, tree_hash(corpus_root),
                                     function_hash(convert, _checkpoint),
                                     implementation_hash(library / "adapters", library / "common", REPO_ROOT / "packaging")])
    converted = _checkpoint(state, "conversion", conversion_inputs, output_dir, convert, resume=args.resume)
    audit_dir = run_root / "reports" / "fidelity"
    conversion_reviewer = args.conversion_reviewer_model or default_conversion_reviewer_model()
    audit_options = ["paperrecon", "--domain", domain.name, "--source", str(corpus_root),
                     "--dataset", str(output_dir), "--upstream-revision", revision,
                     "--overview", "short", "--output", str(audit_dir),
                     "--reviewer-model", conversion_reviewer, "--semantic-review"]

    def audit():
        input_hashes = (tree_hash(corpus_root), tree_hash(output_dir))
        if audit_dir.exists():
            audit_dir.rename(audit_dir.with_name(f"fidelity-{uuid4().hex}"))
        audit_result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "audit_fidelity.py"),
                *audit_options,
                *(["--timeout", str(args.timeout)] if args.timeout is not None else []),
            ],
            cwd=REPO_ROOT,
            check=False,
            timeout=args.timeout,
        )
        if audit_result.returncode:
            raise ValueError(f"fidelity/semantic/determinism audit failed; inspect {audit_dir}")
        if input_hashes != (tree_hash(corpus_root), tree_hash(output_dir)):
            raise ValueError("source or Harbor task changed during conversion audit")
        summary = json.loads((audit_dir / "summary.json").read_text())
        if (summary.get("failed_tasks") != 0 or summary.get("determinism_ok") is not True
            or summary.get("semantic_review_failures") != 0
            or summary.get("semantic_reviews") != converted):
            raise ValueError(f"incomplete fidelity/semantic/determinism evidence: {audit_dir}")
        return summary

    audit_inputs = fingerprint([conversion_inputs, tree_hash(output_dir), audit_options,
                                function_hash(audit, _checkpoint),
                                implementation_hash(library / "fidelity", REPO_ROOT / "scripts" / "audit_fidelity.py")])
    _checkpoint(state, "audit", audit_inputs, audit_dir, audit, resume=args.resume)
    trials = []
    manifest = [json.loads(line) for line in (output_dir / "dataset-manifest.jsonl").read_text().splitlines() if line]
    if {entry["upstream_paper_id"] for entry in manifest} != {spec.paper_id for spec in specs} or len(manifest) != len(specs):
        raise ValueError("converted task coverage does not match the approved construction selection")
    package = get_knowledge_package(domain.name, args.research_type)
    if args.trial_model and args.trial_agent_version:
        builds = {item["paper_id"]: item for item in outcomes_build}
        for entry in manifest:
            task = output_dir / entry["task_id"]
            build = builds[entry["upstream_paper_id"]]
            trial_root = run_root / "trials" / entry["task_id"]
            paper = corpus_root / entry["upstream_paper_id"]
            review_path = paper / "original" / "reconstructability_review.json"
            execution = {"trial_model": args.trial_model, "trial_agent": args.trial_agent,
                         "trial_agent_version": args.trial_agent_version,
                         "reviewer_model": args.reviewer_model or default_reviewer_model()}
            knowledge = json.loads(json.dumps(package.as_dict()))
            trial_inputs = fingerprint([tree_hash(task), file_hash(review_path), knowledge, execution,
                                        implementation_hash(library / "construction" / "core" / "trial.py")])
            trial_state = StageState(trial_root / "stages.json", execution)
            previous = trial_state.record["stages"].get("trial", {})
            if args.resume and trial_state.reusable("trial", trial_inputs, fingerprint(previous.get("result"))):
                try:
                    verified = verify_trial_evidence(previous["result"], root=run_root, task=task, paper=paper,
                                                     knowledge=knowledge, execution=execution)
                except (ValueError, OSError, KeyError, TypeError, AttributeError):
                    pass
                else:
                    trials.append({**previous["result"], **verified})
                    continue
            # Each attempt gets its own directory; never overwrite a trajectory.
            attempt = 1
            while (trial_root / str(attempt)).exists():
                attempt += 1
            trial_state.save("trial", "running", trial_inputs)
            trial = run_trial(
                task, output=trial_root / str(attempt), model=args.trial_model,
                agent=args.trial_agent, agent_version=args.trial_agent_version,
                knowledge=package.as_dict(), material_review=build.get("review", {}),
                review_path=review_path,
                timeout=args.trial_timeout,
            )
            try:
                verify_trial_evidence(trial, root=run_root, task=task, paper=paper, knowledge=knowledge, execution=execution)
            except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
                trial = {**trial, "status": "blocked", "exception": f"invalid_trial_evidence:{type(error).__name__}", "diagnosis": "environment"}
                trial_state.save("trial", "failed", trial_inputs, result=trial, error=str(error))
            else:
                trial_state.save("trial", "passed", trial_inputs, fingerprint(trial), result=trial)
            trials.append(trial)
    trial_counts = batch_counts(outcomes_build, trials, manifest, args.target_count)
    batch.update(trial_counts)
    batch["trials"] = trials
    batch["trial_status"] = trial_counts["status"] if trials else "not_run"
    batch["trial_acceptance"] = trial_counts
    source_archive = None
    if args.stage_candidate:
        archive_options = {
            "release_root": run_root / "dataset",
            "dataset_repo": f"candidate/{domain.benchmark_config}",
            "dataset_revision": revision,
            "converter_revision": revision,
            "paperwrite_source": corpus_root,
            "paperwritingbench_source": corpus_root,
            "lifesci_source": corpus_root,
            "paperrecon_sources": {domain.name: corpus_root},
            "included_configs": {domain.benchmark_config},
            "implementation": implementation,
        }
        archive_inputs = fingerprint([tree_hash(output_dir), tree_hash(corpus_root), archive_options,
                                      function_hash(_stage_source_archive, _checkpoint),
                                      implementation_hash(library / "provenance", library / "source_archive")])
        source_archive_dir = _checkpoint(state, "archive", archive_inputs, run_root / "source-archive",
                                        lambda: str(_stage_source_archive(run_root, **archive_options)), resume=args.resume)
        source_archive = str(source_archive_dir)
    result = {
        **batch,
        "status": "passed" if trial_counts["status"] == "passed" else "task_ready",
        "construction_status": "task_ready",
        "task_ready_count": len(manifest),
        "construction_unfinished_count": max(0, args.target_count - len(manifest)),
        "failed_count": 0,
        "blocked_count": 0,
        "unfinished_count": max(0, args.target_count - len(manifest)),
        "tasks": [{**task, "status": "approved" if task["status"] == "approved" else "task_ready", "construction_status": "task_ready", "reason": "construction, independent review and conversion audits passed",
                   "trial_status": task["status"] if trials else "not_run", "trial_reason": task["reason"]} for task in trial_counts["tasks"]],
        "checkpoint_path": str(state.path),
        "promotion": promotion_summary,
        "approval_sha256": approval["candidate_sha256"],
        "built_tasks": len(outcomes_build),
        "converted_tasks": converted,
        "dataset": str(output_dir),
        "candidate_stage": bool(args.stage_candidate),
        "source_archive": source_archive,
        "knowledge": package.as_dict(),
        "dataset_tree_sha256": tree_hash(output_dir),
        "archive_tree_sha256": tree_hash(Path(source_archive)) if source_archive else None,
        "fidelity_summary_sha256": file_hash(run_root / "reports" / "fidelity" / "summary.json"),
        "execution_sha256": file_hash(run_root / "execution.json"),
    }
    _write(run_root / "run-summary.json", result)
    print(f"Harbor tasks task_ready -> {output_dir}")
    return 2 if trials and trial_counts["status"] != "passed" else 0


def main() -> int:
    args = _parser().parse_args()
    try:
        defaults = {"lifesci": "experimental", "physics": "simulation",
                    "chemistry": "synthesis_characterization", "mathematics": "theorem_proof"}
        request = ConstructionRequest.model_validate_json(args.request_json) if args.request_json else ConstructionRequest(
            domain=args.domain, research_type=args.research_type or defaults[args.domain],
            target_count=args.target_count, topic=args.extra_guidance,
            source_ids=args.source_ids,
            delivery_root=str(args.run_root.resolve()), timeout_seconds=args.timeout,
            max_turns=args.max_turns, concurrency=args.concurrency,
        )
        if request.domain != args.domain or Path(request.delivery_root).resolve() != args.run_root.resolve():
            raise ValueError("request domain/delivery_root contradict CLI")
        args.research_type = request.research_type
        args.source_ids = request.source_ids
        args.trial_timeout = request.trial_timeout_seconds
        args.target_count = request.target_count
        args.timeout, args.max_turns, args.concurrency = request.timeout_seconds, request.max_turns, request.concurrency
        args.extra_guidance = request.topic + "\nResearch type: " + request.research_type
        if request.source_ids:
            args.extra_guidance += "\nOnly these proposed source IDs: " + ", ".join(request.source_ids)
        print(request.model_dump_json(indent=2))
        if args.describe_request:
            return 0
        git_root = _enclosing_git_root(args.run_root.resolve())
        if git_root is not None:
            raise ValueError(f"run-root must be outside every Git working tree: {git_root}")
        _write(args.run_root.resolve() / "request.json", request.model_dump())
        _write(args.run_root.resolve() / "execution.json", {
            "implementation": implementation_provenance(),
            "worker_model": args.model, "reviewer_model": args.reviewer_model or default_reviewer_model(),
            "conversion_reviewer_model": args.conversion_reviewer_model or default_conversion_reviewer_model(),
            "trial_model": args.trial_model, "trial_agent": args.trial_agent,
            "trial_agent_version": args.trial_agent_version,
        })
        handoff = {"upload_candidate_requested": request.upload_candidate, "publish_requested": request.publish,
                   "uploaded": False, "published": False,
                   "status": "awaiting_release_operator" if request.upload_candidate or request.publish else "local_only",
                   "command": "scripts/publish_paperrecon_release.py",
                   "required_flags": (["--upload-candidate"] if request.upload_candidate else []) + (["--publish"] if request.publish else [])}
        _write(args.run_root.resolve() / "release-handoff.json", handoff)
        print(json.dumps({"release_handoff": handoff}))
        return _promote_and_build(args) if args.candidates else _screen(args)
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired, PromotionError, ScreeningError, DatasetAuditError, VerifierError) as error:
        print(f"ERROR: {error}")
        root = args.run_root.resolve()
        if _enclosing_git_root(root) is None and (root / "request.json").is_file():
            _write(root / "run-summary.json", {"status": "blocked", "target_count": args.target_count,
                   "approved_count": 0, "failed_count": 0, "blocked_count": 0,
                   "unfinished_count": args.target_count, "reason": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
