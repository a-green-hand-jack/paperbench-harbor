"""Run two independent read-only verifier agents over a candidate set."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperbench_harbor.construction.core.opencode_agent import (
    DEFAULT_TIMEOUT_SECONDS,
    prepare_scratch,
    run_agent_session,
)
from paperbench_harbor.construction.domains import get_domain
from scripts.promote_lifesci_paperrecon_candidates import read_candidates


class VerifierError(RuntimeError):
    """The independent approval gate failed closed."""


def read_agent_approval(path: Path, *, candidates_path: Path, candidates: list) -> dict:
    """Validate the immutable manifest consumed by promotion."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VerifierError(f"cannot read agent approval {path}: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise VerifierError("agent approval must be a schema_version 1 object")
    digest = _sha256(candidates_path)
    if payload.get("candidate_sha256") != digest:
        raise VerifierError("agent approval does not match the exact candidate set")
    approved = payload.get("approved_arxiv_ids")
    candidate_ids = {candidate.arxiv_id for candidate in candidates}
    if not isinstance(approved, list) or any(not isinstance(item, str) for item in approved):
        raise VerifierError("agent approval must contain approved_arxiv_ids as strings")
    approved_ids = set(approved)
    if not approved_ids <= candidate_ids:
        raise VerifierError("agent approval names an id absent from the candidate set")
    verifiers = payload.get("verifiers")
    screening = payload.get("screening_model")
    models = [item.get("model") for item in verifiers] if isinstance(verifiers, list) else []
    if len(models) != 2 or any(not isinstance(model, str) for model in models):
        raise VerifierError("agent approval must record two verifier models")
    if len(set(models)) != 2 or screening in models:
        raise VerifierError("agent approval verifier identities are not independent")
    return {"approved_arxiv_ids": frozenset(approved_ids), "reviewer": " + ".join(models), "candidate_sha256": digest}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prompt(domain: str, model: str, candidate_path: Path, output_path: Path, ids: list[str]) -> str:
    return f"""You are an independent, read-only verifier for a PaperRecon candidate set.
You are not the screening agent, and you must not edit the candidate file or any
repository, corpus, dataset, archive, or release state. Read the exact candidate
JSON at {candidate_path}. For every one of these ids: {', '.join(ids)}, independently
check the live arXiv abstract page and e-print source, the primary category and
accepted paper license, and the GitHub repository API when code_status is
available. For not_applicable, require a concrete reason rather than missing
code. Write exactly one JSON object to {output_path} and nothing else:
{{"schema_version":1,"domain":"{domain}","candidate_sha256":"<sha256>","verifier":"{model}","verdicts":[{{"arxiv_id":"...","ok":true,"evidence":["url or path"],"reason":"..."}}]}}
Include every id exactly once. Set ok=false for any failed or unverifiable claim.
"""


def _read_verdict(path: Path, *, candidate_sha: str, domain: str, model: str, ids: set[str]) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VerifierError(f"invalid verifier output {path}: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise VerifierError(f"{path} must be a schema_version 1 object")
    if payload.get("domain") != domain or payload.get("candidate_sha256") != candidate_sha:
        raise VerifierError(f"{path} is not bound to this candidate set")
    if payload.get("verifier") != model:
        raise VerifierError(f"{path} does not identify verifier model {model}")
    verdicts = payload.get("verdicts")
    if not isinstance(verdicts, list) or len(verdicts) != len(ids) or {v.get("arxiv_id") for v in verdicts if isinstance(v, dict)} != ids:
        raise VerifierError(f"{path} must contain exactly one verdict for every candidate")
    for verdict in verdicts:
        if (
            not isinstance(verdict, dict)
            or not isinstance(verdict.get("ok"), bool)
            or not isinstance(verdict.get("reason"), str)
            or not verdict["reason"].strip()
            or not isinstance(verdict.get("evidence"), list)
            or not verdict["evidence"]
        ):
            raise VerifierError(f"{path} contains malformed verdict")
    return payload


def verify(
    *, candidate_path: Path, domain_name: str, run_root: Path, screening_model: str,
    verifier_models: tuple[str, str], timeout: int = DEFAULT_TIMEOUT_SECONDS,
    minimum_approved: int = 20,
) -> dict:
    if verifier_models[0] == verifier_models[1] or screening_model in verifier_models:
        raise VerifierError("verifiers must be distinct from each other and from the screening model")
    domain = get_domain(domain_name)
    candidates = read_candidates(candidate_path, policy=domain.screening_policy, exclude_ids=domain.exclude_ids)
    candidate_sha = _sha256(candidate_path)
    ids = {candidate.arxiv_id for candidate in candidates}
    if len(ids) < minimum_approved:
        raise VerifierError(f"candidate set has {len(ids)} records; need at least {minimum_approved}")
    verdict_payloads: list[dict] = []
    for index, model in enumerate(verifier_models, start=1):
        workspace = prepare_scratch(run_root, f"verifier-{index}", fresh=True)
        output_path = workspace / "verdict.json"
        run = run_agent_session(
            paper_id=f"paperrecon-verifier-{index}",
            prompt=_prompt(domain_name, model, candidate_path.resolve(), output_path, sorted(ids)),
            workspace=workspace,
            log_dir=run_root / "logs",
            model=model,
            timeout=timeout,
        )
        if not run.ok:
            raise VerifierError(f"verifier {model} failed; see {run.log_path}")
        verdict_payloads.append(_read_verdict(output_path, candidate_sha=candidate_sha, domain=domain_name, model=model, ids=ids))
    approved = sorted(
        arxiv_id
        for arxiv_id in ids
        if all(next(v["ok"] for v in payload["verdicts"] if v["arxiv_id"] == arxiv_id) for payload in verdict_payloads)
    )
    if len(approved) < minimum_approved:
        raise VerifierError(f"only {len(approved)} unanimous approvals; need at least {minimum_approved}")
    output = run_root / "agent-approval.json"
    result = {
        "schema_version": 1,
        "domain": domain_name,
        "candidate_sha256": candidate_sha,
        "screening_model": screening_model,
        "verifiers": [
            {"model": model, "verdict_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()}
            for model, payload in zip(verifier_models, verdict_payloads, strict=True)
        ],
        "approved_arxiv_ids": approved,
        "minimum_approved": minimum_approved,
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"agent approval -> {output}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", choices=("lifesci", "physics", "chemistry", "mathematics"), required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--screening-model", default="openai/gpt-5.6-terra")
    parser.add_argument("--verifier-model-a", default="openai/gpt-5.5")
    parser.add_argument("--verifier-model-b", default="apex/gpt-5.6-sol")
    parser.add_argument("--minimum-approved", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    try:
        verify(candidate_path=args.candidates.resolve(), domain_name=args.domain, run_root=args.run_root.resolve(), screening_model=args.screening_model, verifier_models=(args.verifier_model_a, args.verifier_model_b), timeout=args.timeout, minimum_approved=args.minimum_approved)
    except VerifierError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
