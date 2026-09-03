"""Harbor wrapping settings for Physics-PaperRecon."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from paperbench_harbor.adapters.paperwrite_bench import spec as pwb_spec
from paperbench_harbor.adapters.paperwrite_bench.converter import PaperWriteBenchConversionConfig
from paperbench_harbor.adapters.spec import BenchmarkIdentity, MaterialCompletenessContract

IDENTITY = BenchmarkIdentity(benchmark="Physics-PaperRecon", task_id_prefix="phys", tags=("paper-writing", "latex", "scientific-writing", "physics", "physics-paperrecon"), relevant_experience="Reconstructing a physics research paper from a research overview, figures, tables and approved study materials under a fixed bibliography and LaTeX template.", agents_md_dir="agents_md", agents_md_fallback="AGENTS_theory.md")
BENCHMARK = IDENTITY.benchmark
TASK_ID_PREFIX = IDENTITY.task_id_prefix
CATEGORY = pwb_spec.SPEC.render.category
TAGS = IDENTITY.tags
RELEVANT_EXPERIENCE = IDENTITY.relevant_experience
AGENTS_MD_DIR = Path(__file__).resolve().parent / IDENTITY.agents_md_dir
AGENTS_MD_FALLBACK = IDENTITY.agents_md_fallback

def physics_paperrecon_conversion_config(*, source: Path, output_dir: Path, upstream_revision: str | None, overview: str = "short", limit: int | None = None, overwrite: bool = False) -> PaperWriteBenchConversionConfig:
    return PaperWriteBenchConversionConfig(source=source, output_dir=output_dir, overview=overview, limit=limit, overwrite=overwrite, upstream_revision=upstream_revision, benchmark=SPEC.benchmark, task_id_prefix=SPEC.task_id_prefix, category=SPEC.render.category, tags=SPEC.identity.tags, relevant_experience=SPEC.identity.relevant_experience, agents_md_dir=AGENTS_MD_DIR, agents_md_fallback=AGENTS_MD_FALLBACK, include_official_grader=False, layout_spec=SPEC)

SPEC = dataclasses.replace(pwb_spec.SPEC, identity=IDENTITY, public=tuple(dataclasses.replace(rule, tree_exclude_globs=("manuscript/*.tex", "manuscript/*/*.tex", "tex/minibwa.tex", "./README.md")) if rule.source == "resources/code" else rule for rule in pwb_spec.SPEC.public), forbidden_public_names=pwb_spec.SPEC.forbidden_public_names | {"provenance.json"}, render=dataclasses.replace(pwb_spec.SPEC.render, grader_module=""), style_resolution="local-first-package-scan", redact_source_paper_references=True, material_completeness=MaterialCompletenessContract(source_inventory="resources/table_inventory.json", public_inventory="environment/materials/table_inventory.json", public_material_root="environment/materials/tables"))
