import json
from pathlib import Path

import pytest

from paperbench_harbor.construction.core.knowledge import PACKAGES
from scripts import publish_paperrecon_release as publisher


def _run(root: Path, domain: str, count: int = 20) -> None:
    dataset = root / "dataset" / publisher.CONFIGS[domain]
    archive = root / "source-archive"
    dataset.mkdir(parents=True)
    archive.mkdir()
    package = next(p for p in PACKAGES if p.domain == domain)
    execution = {"trial_model": "fixture/model", "trial_agent": "codex", "trial_agent_version": "1.0", "reviewer_model": "fixture/reviewer"}
    (root / "execution.json").write_text(json.dumps(execution))
    entries = [{"task_id": f"task-{i}", "upstream_paper_id": f"paper_{i}"} for i in range(count)]
    (dataset / "dataset-manifest.jsonl").write_text("\n".join(map(json.dumps, entries)) + "\n", encoding="utf-8")
    trials = []
    for entry in entries:
        task = dataset / entry["task_id"]
        task.mkdir()
        (task / "instruction.md").write_text("Fixture task")
        trial_root = root / "trials" / task.name / "1"
        result = trial_root / "writer-trial" / "attempt" / "result.json"
        result.parent.mkdir(parents=True)
        result.write_text(json.dumps({"started_at": "2026-09-05T00:00:00", "finished_at": "2026-09-05T00:01:00",
                                     "task_name": task.name, "task_id": {"path": str(task.resolve())},
                                     "exception_info": None, "agent_info": {"name": "codex", "version": "1.0", "model_info": {"provider": "fixture", "name": "model"}},
                                     "config": {"agent": {"name": "codex", "model_name": "fixture/model", "kwargs": {"version": "1.0"}},
                                                "environment": {"type": "docker", "mounts": None}, "verifier": {"disable": False}},
                                     "verifier_result": {"rewards": {"reward": 1}}}))
        trajectory = result.parent / "agent" / "trajectory.json"
        trajectory.parent.mkdir()
        trajectory.write_text('{"steps":[{"role":"agent","content":"Fixture trace"}]}')
        paper = root / "corpus" / entry["upstream_paper_id"]
        (paper / "original").mkdir(parents=True)
        (paper / "original" / "main.tex").write_text("Source fixture")
        review = paper / "original" / "reconstructability_review.json"
        review.write_text(json.dumps({"ok": True, "materials_sha256": publisher._tree_digest(paper),
                                     "model": "fixture/reviewer", "knowledge": package.as_dict()}))
        record = {"task_id": task.name, "task_sha256": publisher._tree_digest(task),
                       "diagnosis": "contract_passed_material_review_passed",
                       "status": "completed", "exception": None, "returncode": 0,
                       "review_path": str(review), "review_sha256": publisher._digest(review),
                       "model": "fixture/model", "agent": "codex", "agent_version": "1.0", "knowledge": package.as_dict(),
                       "trajectories": [{"path": str(trajectory), "sha256": publisher._digest(trajectory)}],
                       "result_path": str(result), "result_sha256": publisher._digest(result)}
        evidence = trial_root / "trial-evidence.json"
        evidence.write_text(json.dumps(record))
        trials.append({**record, "evidence_path": str(evidence), "evidence_sha256": publisher._digest(evidence)})
    (archive / "manifest.json").write_text("{}\n", encoding="utf-8")
    (root / "reports" / "fidelity").mkdir(parents=True)
    (root / "reports" / "fidelity" / "summary.json").write_text(
        json.dumps(
            {
                "total_tasks": count,
                "passed_tasks": count,
                "failed_tasks": 0,
                "determinism_ok": True,
                "semantic_reviews": count,
                "semantic_review_failures": 0,
            }
        ),
        encoding="utf-8",
    )
    (root / "run-summary.json").write_text(
        json.dumps({"built_tasks": count, "converted_tasks": count, "dataset": str(dataset), "source_archive": str(archive),
                    "status": "passed", "approved_count": count, "trials": trials,
                    "research_type": package.research_type, "execution_sha256": publisher._digest(root / "execution.json"),
                    "dataset_tree_sha256": publisher._tree_digest(dataset),
                    "archive_tree_sha256": publisher._tree_digest(archive),
                    "fidelity_summary_sha256": publisher._digest(root / "reports" / "fidelity" / "summary.json")}),
        encoding="utf-8",
    )


def test_gate_requires_all_domains(tmp_path: Path) -> None:
    for domain in publisher.DOMAINS[1:]:
        _run(tmp_path / domain, domain)
    with pytest.raises(publisher.ReleasePublisherError, match="physics"):
        publisher.load_gate({domain: tmp_path / domain for domain in publisher.DOMAINS[1:]})


def test_gate_rejects_failed_fidelity(tmp_path: Path) -> None:
    roots = {}
    for domain in publisher.DOMAINS:
        root = tmp_path / domain
        _run(root, domain)
        roots[domain] = root
    summary = roots["physics"] / "reports" / "fidelity" / "summary.json"
    data = json.loads(summary.read_text(encoding="utf-8"))
    data["failed_tasks"] = 1
    summary.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(publisher.ReleasePublisherError, match="physics fidelity"):
        publisher.load_gate(roots)


def test_gate_returns_immutable_digests(tmp_path: Path) -> None:
    roots = {}
    for domain in publisher.DOMAINS:
        root = tmp_path / domain
        _run(root, domain)
        roots[domain] = root
    evidence = publisher.load_gate(roots)
    assert evidence["minimum_tasks_per_domain"] == 20
    assert {item["config"] for item in evidence["domains"]} == {
        publisher.CONFIGS[domain] for domain in publisher.DOMAINS
    }
    assert all(len(item["dataset_tree_sha256"]) == 64 for item in evidence["domains"])


def test_publish_is_dry_tag_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    roots = {}
    for domain in publisher.DOMAINS:
        root = tmp_path / domain
        _run(root, domain)
        roots[domain] = root
    calls: list[list[str]] = []
    monkeypatch.setattr(publisher, "_run", lambda command: calls.append(command) or "ok")
    result = publisher.publish(
        publisher.load_gate(roots),
        task_repo="u/tasks",
        archive_repo="u/archive",
        candidate_revision="candidate",
        release_tag="v0.1.0",
        publish_public=False,
        evidence_path=tmp_path / "evidence.json",
    )
    assert result["published"] is False
    assert result["uploaded"] is False
    assert calls == []


def test_stale_artifact_cannot_reuse_gate(tmp_path):
    roots = {domain: tmp_path / domain for domain in publisher.DOMAINS}
    for domain, root in roots.items():
        _run(root, domain)
    (roots["physics"] / "dataset" / publisher.CONFIGS["physics"] / "task-0" / "instruction.md").write_text("changed")
    with pytest.raises(publisher.ReleasePublisherError, match="stale evidence binding"):
        publisher.load_gate(roots)


def test_publish_does_not_imply_upload(tmp_path):
    with pytest.raises(publisher.ReleasePublisherError, match="explicit --upload-candidate"):
        publisher.publish({}, task_repo="u/tasks", archive_repo="u/archive", candidate_revision="candidate",
                          release_tag="v1", publish_public=True, evidence_path=tmp_path / "evidence.json")
