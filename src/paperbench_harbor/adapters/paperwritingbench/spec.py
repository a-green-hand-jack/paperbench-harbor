"""PaperWritingBench's layout, as data.

The shape that keeps this benchmark's explicit hooks separate from
PaperWrite-Bench is visible in three fields below: papers are nested by venue,
the writer's material is `raw_materials/` rather than `resources/`, and the
conference kit is a whole directory keyed by venue instead of individual style
files discovered from the LaTeX. Discovery itself is now data-driven through
`PAPER_GLOB`, not a hand-maintained venue list in the converter.
"""

from __future__ import annotations

from paperbench_harbor.adapters.spec import (
    BenchmarkIdentity,
    CopyRule,
    RenderDefaults,
    UpstreamLayoutSpec,
)

PAPER_GLOB = "*/papers/*"
DISCOVERY_MARKER = "raw_materials/idea_sparse.md"

PUBLIC_RULES = (
    CopyRule(
        "raw_materials/idea_sparse.md",
        "environment/materials/idea_sparse.md",
        required=True,
    ),
    # Rewritten on every one of the 200 published tasks: upstream logs carry
    # short alignment rows, bare pipes inside math, and unlabeled columns, and
    # `normalize_markdown_tables` repairs the structure without touching any
    # result value, recording each correction in `upstream_data_warnings.md`.
    CopyRule(
        "raw_materials/experimental_log.md",
        "environment/materials/experimental_log.md",
        may_be_rewritten=True,
    ),
    CopyRule("raw_materials/figures", "environment/materials/figures", kind="tree"),
)

PRIVATE_RULES = (
    # Named after the sample, so it cannot be spelled literally. Both the
    # oracle and the evaluator get a copy.
    CopyRule(
        "*.pdf",
        "solution/private/",
        extra_targets=("tests/private/",),
    ),
    CopyRule(
        "raw_materials/idea_dense.md",
        "solution/private/idea_dense.md",
        extra_targets=("tests/private/idea_dense.md",),
    ),
    CopyRule(
        "raw_materials/original_paper_gt_citations_*.json",
        "solution/private/",
        extra_targets=("tests/private/",),
    ),
)

SPEC = UpstreamLayoutSpec(
    identity=BenchmarkIdentity(
        benchmark="PaperWritingBench",
        task_id_prefix="pwbw",
        tags=("paper-writing", "latex", "scientific-writing", "paperwrite-bench"),
        relevant_experience=(
            "Benchmark adaptation of PaperWrite-Bench into the Harbor task format, "
            "preserving the upstream writing-agent contract."
        ),
    ),
    paper_glob=PAPER_GLOB,
    discovery_marker=DISCOVERY_MARKER,
    public=PUBLIC_RULES,
    private=PRIVATE_RULES,
    forbidden_public_names=frozenset(
        {
            "idea_dense.md",
            "main.pdf",
            "config.yaml",
            "eval_points.json",
            "source_manifest.json",
        }
    ),
    generated_public=(
        "environment/materials/upstream_data_warnings.md",
        "environment/paper_orchestra/",
    ),
    generated_private=("tests/private/source_manifest.json",),
    style_resolution="venue-directory",
    render=RenderDefaults(
        num_page="8",
        column="two-column",
        grader_module="grader_pwbw",
    ),
)
