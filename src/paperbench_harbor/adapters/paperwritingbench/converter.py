from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from paperbench_harbor.common.audit import audit_forbidden_names
from paperbench_harbor.common.manifest import write_source_manifest

SUPPORTED_PROTOCOLS = {"sparse-plotoff", "sparse-ploton", "dense-plotoff"}
IMPLEMENTED_PROTOCOLS = {"sparse-plotoff"}
VENUES = ("cvpr2025", "iclr2025")
FORBIDDEN_PUBLIC_NAMES = {
    "idea_dense.md",
    "main.pdf",
    "config.yaml",
    "eval_points.json",
    "source_manifest.json",
}
_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "common" / "templates"
_CONFERENCE_TEMPLATES_DIR = (
    Path(__file__).resolve().parents[4] / "packaging" / "conference-templates"
)
_VENDOR_DIR = Path(__file__).resolve().parents[2] / "vendor"
_CITATION_CACHE_PATTERN = re.compile(r"^original_paper_gt_citations_.+\.json$")

_PAPER_ORDER_RE = re.compile(r"(\d+)")


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
    for venue in VENUES:
        papers_root = source / venue / "papers"
        if not papers_root.is_dir():
            continue
        for paper_dir in papers_root.iterdir():
            raw = paper_dir / "raw_materials"
            if not raw.is_dir() or not (raw / "idea_sparse.md").is_file():
                continue
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


def _copy_public_materials(raw: Path, environment_dir: Path, venue: str) -> list[Path]:
    materials_dir = environment_dir / "materials"
    materials_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []

    for filename in ("idea_sparse.md", "experimental_log.md"):
        source = raw / filename
        if source.is_file():
            destination = materials_dir / filename
            shutil.copy2(source, destination)
            copied.append(destination)

    figures = raw / "figures"
    if figures.is_dir() and any(figures.iterdir()):
        destination = materials_dir / "figures"
        shutil.copytree(figures, destination)
        copied.extend(path for path in destination.rglob("*") if path.is_file())

    template_dir = _CONFERENCE_TEMPLATES_DIR / venue
    if not template_dir.is_dir():
        raise FileNotFoundError(f"conference template missing: {template_dir}")
    destination = materials_dir / "conference_template"
    shutil.copytree(template_dir, destination)
    copied.extend(path for path in destination.rglob("*") if path.is_file())

    return copied


def _copy_private_materials(paper_dir: Path, raw: Path, solution_private: Path, tests_private: Path) -> list[Path]:
    copied: list[Path] = []

    for pdf in paper_dir.glob("*.pdf"):
        destination = solution_private / pdf.name
        shutil.copy2(pdf, destination)
        copied.append(destination)
        evaluator_copy = tests_private / pdf.name
        shutil.copy2(pdf, evaluator_copy)
        copied.append(evaluator_copy)

    idea_dense = raw / "idea_dense.md"
    if idea_dense.is_file():
        for target in (solution_private, tests_private):
            destination = target / "idea_dense.md"
            shutil.copy2(idea_dense, destination)
            copied.append(destination)

    for source in sorted(raw.glob("original_paper_gt_citations_*.json")):
        for target in (solution_private, tests_private):
            destination = target / source.name
            shutil.copy2(source, destination)
            copied.append(destination)

    return copied


def _render_templates(
    environment: Environment,
    task_dir: Path,
    metadata: _PaperMetadata,
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
        "num_page": "8",
        "column": "two-column",
        "grader_module": "grader_pwbw",
        "include_paper_orchestra": True,
    }
    (task_dir / "task.toml").write_text(
        environment.get_template("task.toml.j2").render(**context), encoding="utf-8"
    )
    (task_dir / "instruction.md").write_text(
        environment.get_template("instruction_pwbw.md.j2").render(**context), encoding="utf-8"
    )
    (task_dir / "environment" / "Dockerfile").write_text(
        environment.get_template("environment.Dockerfile.j2").render(**context), encoding="utf-8"
    )
    (task_dir / "tests" / "Dockerfile").write_text(
        environment.get_template("tests.Dockerfile.j2").render(**context), encoding="utf-8"
    )
    (task_dir / "tests" / "test.sh").write_text(
        environment.get_template("test.sh.j2").render(**context), encoding="utf-8"
    )
    (task_dir / "tests" / "test_state.py").write_text(
        environment.get_template("test_state.py.j2").render(**context), encoding="utf-8"
    )
    (task_dir / "solution" / "solve.sh").write_text(
        environment.get_template("solve_pwbw.sh.j2").render(**context), encoding="utf-8"
    )
    (task_dir / "solution" / "oracle_pwbw.py").write_text(
        environment.get_template("oracle_pwbw.py.j2").render(**context), encoding="utf-8"
    )
    (task_dir / "tests" / "grader_pwbw.py").write_text(
        environment.get_template("grader_pwbw.py.j2").render(**context), encoding="utf-8"
    )


def _convert_paper(
    environment: Environment,
    paper_dir: Path,
    metadata: _PaperMetadata,
    task_dir: Path,
    task_id: str,
    protocol: str,
    upstream_revision: str | None,
) -> None:
    raw = paper_dir / "raw_materials"
    environment_dir = task_dir / "environment"
    solution_dir = task_dir / "solution"
    solution_private = solution_dir / "private"
    tests_dir = task_dir / "tests"
    tests_private = tests_dir / "private"
    for path in (environment_dir, solution_dir, solution_private, tests_dir, tests_private):
        path.mkdir(parents=True, exist_ok=True)
    # The shared environment Dockerfile unconditionally copies texmf/; keep it
    # present even when no extra style files are bundled for this venue.
    texmf_dir = environment_dir / "texmf"
    texmf_dir.mkdir(exist_ok=True)
    (texmf_dir / ".keep").touch()

    public_files = _copy_public_materials(raw, environment_dir, metadata.venue)
    private_files = _copy_private_materials(paper_dir, raw, solution_private, tests_private)

    shutil.copytree(
        _VENDOR_DIR / "paper_orchestra",
        tests_dir / "vendor" / "paper_orchestra",
    )
    # Ship the complete upstream PaperOrchestra pipeline with the writer environment.
    shutil.copytree(
        _VENDOR_DIR / "paper_orchestra" / "upstream_pipeline",
        environment_dir / "paper_orchestra",
    )
    shutil.copy2(
        Path(__file__).resolve().parents[2] / "sidecar" / "server.py",
        environment_dir / "paper_orchestra_sidecar.py",
    )
    (environment_dir / "entrypoint.sh").write_text(
        environment.get_template("sidecar_entrypoint.sh.j2").render(), encoding="utf-8"
    )

    audit_forbidden_names(environment_dir, FORBIDDEN_PUBLIC_NAMES)

    _render_templates(environment, task_dir, metadata)

    write_source_manifest(
        destination=tests_private / "source_manifest.json",
        benchmark="PaperWritingBench",
        upstream_id=metadata.paper_id,
        protocol=protocol,
        upstream_revision=upstream_revision,
        public_files=public_files,
        private_files=private_files,
        extra={
            "task_id": task_id,
            "venue": metadata.venue,
            "num_figures": metadata.num_figures,
            "num_tables": metadata.num_tables,
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
    if config.protocol not in IMPLEMENTED_PROTOCOLS:
        raise NotImplementedError(
            f"Protocol {config.protocol!r} is not implemented yet; "
            f"implemented protocols: {', '.join(sorted(IMPLEMENTED_PROTOCOLS))}"
        )

    if not config.source.is_dir():
        raise FileNotFoundError(f"source directory not found: {config.source}")

    papers = _iter_papers(config.source)
    if config.limit is not None:
        papers = papers[: config.limit]

    environment = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )

    config.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = config.output_dir / "dataset-manifest.jsonl"
    manifest: dict[tuple[str, str], dict] = {}
    if manifest_path.is_file():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            manifest[(entry["task_id"], entry["upstream_paper_id"])] = entry

    converted = 0
    for index, (paper_dir, metadata) in enumerate(papers, start=1):
        task_id = f"pwbw-{index:04d}"
        task_dir = config.output_dir / task_id
        if task_dir.exists():
            if not config.overwrite:
                continue
            shutil.rmtree(task_dir)

        _convert_paper(
            environment=environment,
            paper_dir=paper_dir,
            metadata=metadata,
            task_dir=task_dir,
            task_id=task_id,
            protocol=config.protocol,
            upstream_revision=config.upstream_revision,
        )

        manifest[(task_id, metadata.paper_id)] = {
            "task_id": task_id,
            "upstream_paper_id": metadata.paper_id,
            "venue": metadata.venue,
            "protocol": config.protocol,
        }
        converted += 1

    if converted:
        manifest_path.write_text(
            "\n".join(
                json.dumps(entry, sort_keys=True)
                for entry in sorted(manifest.values(), key=lambda item: item["task_id"])
            )
            + "\n",
            encoding="utf-8",
        )

    return converted
