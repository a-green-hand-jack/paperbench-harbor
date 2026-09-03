from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest

from scripts import run_release_workflow as workflow

REVISION = "a" * 40
DATASET_REVISION = "b" * 40
MODEL = "openai/gpt-5.5"


def _write_dataset(root: Path, *, task_id: str, paper_id: str) -> None:
    task = root / task_id
    task.mkdir(parents=True)
    (task / "task.toml").write_text(f"[task]\nid = '{task_id}'\n", encoding="utf-8")
    (root / "dataset-manifest.jsonl").write_text(
        json.dumps({"task_id": task_id, "upstream_paper_id": paper_id}) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archive_plan(tmp_path: Path, *, dataset_root: Path) -> Path:
    source = tmp_path / "source-input.txt"
    pdf = tmp_path / "paper.pdf"
    source.write_text("source material", encoding="utf-8")
    pdf.write_bytes(b"pdf bytes")
    plan = {
        "schema_version": 1,
        "release": {
            "dataset_repo": "https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam",
            "dataset_revision": DATASET_REVISION,
            "dataset_tag": "v0.4.1",
            "source_archive_repo": (
                "https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam-Source-Archive"
            ),
            "source_archive_tag": "v0.4.1-lifesci-source",
            "converter_revision": REVISION,
            "workflow_revision": REVISION,
        },
        "papers": [
            {
                "paper_id": "lspr:paper_1",
                "identity": {
                    "title": "A LifeSci paper",
                    "source_kind": "venue-only",
                    "arxiv_id": "not-applicable",
                    "arxiv_version": "not-applicable",
                    "abstract_url": "not-applicable",
                    "eprint_url": "not-applicable",
                    "pdf_url": "https://example.test/paper.pdf",
                    "license": "CC BY 4.0",
                    "source_exclusion_reason": "published through the venue only",
                },
                "code": {
                    "status": "not-applicable",
                    "repository_url": "not-applicable",
                    "revision": "not-applicable",
                    "license": "not-applicable",
                    "exclusion_reason": "the paper declares no code repository",
                },
                "workflow": {
                    "kind": "papersmith",
                    "revision": REVISION,
                    "fetched_at": "2026-09-03T00:00:00Z",
                    "source_archive_manifest_revision": "v0.4.1-lifesci-source",
                },
                "inputs": [
                    {
                        "kind": "source-tree-manifest",
                        "source_url": "https://example.test/source-tree-manifest",
                        "fetched_at": "2026-09-03T00:00:00Z",
                        "sha256": _sha256(source),
                        "bytes": source.stat().st_size,
                        "redistribution": "archived",
                        "archive_path": "papers/lspr-paper-1/source-tree-manifest.txt",
                        "source_path": str(source),
                        "exclusion_reason": None,
                    },
                    {
                        "kind": "pdf",
                        "source_url": "https://example.test/paper.pdf",
                        "fetched_at": "2026-09-03T00:00:00Z",
                        "sha256": _sha256(pdf),
                        "bytes": pdf.stat().st_size,
                        "redistribution": "locator-only",
                        "archive_path": None,
                        "source_path": str(pdf),
                        "exclusion_reason": "license terms do not permit redistribution",
                    }
                ],
            }
        ],
        "tasks": [
            {
                "task_id": "lspr-0001",
                "task_path": "lspr-0001",
                "config": "lifesci-paperrecon-short",
                "paper_id": "lspr:paper_1",
                "dataset_revision": DATASET_REVISION,
                "converter_revision": REVISION,
            }
        ],
    }
    path = tmp_path / "source-archive-plan.json"
    path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return path


def _workflow_spec(
    tmp_path: Path,
    *,
    paperwrite_source: Path,
    paperwrite_dataset: Path,
    lifesci_source: Path,
    lifesci_dataset: Path,
    plan: Path,
) -> Path:
    value = {
        "schema_version": 1,
        "release": {
            "converter_revision": REVISION,
            "workflow_revision": REVISION,
            "reviewer_model": MODEL,
            "max_concurrent_audits": 2,
        },
        "audits": [
            {
                "config": "paperwrite-bench-short",
                "benchmark": "paperwrite-bench",
                "source": str(paperwrite_source),
                "dataset": str(paperwrite_dataset),
                "upstream_revision": "upstream-paperwrite",
                "overview": "short",
                "protocol": None,
                "workers": 3,
            },
            {
                "config": "lifesci-paperrecon-short",
                "benchmark": "lifesci-paperrecon",
                "source": str(lifesci_source),
                "dataset": str(lifesci_dataset),
                "upstream_revision": REVISION,
                "overview": "short",
                "protocol": None,
                "workers": 2,
            },
        ],
        "source_archive": {"plan": str(plan), "dataset": str(lifesci_dataset)},
    }
    path = tmp_path / "release-workflow.json"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _summary(audit: workflow.AuditSpec) -> dict[str, object]:
    return {
        "total_tasks": 1,
        "passed_tasks": 1,
        "failed_tasks": 0,
        "determinism_ok": True,
        "semantic_reviews": 1,
        "semantic_review_failures": 0,
        "evidence": {
            "semantic_review_required": True,
            "reviewer_model": MODEL,
            "converter_revision": REVISION,
            "upstream_revision": audit.upstream_revision,
            "upstream_tree_sha256": workflow._tree_digest(audit.source),
            "dataset_tree_sha256": workflow._tree_digest(audit.dataset),
        },
    }


def test_runs_all_audits_concurrently_then_records_the_archive_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paperwrite_source = tmp_path / "paperwrite-source"
    lifesci_source = tmp_path / "lifesci-source"
    paperwrite_source.mkdir()
    lifesci_source.mkdir()
    (paperwrite_source / "source.txt").write_text("pwb", encoding="utf-8")
    (lifesci_source / "source.txt").write_text("lspr", encoding="utf-8")
    paperwrite_dataset = tmp_path / "paperwrite-dataset"
    lifesci_dataset = tmp_path / "lifesci-dataset"
    _write_dataset(paperwrite_dataset, task_id="pwb-0001", paper_id="paper_1")
    _write_dataset(lifesci_dataset, task_id="lspr-0001", paper_id="paper_1")
    plan = _archive_plan(tmp_path, dataset_root=lifesci_dataset)
    spec = workflow.load_workflow_spec(
        _workflow_spec(
            tmp_path,
            paperwrite_source=paperwrite_source,
            paperwrite_dataset=paperwrite_dataset,
            lifesci_source=lifesci_source,
            lifesci_dataset=lifesci_dataset,
            plan=plan,
        )
    )
    monkeypatch.setattr(workflow, "_git_revision", lambda: REVISION)
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    active = 0
    peak_active = 0

    def fake_run_audit(audit: workflow.AuditSpec, *, output: Path, reviewer_model: str) -> Path:
        nonlocal active, peak_active
        assert reviewer_model == MODEL
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        barrier.wait(timeout=2)
        output.mkdir(parents=True)
        summary = output / "summary.json"
        summary.write_text(json.dumps(_summary(audit)), encoding="utf-8")
        with lock:
            active -= 1
        return summary

    monkeypatch.setattr(workflow, "_run_audit", fake_run_audit)
    evidence = tmp_path / "evidence" / "release-workflow.json"
    report = workflow.run_release_workflow(
        spec=spec,
        audit_output=tmp_path / "audits",
        archive_output=tmp_path / "archive",
        evidence_output=evidence,
    )

    assert peak_active == 2
    assert report["archive_report"]["release_gate"] == "passed"
    persisted = json.loads(evidence.read_text(encoding="utf-8"))
    assert [entry["config"] for entry in persisted["audits"]] == [
        "paperwrite-bench-short",
        "lifesci-paperrecon-short",
    ]
    assert persisted["source_archive_gate"]["configs"] == ["lifesci-paperrecon-short"]
    assert (tmp_path / "archive" / "registry" / "tasks.jsonl").is_file()


def test_rejects_incomplete_semantic_evidence_before_building_the_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "source.txt").write_text("source", encoding="utf-8")
    dataset = tmp_path / "dataset"
    _write_dataset(dataset, task_id="lspr-0001", paper_id="paper_1")
    plan = _archive_plan(tmp_path, dataset_root=dataset)
    raw_spec = {
        "schema_version": 1,
        "release": {
            "converter_revision": REVISION,
            "workflow_revision": REVISION,
            "reviewer_model": MODEL,
            "max_concurrent_audits": 1,
        },
        "audits": [
            {
                "config": "lifesci-paperrecon-short",
                "benchmark": "lifesci-paperrecon",
                "source": str(source),
                "dataset": str(dataset),
                "upstream_revision": REVISION,
                "overview": "short",
                "protocol": None,
                "workers": 1,
            }
        ],
        "source_archive": {"plan": str(plan), "dataset": str(dataset)},
    }
    spec_path = tmp_path / "workflow.json"
    spec_path.write_text(json.dumps(raw_spec), encoding="utf-8")
    spec = workflow.load_workflow_spec(spec_path)
    monkeypatch.setattr(workflow, "_git_revision", lambda: REVISION)

    def incomplete(audit: workflow.AuditSpec, *, output: Path, reviewer_model: str) -> Path:
        output.mkdir(parents=True)
        broken = _summary(audit)
        broken["semantic_reviews"] = 0
        summary = output / "summary.json"
        summary.write_text(json.dumps(broken), encoding="utf-8")
        return summary

    monkeypatch.setattr(workflow, "_run_audit", incomplete)
    archive = tmp_path / "archive"
    with pytest.raises(workflow.ReleaseWorkflowError, match="semantic_reviews=0"):
        workflow.run_release_workflow(
            spec=spec,
            audit_output=tmp_path / "audits",
            archive_output=archive,
            evidence_output=tmp_path / "evidence.json",
        )
    assert not (archive / "registry").exists()


def test_rejects_an_archive_tree_that_is_not_the_audited_task_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "source.txt").write_text("source", encoding="utf-8")
    archive_dataset = tmp_path / "archive-dataset"
    audited_dataset = tmp_path / "audited-dataset"
    _write_dataset(archive_dataset, task_id="lspr-0001", paper_id="paper_1")
    _write_dataset(audited_dataset, task_id="lspr-0001", paper_id="paper_1")
    plan = _archive_plan(tmp_path, dataset_root=archive_dataset)
    raw_spec = {
        "schema_version": 1,
        "release": {
            "converter_revision": REVISION,
            "workflow_revision": REVISION,
            "reviewer_model": MODEL,
            "max_concurrent_audits": 1,
        },
        "audits": [
            {
                "config": "lifesci-paperrecon-short",
                "benchmark": "lifesci-paperrecon",
                "source": str(source),
                "dataset": str(audited_dataset),
                "upstream_revision": REVISION,
                "overview": "short",
                "protocol": None,
                "workers": 1,
            }
        ],
        "source_archive": {"plan": str(plan), "dataset": str(archive_dataset)},
    }
    spec_path = tmp_path / "workflow.json"
    spec_path.write_text(json.dumps(raw_spec), encoding="utf-8")
    spec = workflow.load_workflow_spec(spec_path)
    monkeypatch.setattr(workflow, "_git_revision", lambda: REVISION)

    with pytest.raises(workflow.ReleaseWorkflowError, match="not the task audited"):
        workflow.run_release_workflow(
            spec=spec,
            audit_output=tmp_path / "audits",
            archive_output=tmp_path / "archive",
            evidence_output=tmp_path / "evidence.json",
        )
