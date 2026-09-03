import json
from pathlib import Path

import pytest

from scripts import publish_paperrecon_release as publisher


def _run(root: Path, domain: str, count: int = 20) -> None:
    dataset = root / f"{publisher.CONFIGS[domain]}"
    archive = root / "source-archive"
    dataset.mkdir(parents=True)
    archive.mkdir()
    (dataset / "dataset-manifest.jsonl").write_text("{}\n" * count, encoding="utf-8")
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
        json.dumps({"built_tasks": count, "converted_tasks": count, "dataset": str(dataset), "source_archive": str(archive)}),
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
    assert not any("tag" in command for command in calls)
