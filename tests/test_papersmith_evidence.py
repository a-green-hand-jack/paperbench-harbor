from __future__ import annotations

import json

import pytest

from paperbench_harbor.construction.core.evidence import (
    Fact,
    file_hash,
    public_requirement,
    tree_hash,
    validate_research_evidence,
)
from paperbench_harbor.construction.core.knowledge import PACKAGES, get_knowledge_package
from paperbench_harbor.construction.core.request import ConstructionRequest
from paperbench_harbor.construction.core.review import ReviewError, parse_verdict
from paperbench_harbor.construction.core.state import StageState
from paperbench_harbor.construction.core.trial import diagnose_trial


def evidence_fixture(root, package):
    (root / "original").mkdir()
    (root / "resources").mkdir()
    source = root / "original" / "main.tex"
    source.write_text("Located original research statement.\n")
    public = root / "resources" / "research_overview_short.md"
    public.write_text("Independent public evidence of the scientific result.\n")

    def fact(name):
        return {"id": name, "kind": name, "statement": "A supported scientific statement",
                "sources": [{"path": "original/main.tex", "locator": "lines:1-1", "sha256": file_hash(source)}],
                "public_support": [{"path": "resources/research_overview_short.md", "locator": "lines:1-1", "sha256": file_hash(public)}]}

    checks = {
        "lifesci": {"biological_replicates": 3, "technical_replicates": 2, "design": "interventional"},
        "physics": {"convergence_tolerance": 0.01, "error_bound": 0.001, "refinements": [32.0, 64.0]},
        "chemistry": {"yield_percent": 85.0, "purity_percent": 99.0, "product_identity": "ethanol", "characterized_identity": "ethanol"},
        "mathematics": {"lemma_dependencies": {"L1": [], "T1": ["L1"]}, "requires_proof_discovery": False},
    }
    data = {
        "schema_version": 1, "domain": package.domain, "research_type": package.research_type,
        "knowledge_version": package.version, "capability": "writing_reconstruction",
        "question": fact("question"), "methods": [fact("method")],
        "assumptions": [fact("assumption")], "facts": [fact(kind) for kind in package.required_facts],
        "claims": [{**fact("claim"), "evidence_ids": [package.required_facts[0]], "limitations": ["Only studied conditions"]}],
        "requirements": [fact("requirement")],
        "assets": [{"path": "original/main.tex", "source_url": "https://arxiv.org/e-print/2601.00001v1",
                    "revision": "2601.00001v1", "license": "CC BY 4.0", "sha256": file_hash(source),
                    "status": "included", "required": True}],
        "domain_checks": checks[package.domain],
    }
    (root / "resources" / "writing_requirements.json").write_text(json.dumps([
        public_requirement(Fact.model_validate(data["requirements"][0]))
    ]))
    write_evidence(root, data)
    return data


def write_evidence(root, data):
    (root / "original" / "research_evidence.json").write_text(json.dumps(data))


@pytest.mark.parametrize("package", PACKAGES, ids=lambda p: p.domain)
def test_domain_material_contract_passes_and_missing_fact_fails(tmp_path, package):
    data = evidence_fixture(tmp_path, package)
    assert validate_research_evidence(tmp_path, package.domain, package.research_type)
    data["facts"].pop()
    write_evidence(tmp_path, data)
    with pytest.raises(ValueError, match="missing .* evidence"):
        validate_research_evidence(tmp_path, package.domain, package.research_type)


@pytest.mark.parametrize("domain,field,value", [
    ("lifesci", "biological_replicates", 0),
    ("physics", "refinements", [32.0, 32.0]),
    ("chemistry", "characterized_identity", "methanol"),
    ("mathematics", "lemma_dependencies", {"L1": ["T1"], "T1": ["L1"]}),
])
def test_domain_specific_invalid_evidence(tmp_path, domain, field, value):
    package = next(p for p in PACKAGES if p.domain == domain)
    data = evidence_fixture(tmp_path, package)
    data["domain_checks"][field] = value
    write_evidence(tmp_path, data)
    with pytest.raises(ValueError):
        validate_research_evidence(tmp_path, domain, package.research_type)


@pytest.mark.parametrize("mutation", ["private", "stale", "missing", "revision", "requirements", "renamed_answer", "symlink"])
def test_evidence_and_boundary_fail_closed(tmp_path, mutation):
    package = PACKAGES[0]
    data = evidence_fixture(tmp_path, package)
    if mutation == "private":
        data["question"]["public_support"] = data["question"]["sources"]
    elif mutation == "stale":
        (tmp_path / "resources" / "research_overview_short.md").write_text("Changed claim")
    elif mutation == "missing":
        data["assets"][0].update(status="missing", reason="supplement unavailable")
    elif mutation == "revision":
        data["assets"][0]["revision"] = "main"
    elif mutation == "requirements":
        (tmp_path / "resources" / "writing_requirements.json").write_text("[]")
    elif mutation == "renamed_answer":
        (tmp_path / "resources" / "answer.txt").write_bytes((tmp_path / "original" / "main.tex").read_bytes())
    else:
        (tmp_path / "resources" / "linked.txt").symlink_to(tmp_path / "original" / "main.tex")
    write_evidence(tmp_path, data)
    with pytest.raises(ValueError):
        validate_research_evidence(tmp_path, package.domain, package.research_type)


def test_request_defaults_and_unsupported_capability(tmp_path):
    args = {"domain": "mathematics", "research_type": "theorem_proof", "delivery_root": str(tmp_path)}
    request = ConstructionRequest(**args)
    assert request.target_count == 1
    assert not request.publish and not request.upload_candidate
    with pytest.raises(ValueError, match="proof_discovery"):
        ConstructionRequest(**args, capability="proof_discovery")
    with pytest.raises(ValueError, match="unsupported research type"):
        get_knowledge_package("mathematics", "numerical")
    with pytest.raises(ValueError):
        ConstructionRequest(**args, publish=True)
    with pytest.raises(ValueError):
        ConstructionRequest(**args, target_count=True)


def test_state_invalidation_is_bound_to_configuration_and_material(tmp_path):
    path = tmp_path / "stages.json"
    state = StageState(path, {"knowledge": "1.0.0"})
    state.save("evidence", "passed", "input", "evidence")
    state.save("review", "passed", "evidence", "review")
    assert StageState(path, state.config).reusable("review", "evidence", "review")
    assert not state.reusable("review", "changed", "review")
    state.save("evidence", "running", "new-input")
    assert "review" not in state.record["stages"]
    assert not StageState(path, {"knowledge": "2.0.0"}).record["stages"]


def test_structured_review_rejects_contradictory_pass(tmp_path):
    path = tmp_path / "verdict.json"
    path.write_text(json.dumps({"ok": True, "reasoning": "checked", "concerns": [],
                               "defects": [{"category": "leakage", "severity": "blocking",
                                            "source_evidence": ["resources/answer.txt:lines:1-3"], "repair": "Remove answer"}]}))
    with pytest.raises(ReviewError, match="contradicts"):
        parse_verdict(path, require_structured=True)


def test_trial_diagnosis_does_not_conflate_reward_and_quality():
    assert diagnose_trial(reward=0, exception="DockerError", material_ok=True) == "environment"
    assert diagnose_trial(reward=1, exception=None, material_ok=False) == "material_defect"
    assert diagnose_trial(reward=0, exception=None, material_ok=True) == "model_or_task_unresolved"


def test_tree_hash_changes_with_material_and_rejects_links(tmp_path):
    path = tmp_path / "material.txt"
    path.write_text("one")
    first = tree_hash(tmp_path)
    path.write_text("two")
    assert tree_hash(tmp_path) != first
    (tmp_path / "link").symlink_to(path)
    with pytest.raises(ValueError, match="symlink"):
        tree_hash(tmp_path)
