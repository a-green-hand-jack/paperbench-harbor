"""The generic onboarding hand-off produces auditable tasks from approved data."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from paperbench_harbor.onboarding.candidate import BenchmarkCandidate, OnboardingError
from paperbench_harbor.onboarding.converter import (
    OnboardedConversionConfig,
    audit_approved_benchmark,
    convert_approved_benchmark,
)
from paperbench_harbor.onboarding.layout import load_approved_layout, parse_layout_spec


def _candidate() -> BenchmarkCandidate:
    return BenchmarkCandidate(
        benchmark_id="example-writing",
        source_repository="https://github.com/example/example-writing",
        source_revision="a" * 40,
        source_license="MIT",
        dataset_manifest_url=(
            "https://raw.githubusercontent.com/example/example-writing/" + "a" * 40 + "/samples.json"
        ),
        dataset_manifest_sha256="b" * 64,
        benchmark_license="CC BY 4.0",
        sample_count=1,
        writer_deliverable=True,
        requires_experiments=False,
        requires_code=False,
        input_protocol="fixed materials to manuscript",
        evaluator="official fixed evaluator",
        selection_record_url="https://github.com/a-green-hand-jack/paperbench-harbor/issues/2",
        rationale="fixed public sample",
    )


def _rule(source: str, target: str) -> dict[str, object]:
    return {
        "source": source,
        "target": target,
        "kind": "file",
        "required": True,
        "extra_targets": [],
        "tree_excludes": [".git", "__pycache__"],
        "tree_exclude_globs": [],
        "may_be_rewritten": False,
        "protocols": [],
    }


def _layout() -> dict[str, object]:
    return {
        "schema_version": 1,
        "candidate_id": "example-writing",
        "identity": {
            "benchmark": "Example Writing",
            "task_id_prefix": "example",
            "tags": ["paper-writing"],
            "relevant_experience": "scientific writing",
        },
        "paper_glob": "papers/*",
        "discovery_marker": "ground/main.tex",
        "public": [
            _rule("writer/overview.md", "environment/materials/research_overview.md"),
            _rule("writer/template.tex", "environment/materials/template.tex"),
            _rule("writer/references.bib", "environment/materials/references.bib"),
        ],
        "private": [_rule("ground/main.tex", "solution/private/main.tex")],
        "forbidden_public_names": ["main.pdf", "provenance.json"],
        "writer_instructions": "Use only the supplied evidence.",
        "render": {"category": "research-writing", "num_page": "4", "column": "single-column"},
    }


def _source(root: Path) -> Path:
    paper = root / "papers" / "sample-one"
    (paper / "writer").mkdir(parents=True)
    (paper / "ground").mkdir()
    (paper / "writer" / "overview.md").write_text("# Idea\n", encoding="utf-8")
    (paper / "writer" / "template.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\end{document}\n", encoding="utf-8"
    )
    (paper / "writer" / "references.bib").write_text("", encoding="utf-8")
    (paper / "ground" / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nGround truth.\\end{document}\n",
        encoding="utf-8",
    )
    for command in (
        ["git", "init", "--quiet"],
        ["git", "config", "user.email", "tests@example.invalid"],
        ["git", "config", "user.name", "Tests"],
        ["git", "add", "."],
        ["git", "commit", "--quiet", "-m", "source"],
    ):
        subprocess.run(command, cwd=root, check=True, capture_output=True)
    return root


def _approved(tmp_path: Path, candidate: BenchmarkCandidate):
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate.as_dict(), sort_keys=True) + "\n", encoding="utf-8")
    layout_path = tmp_path / "layout.json"
    layout_path.write_text(json.dumps(_layout(), sort_keys=True) + "\n", encoding="utf-8")
    approval = tmp_path / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "candidate_sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
                "layout_spec_sha256": hashlib.sha256(layout_path.read_bytes()).hexdigest(),
                "reviewer": "reviewer",
            }
        ),
        encoding="utf-8",
    )
    return candidate, candidate_path, layout_path, approval


def test_approved_layout_generates_and_audits_a_task(tmp_path: Path) -> None:
    source = _source(tmp_path / "source")
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout.strip()
    candidate = replace(_candidate(), source_revision=revision)
    candidate, candidate_path, layout_path, approval = _approved(tmp_path, candidate)
    approved = load_approved_layout(
        layout_path,
        candidate_path=candidate_path,
        approval_path=approval,
        candidate=candidate,
    )
    config = OnboardedConversionConfig(
        source=source,
        output_dir=tmp_path / "out",
        upstream_revision=revision,
        candidate=candidate,
        approved_layout=approved,
    )
    assert convert_approved_benchmark(config) == 1
    reports = audit_approved_benchmark(config, semantic_review=False)
    assert [report.ok for report in reports] == [True]
    assert (tmp_path / "out" / "example-0001" / "environment" / "materials" / "AGENTS.md").is_file()


def test_layout_requires_the_generic_writer_and_oracle_contract(tmp_path: Path) -> None:
    candidate = _candidate()
    layout = _layout()
    layout["public"] = layout["public"][:-1]  # type: ignore[index]
    path = tmp_path / "layout.json"
    path.write_text(json.dumps(layout), encoding="utf-8")
    with pytest.raises(OnboardingError, match="required public targets"):
        parse_layout_spec(path, candidate=candidate)
