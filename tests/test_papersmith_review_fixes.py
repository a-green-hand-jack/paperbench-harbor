from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from paperbench_harbor.common.audit import audit_public_materials
from paperbench_harbor.construction.core.evidence import (
    file_hash,
    source_fingerprint,
    validate_boundary,
)
from paperbench_harbor.construction.core.request import ConstructionRequest
from paperbench_harbor.construction.core.review import ReviewError, parse_verdict
from paperbench_harbor.construction.core.trial import run_trial
from scripts import publish_paperrecon_release as publisher
from scripts import run_paperrecon_domain as runner
from scripts.test_publish_paperrecon_release import _run


def test_cli_build_has_initialized_source_ids(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "_enclosing_git_root", lambda path: None)
    def build(args):
        assert args.source_ids == []
        assert args.research_type == "simulation"
        return 0
    monkeypatch.setattr(runner, "_promote_and_build", build)
    monkeypatch.setattr(sys, "argv", ["runner", "--domain", "physics", "--run-root", str(tmp_path), "--candidates", "candidate.json"])
    assert runner.main() == 0


def test_cli_reaches_actual_promotion_and_build_with_default_ids(monkeypatch, tmp_path):
    from paperbench_harbor.construction.core.spec import PaperSpec

    monkeypatch.setattr(runner, "_enclosing_git_root", lambda path: None)
    spec = PaperSpec("paper_1", "2601.00001", "simulation", code_repo="https://github.com/example/code", expected_version="v1")
    monkeypatch.setattr(runner, "read_candidates", lambda *args, **kwargs: [spec])
    monkeypatch.setattr(runner, "read_agent_approval", lambda *args, **kwargs: {"approved_arxiv_ids": [spec.arxiv_id], "reviewer": "fixture", "candidate_sha256": "a" * 64})
    monkeypatch.setattr(runner, "promote", lambda *args, **kwargs: ([], [spec], {}))
    monkeypatch.setattr(runner, "check_opencode_available", lambda model: None)
    def build(specs, plugin, **kwargs):
        assert specs[0].research_type == "simulation"
        return [{"paper_id": "paper_1", "status": "failed", "reason": "fixture material failure"}]
    monkeypatch.setattr(runner, "build_corpus", build)
    monkeypatch.setattr(sys, "argv", ["runner", "--domain", "physics", "--run-root", str(tmp_path), "--candidates", "candidate.json", "--agent-approval", "approval.json", "--promote", "--build", "--convert", "--audit"])
    assert runner.main() == 1
    assert json.loads((tmp_path / "run-summary.json").read_text())["failed_count"] == 1


@pytest.mark.parametrize("domain", ["lifesci", "physics", "chemistry", "mathematics"])
def test_fidelity_uses_all_registered_domain_layouts(domain):
    from paperbench_harbor.adapters.paperrecon import get_paperrecon_adapter
    from paperbench_harbor.fidelity.audit import _layout_spec

    adapter = get_paperrecon_adapter(domain)
    assert _layout_spec(adapter.benchmark).benchmark == adapter.benchmark


@pytest.mark.parametrize("field,value", [("source_scope", "all journals"), ("difficulty", "proof discovery"),
                                        ("capability", "proof_discovery"), ("material_policy", "hide crucial facts")])
def test_unsupported_request_semantics_rejected(field, value):
    with pytest.raises(ValueError):
        ConstructionRequest(domain="physics", research_type="simulation", delivery_root="/outside", **{field: value})


def test_remote_intent_is_an_explicit_unexecuted_handoff(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "_enclosing_git_root", lambda path: None)
    request = ConstructionRequest(domain="physics", research_type="simulation", delivery_root=str(tmp_path), upload_candidate=True, publish=True)
    monkeypatch.setattr(sys, "argv", ["runner", "--domain", "physics", "--run-root", str(tmp_path), "--request-json", request.model_dump_json()])
    monkeypatch.setattr(runner, "_screen", lambda args: 0)
    assert runner.main() == 0
    handoff = json.loads((tmp_path / "release-handoff.json").read_text())
    assert handoff["status"] == "awaiting_release_operator"
    assert handoff["required_flags"] == ["--upload-candidate", "--publish"]
    assert not handoff["uploaded"] and not handoff["published"]


def test_run_root_is_checked_before_any_writes(monkeypatch, tmp_path):
    (tmp_path / ".git").write_text("gitdir: elsewhere")
    root = tmp_path / "new" / "run"
    monkeypatch.setattr(sys, "argv", ["runner", "--domain", "physics", "--run-root", str(root)])
    assert runner.main() == 1
    assert not root.exists()


@pytest.fixture
def release_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(publisher, "MIN_TASKS", 1)
    roots = {d: tmp_path / d for d in publisher.DOMAINS}
    for domain, root in roots.items():
        _run(root, domain, count=1)
    assert publisher.load_gate(roots)
    return roots


@pytest.mark.parametrize("mutation", ["dataset_escape", "archive_escape", "symlink", "reward_zero", "reward_bool", "unfinished", "exception", "wrong_task", "model", "agent", "version", "knowledge", "review", "trace_missing", "trace_changed", "trace_escape", "trial_changed", "private_mount", "verification_disabled", "observed_model"])
def test_release_requires_real_bound_evidence(release_roots, tmp_path, mutation):
    root = release_roots["physics"]
    summary_path = root / "run-summary.json"
    summary = json.loads(summary_path.read_text())
    ref = summary["trials"][0]
    evidence_path = Path(ref["evidence_path"])
    evidence = json.loads(evidence_path.read_text())
    result_path = Path(evidence["result_path"])
    result = json.loads(result_path.read_text())
    if mutation in ("dataset_escape", "archive_escape"):
        summary["dataset" if mutation == "dataset_escape" else "source_archive"] = str(tmp_path)
    elif mutation == "symlink":
        link = root / "linked-evidence.json"
        link.symlink_to(evidence_path)
        ref["evidence_path"] = str(link)
    elif mutation in ("reward_zero", "reward_bool"):
        result["verifier_result"]["rewards"]["reward"] = 0 if mutation == "reward_zero" else True
    elif mutation == "unfinished":
        result["finished_at"] = None
    elif mutation == "exception":
        result["exception_info"] = {"exception_type": "DockerError"}
    elif mutation == "wrong_task":
        result["task_id"]["path"] = str(tmp_path)
    elif mutation == "private_mount":
        result["config"]["environment"]["mounts"] = [{"source": str(root / "corpus"), "target": "/private"}]
    elif mutation == "verification_disabled":
        result["config"]["verifier"]["disable"] = True
    elif mutation == "observed_model":
        result["agent_info"]["model_info"]["name"] = "other"
    elif mutation in ("model", "agent", "version"):
        evidence[{"version": "agent_version"}.get(mutation, mutation)] = "other"
    elif mutation == "knowledge":
        evidence["knowledge"]["version"] = "2.0.0"
    elif mutation == "review":
        Path(evidence["review_path"]).write_text('{"ok":true}')
    elif mutation == "trace_missing":
        evidence["trajectories"] = []
    elif mutation == "trace_changed":
        Path(evidence["trajectories"][0]["path"]).write_text("changed")
    elif mutation == "trace_escape":
        evidence["trajectories"][0]["path"] = str(root / "execution.json")
        evidence["trajectories"][0]["sha256"] = file_hash(root / "execution.json")
    elif mutation == "trial_changed":
        evidence["status"] = "running"
    # Rebind hashes deliberately: a matching digest alone must not authorize invalid results.
    result_path.write_text(json.dumps(result))
    evidence["result_sha256"] = file_hash(result_path)
    evidence_path.write_text(json.dumps(evidence))
    ref["evidence_sha256"] = file_hash(evidence_path)
    summary_path.write_text(json.dumps(summary))
    with pytest.raises(publisher.ReleasePublisherError):
        publisher.load_gate(release_roots)


def test_pinned_code_exception_and_symlink_guards(tmp_path):
    (tmp_path / "original").mkdir()
    code = tmp_path / "resources" / "code"
    code.mkdir(parents=True)
    (code / "main.tex").write_text("Example unrelated to the original paper")
    with pytest.raises(ValueError, match="provenance"):
        validate_boundary(tmp_path)
    (tmp_path / "original" / "provenance.json").write_text(json.dumps({"code_repo": "https://github.com/example/code", "code_commit": "a" * 40}))
    validate_boundary(tmp_path)
    (code / "link").symlink_to(tmp_path / "original")
    with pytest.raises(ValueError, match="symlink"):
        validate_boundary(tmp_path)


@pytest.mark.parametrize("name", ["main.tex", "main.pdf", "config.yaml", "eval_points.json", "source_manifest.json", "provenance.json"])
def test_trial_reuses_authoritative_forbidden_names(tmp_path, name):
    (tmp_path / name).write_text("private")
    with pytest.raises(ValueError):
        audit_public_materials(tmp_path, code_prefix="materials/code", code_approved=False)


@pytest.mark.parametrize("reference", ["not evidence", "../outside:lines:1-1", "absent.tex:lines:1-1", "source.tex:lines:2-9", "source.tex:unknown:x"])
def test_defects_require_existing_located_evidence(tmp_path, reference):
    (tmp_path / "source.tex").write_text("one line\n")
    verdict = {"ok": False, "reasoning": "defect", "concerns": [], "defects": [{"category": "scientific_fact", "severity": "major", "repair": "Correct the stated value", "source_evidence": [reference]}]}
    path = tmp_path / "verdict.json"
    path.write_text(json.dumps(verdict))
    with pytest.raises(ReviewError, match="source_evidence"):
        parse_verdict(path, require_structured=True)


def test_structured_repair_reaches_retry(tmp_path):
    (tmp_path / "source.tex").write_text("one line\n")
    path = tmp_path / "verdict.json"
    path.write_text(json.dumps({"ok": False, "reasoning": "defect", "concerns": [], "defects": [{"category": "scientific_fact", "severity": "major", "repair": "Correct the stated value", "source_evidence": ["source.tex:lines:1-1"]}]}))
    assert "Correct the stated value" in parse_verdict(path, require_structured=True).remedy()


def test_source_resume_hash_includes_assets(tmp_path):
    (tmp_path / "original").mkdir()
    source = tmp_path / "original" / "main.tex"
    source.write_text("one")
    digest = source_fingerprint(tmp_path)
    source.write_text("two")
    assert source_fingerprint(tmp_path) != digest


def test_stage_invalidation_survives_sorted_json_reload(tmp_path):
    from paperbench_harbor.construction.core.state import StageState

    path = tmp_path / "stages.json"
    state = StageState(path, {})
    for stage in ("evidence", "build", "validate", "review", "delivery"):
        state.save(stage, "passed", "in", "out")
    resumed = StageState(path, {})
    resumed.save("build", "running", "new")
    assert set(resumed.record["stages"]) == {"evidence", "build"}


def test_short_protocol_cannot_use_private_long_overview(tmp_path):
    from test_papersmith_evidence import evidence_fixture, write_evidence

    from paperbench_harbor.construction.core.evidence import validate_research_evidence
    from paperbench_harbor.construction.core.knowledge import PACKAGES

    data = evidence_fixture(tmp_path, PACKAGES[0])
    data["question"]["public_support"][0]["path"] = "resources/research_overview_long.md"
    write_evidence(tmp_path, data)
    with pytest.raises(ValueError, match="private long overview"):
        validate_research_evidence(tmp_path, "lifesci", "experimental")


def test_public_binding_sync_never_rebinds_private_source(tmp_path):
    from test_papersmith_evidence import evidence_fixture

    from paperbench_harbor.construction.core.evidence import synchronize_research_materials
    from paperbench_harbor.construction.core.knowledge import PACKAGES

    data = evidence_fixture(tmp_path, PACKAGES[0])
    data["question"]["public_support"][0]["sha256"] = "truncated model hash"
    (tmp_path / "original" / "research_evidence.json").write_text(json.dumps(data))
    (tmp_path / "resources" / "research_overview_short.md").write_text("Revised public explanation\n")
    synchronize_research_materials(tmp_path)
    updated = json.loads((tmp_path / "original" / "research_evidence.json").read_text())
    assert updated["question"]["sources"] == data["question"]["sources"]
    assert updated["question"]["public_support"][0]["sha256"] == file_hash(tmp_path / "resources" / "research_overview_short.md")
    assert isinstance(json.loads((tmp_path / "resources" / "writing_requirements.json").read_text()), list)
    assert json.loads((tmp_path / "resources" / "writing_requirements.json").read_text())[0]["public_support"][0]["path"] == "/workspace/materials/research_overview.md"


def test_local_class_dependency_styles_are_included(tmp_path):
    from paperbench_harbor.adapters.paperwrite_bench.converter import _referenced_style_files

    template = tmp_path / "template.tex"
    template.write_text("\\documentclass{aa}\n")
    (tmp_path / "aa.cls").write_text("\\RequirePackage[modulo]{linenoaa}\n")
    (tmp_path / "linenoaa.sty").write_text("\\RequirePackage{nested}\n")
    (tmp_path / "nested.sty").write_text("\\RequirePackage{linenoaa}\n")
    assert set(_referenced_style_files(template, prefer_local_styles=True)) == {"linenoaa", "nested"}


def test_whole_image_defect_locator_is_checked(tmp_path):
    path = tmp_path / "verdict.json"
    (tmp_path / "figure.png").write_bytes(b"image fixture")
    path.write_text(json.dumps({"ok": False, "reasoning": "cannot inspect plotted values", "concerns": [],
                               "defects": [{"category": "material_insufficiency", "severity": "major",
                                            "repair": "Supply inspectable evidence", "source_evidence": ["figure.png:image"]}]}))
    assert not parse_verdict(path, require_structured=True).ok
    (tmp_path / "figure.png").unlink()
    with pytest.raises(ReviewError):
        parse_verdict(path, require_structured=True)


@pytest.mark.parametrize("bad", ["not json", "[]", "null", '{"verifier_result":null}'])
def test_malformed_harbor_result_is_persisted(monkeypatch, tmp_path, bad):
    task = tmp_path / "task"
    (task / "environment").mkdir(parents=True)
    review = tmp_path / "review.json"
    review.write_text('{"ok":true}')
    output = tmp_path / "trial"
    monkeypatch.setattr("paperbench_harbor.construction.core.trial.assert_valid_task_contract", lambda task: None)
    def fake_run(command, **kwargs):
        result = output / "writer-trial" / "attempt" / "result.json"
        result.parent.mkdir(parents=True)
        result.write_text(bad)
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(subprocess, "run", fake_run)
    record = run_trial(task, output=output, model="fixture/model", agent="codex", agent_version="1", knowledge={}, material_review={"ok": True}, review_path=review, timeout=1)
    assert record["status"] == "blocked"
    assert json.loads((output / "trial-evidence.json").read_text())["exception"].startswith("invalid_trial_evidence:")


def test_native_harbor_resolves_auth_template(monkeypatch):
    env = pytest.importorskip("harbor.utils.env")
    monkeypatch.setenv("CODEX_AUTH_JSON_PATH", "/fixture/auth-location")
    assert env.resolve_env_vars({"CODEX_AUTH_JSON_PATH": "${CODEX_AUTH_JSON_PATH}"}) == {"CODEX_AUTH_JSON_PATH": "/fixture/auth-location"}


def test_batch_classifies_by_task_identity():
    outcomes = [{"paper_id": "p1", "status": "ok"}, {"paper_id": "p2", "status": "ok"}]
    manifest = [{"upstream_paper_id": "p1", "task_id": "t1"}, {"upstream_paper_id": "p2", "task_id": "t2"}]
    trials = [{"task_id": "t2", "status": "blocked", "exception": "environment"}, {"task_id": "t1", "status": "completed", "exception": None, "contract_reward": 0, "diagnosis": "model_or_task_unresolved"}]
    counts = runner.batch_counts(outcomes, trials, manifest, 2)
    assert (counts["failed_count"], counts["blocked_count"], counts["approved_count"], counts["unfinished_count"]) == (1, 1, 0, 2)


def test_repeated_archive_staging_preserves_previous_version(monkeypatch, tmp_path):
    archive = tmp_path / "source-archive"
    archive.mkdir()
    (archive / "manifest.json").write_text("previous")
    def build(*, output_dir, **options):
        output_dir.mkdir()
        (output_dir / "manifest.json").write_text("current")
    monkeypatch.setattr(runner, "build_source_archive", build)
    assert runner._stage_source_archive(tmp_path) == archive
    assert (archive / "manifest.json").read_text() == "current"
    assert [p.read_text() for p in (tmp_path / "archive-history").glob("*/manifest.json")] == ["previous"]


def test_failed_archive_rebuild_keeps_active_archive(monkeypatch, tmp_path):
    archive = tmp_path / "source-archive"
    archive.mkdir()
    (archive / "manifest.json").write_text("previous")
    def fail(**kwargs):
        raise ValueError("archive build failed")
    monkeypatch.setattr(runner, "build_source_archive", fail)
    with pytest.raises(ValueError, match="archive build failed"):
        runner._stage_source_archive(tmp_path)
    assert (archive / "manifest.json").read_text() == "previous"
