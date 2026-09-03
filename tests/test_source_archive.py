from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperbench_harbor.provenance.archive import (
    ARCHIVE_MANIFEST_FILENAME,
    REGISTRY_FILENAME,
    build_source_archive,
    verify_source_archive,
)


def _task(
    release: Path,
    config: str,
    task_id: str,
    *,
    benchmark: str,
    upstream_id: str,
    protocol: str,
    extra: dict[str, object] | None = None,
) -> None:
    task_dir = release / config / task_id
    (task_dir / "tests" / "private").mkdir(parents=True)
    (task_dir / "task.toml").write_text("schema_version = '1.0'\n", encoding="utf-8")
    (task_dir / "instruction.md").write_text("Write a paper.\n", encoding="utf-8")
    (task_dir / "tests" / "private" / "source_manifest.json").write_text(
        json.dumps(
            {
                "benchmark": benchmark,
                "upstream_id": upstream_id,
                "protocol": protocol,
                "upstream_revision": "upstream-revision",
                "extra": extra or {},
            }
        ),
        encoding="utf-8",
    )


def _sources(tmp_path: Path) -> tuple[Path, Path, Path]:
    paperwrite = tmp_path / "paperwrite"
    (paperwrite / "paper_1" / "original").mkdir(parents=True)
    (paperwrite / "paper_1" / "original" / "main.tex").write_text(
        "\\title{PaperWrite source}\n", encoding="utf-8"
    )

    paperwritingbench = tmp_path / "paperwritingbench"
    raw = paperwritingbench / "datasets" / "cvpr2025" / "papers" / "cvpr-id" / "raw_materials"
    raw.mkdir(parents=True)
    (raw / "idea_sparse.md").write_text("Idea\n", encoding="utf-8")

    lifesci = tmp_path / "lifesci"
    original = lifesci / "paper_1" / "original"
    original.mkdir(parents=True)
    (original / "main.tex").write_text("\\title{LifeSci source}\n", encoding="utf-8")
    (original / "provenance.json").write_text(
        json.dumps(
            {
                "title": "LifeSci source",
                "arxiv_id": "2601.00001",
                "arxiv_version": "v2",
                "license_label": "CC BY 4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "source_url": "https://arxiv.org/e-print/2601.00001v2",
                "fetch_date": "2026-09-03",
                "code_repo": "https://github.com/example/repo",
                "code_commit": "abc123",
                "code_license": "MIT",
            }
        ),
        encoding="utf-8",
    )
    return paperwrite, paperwritingbench, lifesci


def test_builds_full_registry_and_source_only_archive(tmp_path: Path) -> None:
    release = tmp_path / "release"
    _task(
        release,
        "paperwrite-bench-short",
        "pwb-0001",
        benchmark="PaperWrite-Bench",
        upstream_id="paper_1",
        protocol="short",
    )
    _task(
        release,
        "paperwritingbench-sparse-plotoff",
        "pwbw-0001",
        benchmark="PaperWritingBench",
        upstream_id="cvpr-id",
        protocol="sparse-plotoff",
        extra={"venue": "cvpr2025"},
    )
    _task(
        release,
        "lifesci-paperrecon-short",
        "lspr-0001",
        benchmark="LifeSci-PaperRecon",
        upstream_id="paper_1",
        protocol="short",
    )
    _task(
        release,
        "hello-world",
        "hello-world-0001",
        benchmark="PaperBench Harbor",
        upstream_id="hello-world-0001",
        protocol="hello-world",
    )
    paperwrite, paperwritingbench, lifesci = _sources(tmp_path)
    output = tmp_path / "archive"

    result = build_source_archive(
        release_root=release,
        output_dir=output,
        dataset_repo="Jack-Jieke-Wu/Paper-Writing-Exam",
        dataset_revision="release-revision",
        converter_revision="converter-revision",
        paperwrite_source=paperwrite,
        paperwritingbench_source=paperwritingbench,
        lifesci_source=lifesci,
    )

    assert result == {"task_count": 4, "source_tree_count": 3, "source_file_count": 4}
    registry = [
        json.loads(line)
        for line in (output / "registry" / REGISTRY_FILENAME).read_text(encoding="utf-8").splitlines()
    ]
    assert [record["dataset"]["task_id"] for record in registry] == [
        "hello-world-0001",
        "lspr-0001",
        "pwb-0001",
        "pwbw-0001",
    ]
    assert registry[0]["source_archive"]["status"] == "not_applicable"
    lifesci_record = registry[1]
    assert lifesci_record["paper"]["arxiv_id"] == "2601.00001"
    assert lifesci_record["source_archive"]["dataset_path"] == (
        "sources/lifesci-paperrecon/paper_1/original"
    )
    assert not (output / "paperwrite-bench-short").exists()
    assert not list(output.rglob("task.toml"))
    assert (output / "sources" / "paperwrite-bench" / "paper_1" / "original" / "main.tex").is_file()
    assert (output / "sources" / "paperwritingbench" / "cvpr2025" / "papers" / "cvpr-id").is_dir()
    assert len((output / "manifests" / ARCHIVE_MANIFEST_FILENAME).read_text().splitlines()) == 4
    assert verify_source_archive(output) == {"task_count": 4, "source_file_count": 4}


def test_verification_rejects_tampered_archived_file(tmp_path: Path) -> None:
    release = tmp_path / "release"
    _task(
        release,
        "paperwrite-bench-short",
        "pwb-0001",
        benchmark="PaperWrite-Bench",
        upstream_id="paper_1",
        protocol="short",
    )
    paperwrite, paperwritingbench, lifesci = _sources(tmp_path)
    output = tmp_path / "archive"
    build_source_archive(
        release_root=release,
        output_dir=output,
        dataset_repo="Jack-Jieke-Wu/Paper-Writing-Exam",
        dataset_revision="release-revision",
        converter_revision="converter-revision",
        paperwrite_source=paperwrite,
        paperwritingbench_source=paperwritingbench,
        lifesci_source=lifesci,
    )
    (output / "sources" / "paperwrite-bench" / "paper_1" / "original" / "main.tex").write_text(
        "tampered\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="archive tree hash mismatch"):
        verify_source_archive(output)
