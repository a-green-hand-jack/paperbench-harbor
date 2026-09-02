"""Harbor wrapping settings for the LifeSci-PaperRecon corpus.

Phase 2 of the approved plan deliberately reuses
``adapters.paperwrite_bench.converter`` rather than adding a parallel Harbor
converter: the biology corpus is built into the same generic upstream layout,
so the only benchmark-specific facts are identity metadata, which the converter
takes as parameters.

The corpus itself is produced by
``construction.lifesci_paperrecon`` (an opencode-agent-driven build, see
``scripts/build_lifesci_paperrecon_source.py``); nothing in this module depends
on *how* it was produced, only on the layout it lands in.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from paperbench_harbor.adapters.paperwrite_bench import spec as pwb_spec
from paperbench_harbor.adapters.paperwrite_bench.converter import (
    PaperWriteBenchConversionConfig,
)

BENCHMARK = "LifeSci-PaperRecon"
TASK_ID_PREFIX = "lspr"
CATEGORY = "research-writing"
TAGS = (
    "paper-writing",
    "latex",
    "scientific-writing",
    "biology",
    "life-sciences",
    "lifesci-paperrecon",
)
RELEVANT_EXPERIENCE = (
    "Reconstructing a life-sciences research paper from a research overview, "
    "figures, tables and the study's own analysis code, under a fixed "
    "bibliography and LaTeX template."
)
AGENTS_MD_DIR = Path(__file__).resolve().parent / "agents_md"
AGENTS_MD_FALLBACK = "AGENTS_computational.md"


def lifesci_paperrecon_conversion_config(
    *,
    source: Path,
    output_dir: Path,
    upstream_revision: str | None,
    overview: str = "short",
    limit: int | None = None,
    overwrite: bool = False,
) -> PaperWriteBenchConversionConfig:
    """Build the converter config for the LifeSci-PaperRecon corpus.

    ``include_official_grader`` is off: the pilot ships the binary Harbor smoke
    check only. There is no upstream evaluator to reproduce for this benchmark,
    and fabricating an ``eval_points.json`` rubric would be worse than shipping
    none (approved plan, Phase 3 is deferred to an external review agent).
    """

    return PaperWriteBenchConversionConfig(
        source=source,
        output_dir=output_dir,
        overview=overview,
        limit=limit,
        overwrite=overwrite,
        upstream_revision=upstream_revision,
        benchmark=BENCHMARK,
        task_id_prefix=TASK_ID_PREFIX,
        category=CATEGORY,
        tags=TAGS,
        relevant_experience=RELEVANT_EXPERIENCE,
        agents_md_dir=AGENTS_MD_DIR,
        agents_md_fallback=AGENTS_MD_FALLBACK,
        include_official_grader=False,
        layout_spec=SPEC,
    )


#: The layout is PaperWrite-Bench's, by construction: the corpus is built into
#: that shape, which is the whole reason this module is a shim rather than a
#: converter. Only identity differs, and `provenance.json` -- a record of what
#: the construction agent claimed, which the writer must never see.
SPEC = dataclasses.replace(
    pwb_spec.SPEC,
    benchmark=BENCHMARK,
    task_id_prefix=TASK_ID_PREFIX,
    forbidden_public_names=pwb_spec.SPEC.forbidden_public_names | {"provenance.json"},
)
