from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment

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
from paperbench_harbor.adapters.paperwritingbench.spec import SPEC
from paperbench_harbor.adapters.spec import find_paper_dirs, stage_declared_copies
from paperbench_harbor.common.audit import audit_forbidden_names
from paperbench_harbor.common.manifest import write_source_manifest
from paperbench_harbor.common.task_contract import (
    assert_valid_task_contract,
    normalize_markdown_tables,
)

# Do not advertise protocols that have no faithful converter. New protocols are
# added only with their upstream fixture, layout rules, evaluator, and release
# regression -- a run-time NotImplementedError is not support.
SUPPORTED_PROTOCOLS = {"sparse-plotoff"}
FORBIDDEN_PUBLIC_NAMES = set(SPEC.forbidden_public_names)
_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "common" / "templates"
_CONFERENCE_TEMPLATES_DIR = (
    Path(__file__).resolve().parents[4] / "packaging" / "conference-templates"
)
_VENDOR_DIR = Path(__file__).resolve().parents[2] / "vendor"
_CITATION_CACHE_PATTERN = re.compile(r"^original_paper_gt_citations_.+\.json$")

_PAPER_ORDER_RE = re.compile(r"(\d+)")

_UPSTREAM_DATA_WARNINGS = {
    "pwbw-0007": "Some supplied visual comparisons are incomplete; do not infer missing rendered content.",
    "pwbw-0025": "One result-table header is under-specified upstream; neutral labels preserve its extra values.",
    "pwbw-0030": "Some supplied reenactment visual comparisons are incomplete; do not infer missing rendered content.",
    "pwbw-0048": "One supplied figure is visibly clipped upstream; use it only for what is actually visible.",
    "pwbw-0059": "One supplied figure is visibly incomplete upstream; use it only for what is actually visible.",
    "pwbw-0083": "One supplied figure is visibly incomplete upstream; use it only for what is actually visible.",
    "pwbw-0096": "A Markdown result-table alignment row was repaired mechanically from the upstream data.",
    "pwbw-0101": "A Figure 2 caption is truncated in the upstream source; do not complete it by inference.",
    "pwbw-0116": "The upstream experimental log does not state a batch size; do not report one as established fact.",
    "pwbw-0132": "A Markdown result-table alignment row was repaired mechanically from the upstream data.",
    "pwbw-0133": "Some Kendall tau cells use an ambiguous upstream sentinel; report the ambiguity rather than assigning meaning.",
    "pwbw-0144": "Some figure captions are truncated in the upstream source; do not complete them by inference.",
    "pwbw-0149": "Referenced audio supplements are absent upstream; do not claim observations from unavailable audio.",
    "pwbw-0165": "A Markdown table contained an escaped-pipe repair from upstream notation; preserve the literal mathematical meaning.",
    "pwbw-0170": "The supplied source omits central method definitions; restrict claims to the available description.",
    "pwbw-0171": "Some figure captions are truncated in the upstream source; do not complete them by inference.",
    "pwbw-0197": "A Markdown table contained an escaped-pipe repair from upstream notation; preserve the literal mathematical meaning.",
}


def _natural_sort_key(paper_id: str) -> tuple[object, ...]:
    return tuple(int(part) if part.isdigit() else part for part in _PAPER_ORDER_RE.split(paper_id))


@dataclass(frozen=True)
class PaperWritingBenchConversionConfig:
    source: Path
    output_dir: Path
    protocol: str = "sparse-plotoff"
    limit: int | None = None
    overwrite: bool = False
    upstream_revision: str | None = None


@dataclass(frozen=True)
class _PaperMetadata:
    paper_id: str
    venue: str
    num_figures: int
    num_tables: int


def _iter_papers(source: Path) -> list[tuple[Path, _PaperMetadata]]:
    papers: list[tuple[Path, _PaperMetadata]] = []
    for paper_dir in find_paper_dirs(SPEC, source):
        raw = paper_dir / "raw_materials"
        venue = paper_dir.relative_to(source).parts[0]
        figures = list((raw / "figures").glob("*.*")) if (raw / "figures").is_dir() else []
        metadata = _PaperMetadata(
            paper_id=paper_dir.name,
            venue=venue,
            num_figures=len(figures),
            num_tables=0,
        )
        papers.append((paper_dir, metadata))
    papers.sort(key=lambda item: (item[1].venue, _natural_sort_key(item[1].paper_id)))
    return papers


def _copy_public_materials(
    paper_dir: Path, task_dir: Path, venue: str
) -> tuple[list[Path], dict[Path, tuple[str, Path]], list[str]]:
    environment_dir = task_dir / "environment"
    materials_dir = environment_dir / "materials"
    materials_dir.mkdir(parents=True, exist_ok=True)
    copied, provenance = stage_declared_copies(SPEC, paper_dir, task_dir)
    warnings: list[str] = []

    experimental_log = materials_dir / "experimental_log.md"
    if experimental_log.is_file():
        warnings.extend(normalize_markdown_tables(experimental_log))

    template_dir = _CONFERENCE_TEMPLATES_DIR / venue
    if not template_dir.is_dir():
        raise FileNotFoundError(f"conference template missing: {template_dir}")
    destination = materials_dir / "conference_template"
    shutil.copytree(template_dir, destination)
    for path in destination.rglob("*"):
        if path.is_file():
            copied.append(path)
            provenance[path] = ("harbor_conference_template", template_dir / path.relative_to(destination))

    return copied, provenance, warnings


def _render_templates(
    environment: Environment,
    task_dir: Path,
    metadata: _PaperMetadata,
    has_figures: bool,
    has_upstream_warnings: bool,
) -> None:
    conference = metadata.venue.upper()
    difficulty_explanation = (
        "Writing a submission-ready conference paper from a sparse research idea and an "
        "experimental log requires scientific synthesis, faithful result reporting, LaTeX "
        "composition under conference guidelines, and literature review."
    )
    solution_explanation = (
        "The oracle assembles a complete conference-format paper from the raw materials and "
        "the verifier-only ground-truth citation cache, then compiles it in the submission "
        "contract."
    )
    verification_explanation = (
        "The verifier checks the submission contract, recompiles main.tex without shell "
        "escape or network, and asserts every citation key exists in references.bib."
    )
    context = {
        "difficulty_explanation": difficulty_explanation,
        "solution_explanation": solution_explanation,
        "verification_explanation": verification_explanation,
        "conference": conference,
        "venue": metadata.venue,
        "num_page": SPEC.render.num_page,
        "column": SPEC.render.column,
        "has_figures": has_figures,
        "has_upstream_warnings": has_upstream_warnings,
        "grader_module": SPEC.render.grader_module,
        "include_paper_orchestra": True,
        # Metadata previously hardcoded inside task.toml.j2; kept byte-identical
        # here now that the template takes them as parameters.
        "category": SPEC.render.category,
        "tags_toml": json.dumps(list(SPEC.identity.tags)),
        "relevant_experience": SPEC.identity.relevant_experience,
    }
    render_templates(
        environment,
        task_dir,
        templates={
            "task.toml": "task.toml.j2",
            "instruction.md": "instruction_pwbw.md.j2",
            "environment/Dockerfile": "environment.Dockerfile.j2",
            "tests/Dockerfile": "tests.Dockerfile.j2",
            "tests/test.sh": "test.sh.j2",
            "tests/test_state.py": "test_state.py.j2",
            "solution/solve.sh": "solve_pwbw.sh.j2",
            "solution/oracle_pwbw.py": "oracle_pwbw.py.j2",
            "tests/grader_pwbw.py": "grader_pwbw.py.j2",
        },
        context=context,
    )


def _convert_paper(
    environment: Environment,
    paper_dir: Path,
    metadata: _PaperMetadata,
    task_dir: Path,
    task_id: str,
    protocol: str,
    upstream_revision: str | None,
    source_root: Path,
) -> None:
    directories = prepare_task_directories(task_dir)
    environment_dir = directories.environment
    solution_dir = directories.solution
    tests_dir = directories.tests
    tests_private = directories.tests_private

    public_files, material_provenance, normalization_warnings = _copy_public_materials(
        paper_dir, task_dir, metadata.venue
    )
    upstream_warnings = [*normalization_warnings]
    known_warning = _UPSTREAM_DATA_WARNINGS.get(task_id)
    if known_warning:
        upstream_warnings.append(known_warning)
    if upstream_warnings:
        warning_path = environment_dir / "materials" / "upstream_data_warnings.md"
        warning_path.write_text(
            "# Upstream Data Warnings\n\n"
            "These limits are present in the pinned upstream material. Do not repair, "
            "complete, or infer missing evidence.\n\n"
            + "\n".join(f"- {warning}" for warning in upstream_warnings)
            + "\n",
            encoding="utf-8",
        )
        public_files.append(warning_path)
    private_files, _ = stage_declared_copies(SPEC, paper_dir, task_dir, private=True)

    # Ignore bytecode caches: a .pyc embeds the source path and mtime of the
    # machine that compiled it, so copying one makes the generated task depend
    # on whether the build host happened to have imported the vendor tree.
    # v0.3.1 shipped 348 of them.
    _ignore_bytecode = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(
        _VENDOR_DIR / "paper_orchestra",
        tests_dir / "vendor" / "paper_orchestra",
        ignore=_ignore_bytecode,
    )
    # Ship the complete upstream PaperOrchestra pipeline with the writer environment.
    shutil.copytree(
        _VENDOR_DIR / "paper_orchestra" / "upstream_pipeline",
        environment_dir / "paper_orchestra",
        ignore=_ignore_bytecode,
    )
    shutil.copy2(
        Path(__file__).resolve().parents[2] / "sidecar" / "server.py",
        environment_dir / "paper_orchestra_sidecar.py",
    )
    (environment_dir / "entrypoint.sh").write_text(
        environment.get_template("sidecar_entrypoint.sh.j2").render(), encoding="utf-8"
    )

    audit_forbidden_names(
        environment_dir,
        set(SPEC.forbidden_public_names),
        ignore_globs=SPEC.forbidden_public_ignore_globs,
    )

    _render_templates(
        environment,
        task_dir,
        metadata,
        has_figures=(environment_dir / "materials" / "figures").is_dir(),
        has_upstream_warnings=bool(upstream_warnings),
    )
    assert_valid_task_contract(task_dir)

    write_source_manifest(
        destination=tests_private / "source_manifest.json",
        benchmark="PaperWritingBench",
        upstream_id=metadata.paper_id,
        protocol=protocol,
        upstream_revision=upstream_revision,
        public_files=public_files,
        private_files=private_files,
        source_root=source_root,
        material_provenance=material_provenance,
        extra={
            "task_id": task_id,
            "venue": metadata.venue,
            "num_figures": metadata.num_figures,
            "num_tables": metadata.num_tables,
            "upstream_data_warnings": upstream_warnings,
            "release_provenance_requirements": list(
                SPEC.provenance_requirements.registry_fields
            ),
        },
    )

    for script in (
        environment_dir / "entrypoint.sh",
        solution_dir / "solve.sh",
        tests_dir / "test.sh",
    ):
        script.chmod(0o755)


def convert_paperwritingbench(config: PaperWritingBenchConversionConfig) -> int:
    """Convert PaperWritingBench samples into Harbor tasks.

    Expects the upstream layout from `yiwen-song/PaperWritingBench`
    (datasets.zip):

        <source>/<venue>/papers/<paper_id>/
        ├── <paper_id>.pdf
        └── raw_materials/{idea_sparse.md, idea_dense.md, experimental_log.md,
                           figures/{figure_*.png, info.json},
                           original_paper_gt_citations_*.json}

    Only the `sparse-plotoff` protocol is implemented in the first slice.
    """

    if config.protocol not in SUPPORTED_PROTOCOLS:
        allowed = ", ".join(sorted(SUPPORTED_PROTOCOLS))
        raise ValueError(f"Unsupported protocol {config.protocol!r}; expected one of: {allowed}")
    if not config.source.is_dir():
        raise FileNotFoundError(f"source directory not found: {config.source}")
    source_digest = source_tree_sha256(config.source)

    papers = _iter_papers(config.source)
    if config.limit is not None:
        papers = papers[: config.limit]

    environment = create_template_environment(_TEMPLATES_DIR)

    config.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = config.output_dir / "dataset-manifest.jsonl"
    manifest = load_dataset_manifest(manifest_path)

    converted = 0
    for index, (paper_dir, metadata) in enumerate(papers, start=1):
        task_id = task_id_for(SPEC.task_id_prefix, index)
        task_dir = config.output_dir / task_id
        if not prepare_task_output(task_dir, overwrite=config.overwrite):
            continue

        _convert_paper(
            environment=environment,
            paper_dir=paper_dir,
            metadata=metadata,
            task_dir=task_dir,
            task_id=task_id,
            protocol=config.protocol,
            upstream_revision=config.upstream_revision,
            source_root=config.source,
        )

        manifest[(task_id, metadata.paper_id)] = {
            "task_id": task_id,
            "upstream_paper_id": metadata.paper_id,
            "venue": metadata.venue,
            "protocol": config.protocol,
            "upstream_revision": config.upstream_revision,
        }
        converted += 1

    assert_source_tree_unchanged(config.source, source_digest)
    if converted:
        write_dataset_manifest(manifest_path, manifest)

    return converted
