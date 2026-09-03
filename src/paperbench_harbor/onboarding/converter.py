"""Materialize an approved generic layout into Harbor tasks and audit it.

This is intentionally a modest common converter.  A layout can route fixed
paper materials without a bespoke adapter; benchmarks that need a real parser
or other normalization retain a named adapter hook instead of hiding code in
their JSON proposal.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from paperbench_harbor.adapters.core.convert import (
    assert_source_tree_unchanged,
    create_template_environment,
    load_dataset_manifest,
    prepare_task_directories,
    prepare_task_output,
    render_templates,
    source_tree_sha256,
    task_id_for,
    write_dataset_manifest,
)
from paperbench_harbor.adapters.spec import find_paper_dirs, stage_declared_copies
from paperbench_harbor.common.audit import audit_forbidden_names
from paperbench_harbor.common.manifest import write_source_manifest
from paperbench_harbor.common.task_contract import assert_valid_task_contract
from paperbench_harbor.fidelity.audit import summarize
from paperbench_harbor.fidelity.dataset import audit_dataset, format_failures
from paperbench_harbor.onboarding.candidate import BenchmarkCandidate
from paperbench_harbor.onboarding.layout import ApprovedLayout

_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "common" / "templates"
_TASK_TEMPLATES = {
    "task.toml": "task.toml.j2",
    "instruction.md": "instruction.md.j2",
    "environment/Dockerfile": "environment.Dockerfile.j2",
    "tests/Dockerfile": "tests.Dockerfile.j2",
    "tests/test.sh": "test.sh.j2",
    "tests/test_state.py": "test_state.py.j2",
    "solution/solve.sh": "solve.sh.j2",
    "solution/normalize.py": "normalize.py.j2",
}


@dataclass(frozen=True)
class OnboardedConversionConfig:
    source: Path
    output_dir: Path
    upstream_revision: str
    candidate: BenchmarkCandidate
    approved_layout: ApprovedLayout
    overwrite: bool = False


def _assert_pinned_source(config: OnboardedConversionConfig) -> None:
    """Tie the local source tree to the independently verified Git revision."""

    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=config.source,
            check=True,
            capture_output=True,
            encoding="utf-8",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError("generic onboarding source must be a Git checkout at the approved revision") from error
    if config.upstream_revision != config.candidate.source_revision or revision != config.candidate.source_revision:
        raise ValueError("generic onboarding source revision does not match the independently verified candidate")


def _render_task(config: OnboardedConversionConfig, paper_dir: Path, task_dir: Path, task_id: str) -> None:
    layout = config.approved_layout.layout
    directories = prepare_task_directories(task_dir)
    public_files, material_provenance = stage_declared_copies(layout, paper_dir, task_dir)
    private_files, _ = stage_declared_copies(layout, paper_dir, task_dir, private=True)
    agents = directories.environment / "materials" / "AGENTS.md"
    agents.parent.mkdir(parents=True, exist_ok=True)
    agents.write_text(config.approved_layout.writer_instructions + "\n", encoding="utf-8")
    public_files.append(agents)
    audit_forbidden_names(directories.environment, set(layout.forbidden_public_names))

    materials = directories.environment / "materials"
    context = {
        "difficulty_explanation": "Writing a faithful scientific paper from fixed public materials.",
        "solution_explanation": "The oracle normalizes the fixed ground-truth source into the submission contract.",
        "verification_explanation": "The verifier recompiles main.tex without shell escape and checks cited bibliography keys.",
        "num_page": layout.render.num_page,
        "column": layout.render.column,
        "column_type": layout.render.column,
        "has_code": (materials / "code").is_dir(),
        "has_figures": (materials / "figures").is_dir(),
        "has_tables": (materials / "tables").is_dir(),
        "agents_md": config.approved_layout.writer_instructions,
        "grader_module": "",
        "include_paper_orchestra": False,
        "category": layout.render.category,
        "tags_toml": json.dumps(list(layout.identity.tags)),
        "relevant_experience": layout.identity.relevant_experience,
    }
    render_templates(
        create_template_environment(_TEMPLATES_DIR), task_dir, templates=_TASK_TEMPLATES, context=context
    )
    assert_valid_task_contract(task_dir)
    write_source_manifest(
        destination=directories.tests_private / "source_manifest.json",
        benchmark=layout.benchmark,
        upstream_id=paper_dir.name,
        protocol="",
        upstream_revision=config.upstream_revision,
        public_files=public_files,
        private_files=private_files,
        source_root=config.source,
        material_provenance=material_provenance,
        extra={
            "task_id": task_id,
            "candidate_id": config.candidate.benchmark_id,
            "candidate_source_revision": config.candidate.source_revision,
            "layout_schema_version": 1,
        },
    )
    for script in (directories.solution / "solve.sh", directories.tests / "test.sh"):
        script.chmod(0o755)


def convert_approved_benchmark(config: OnboardedConversionConfig) -> int:
    """Generate tasks only from an already verified and approved layout."""

    if not config.upstream_revision:
        raise ValueError("upstream_revision must be non-empty")
    _assert_pinned_source(config)
    source_digest = source_tree_sha256(config.source)
    layout = config.approved_layout.layout
    papers = find_paper_dirs(layout, config.source)
    if not papers:
        raise ValueError("approved layout did not discover any source papers")
    if len(papers) != config.candidate.sample_count:
        raise ValueError(
            "approved layout discovery count does not match the independently verified candidate "
            f"({len(papers)} != {config.candidate.sample_count})"
        )
    config.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = config.output_dir / "dataset-manifest.jsonl"
    manifest = load_dataset_manifest(manifest_path)
    converted = 0
    for index, paper_dir in enumerate(papers, start=1):
        task_id = task_id_for(layout.task_id_prefix, index)
        task_dir = config.output_dir / task_id
        if not prepare_task_output(task_dir, overwrite=config.overwrite):
            continue
        _render_task(config, paper_dir, task_dir, task_id)
        manifest[(task_id, paper_dir.name)] = {
            "task_id": task_id,
            "upstream_paper_id": paper_dir.name,
            "upstream_revision": config.upstream_revision,
        }
        converted += 1
    assert_source_tree_unchanged(config.source, source_digest)
    if converted:
        write_dataset_manifest(manifest_path, manifest)
    return converted


def audit_approved_benchmark(
    config: OnboardedConversionConfig,
    *,
    semantic_review: bool,
    reviewer_model: str | None = None,
    review_log_dir: Path | None = None,
) -> list:
    """Fail conversion completion when independent structural or semantic audit fails."""

    source_digest = source_tree_sha256(config.source)
    reports = audit_dataset(
        benchmark=config.approved_layout.layout.benchmark,
        source=config.source,
        dataset=config.output_dir,
        protocol="",
        layout_spec=config.approved_layout.layout,
        semantic_review=semantic_review,
        reviewer_model=reviewer_model,
        review_log_dir=review_log_dir,
    )
    failures = format_failures(reports)
    if failures:
        raise RuntimeError(failures)
    assert_source_tree_unchanged(config.source, source_digest)
    return reports


def determinism_approved_benchmark(config: OnboardedConversionConfig) -> dict[str, bool]:
    """Rebuild an approved source twice and retain only byte-level evidence."""

    with tempfile.TemporaryDirectory() as temporary:
        scratch = Path(temporary)
        outputs = []
        manifests = []
        for name in ("a", "b"):
            output = scratch / name
            convert_approved_benchmark(replace(config, output_dir=output, overwrite=True))
            outputs.append(source_tree_sha256(output))
            manifests.append((output / "dataset-manifest.jsonl").read_bytes())
    return {
        "determinism_tree_identical": outputs[0] == outputs[1],
        "determinism_manifest_identical": manifests[0] == manifests[1],
        "determinism_ok": outputs[0] == outputs[1] and manifests[0] == manifests[1],
    }


def write_approved_audit_evidence(
    config: OnboardedConversionConfig,
    reports: list,
    *,
    output: Path,
    determinism: dict[str, bool],
    reviewer_model: str,
) -> None:
    """Persist version-bound onboarding evidence outside the runnable task tree."""

    output.mkdir(parents=True, exist_ok=True)
    for report in reports:
        (output / f"{report.task_id}.json").write_text(
            json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8"
        )
    summary = summarize(reports)
    summary.update(determinism)
    summary["evidence"] = {
        "schema_version": 1,
        "benchmark": config.approved_layout.layout.benchmark,
        "upstream_revision": config.upstream_revision,
        "upstream_tree_sha256": source_tree_sha256(config.source),
        "dataset_tree_sha256": source_tree_sha256(config.output_dir),
        "candidate_sha256": config.approved_layout.candidate_sha256,
        "layout_spec_sha256": config.approved_layout.layout_spec_sha256,
        "approval_reviewer": config.approved_layout.reviewer,
        "semantic_review_required": True,
        "reviewer_model": reviewer_model,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
