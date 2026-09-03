"""PaperWrite-Bench's layout, as data.

Every path here was read off `converter.py`, not out of the upstream README:
the point of the exercise is a description of what the conversion *does*, which
`tests/test_adapter_specs.py` then checks against what it actually produces.

LifeSci-PaperRecon reuses this shape (see `SPEC` in
`adapters/lifesci_paperrecon/harbor.py`) because its corpus is built to this
layout on purpose -- that is what made it a 75-line shim rather than a second
converter.
"""

from __future__ import annotations

from paperbench_harbor.adapters.spec import VARIANT, CopyRule, UpstreamLayoutSpec

#: The upstream tree has no venue nesting: every immediate subdirectory that
#: carries `resources/template.tex` is a paper.
PAPER_GLOB = "*"
DISCOVERY_MARKER = "resources/template.tex"

VARIANT_SOURCES = {
    "short": "resources/research_overview_short.md",
    "long": "resources/research_overview_long.md",
}

PUBLIC_RULES = (
    # The selected overview is renamed on the way in, so the writer cannot tell
    # which variant it received.
    CopyRule(VARIANT, "environment/materials/research_overview.md", required=True),
    CopyRule("resources/template.tex", "environment/materials/template.tex", required=True),
    CopyRule("resources/references.bib", "environment/materials/references.bib"),
    CopyRule("resources/figure_summary.txt", "environment/materials/figure_summary.txt"),
    CopyRule("resources/table_summary.txt", "environment/materials/table_summary.txt"),
    CopyRule("resources/figures", "environment/materials/figures", kind="tree"),
    CopyRule("resources/tables", "environment/materials/tables", kind="tree"),
    CopyRule("resources/code", "environment/materials/code", kind="tree"),
)

PRIVATE_RULES = (
    CopyRule("original/main.tex", "solution/private/main.tex"),
    CopyRule("original/main.pdf", "solution/private/main.pdf"),
    CopyRule("original/config.yaml", "solution/private/config.yaml"),
    # The oracle needs the rubric to solve; the evaluator needs it to score.
    CopyRule(
        "resources/eval_points.json",
        "solution/private/eval_points.json",
        extra_targets=("tests/private/eval_points.json",),
    ),
    CopyRule("original/main.tex", "tests/private/ground_truth.tex"),
    CopyRule("resources/figure_summary.txt", "tests/private/figure_summary.txt"),
    CopyRule("resources/table_summary.txt", "tests/private/table_summary.txt"),
    # Hallucination verification reads main.tex beside its own dependencies, so
    # both upstream trees are copied into one coherent root.
    CopyRule("original", "tests/private/ground_truth_sources", kind="tree"),
    CopyRule("resources", "tests/private/ground_truth_sources", kind="tree"),
)

SPEC = UpstreamLayoutSpec(
    benchmark="PaperWrite-Bench",
    task_id_prefix="pwb",
    paper_glob=PAPER_GLOB,
    discovery_marker=DISCOVERY_MARKER,
    variant_sources=VARIANT_SOURCES,
    public=PUBLIC_RULES,
    private=PRIVATE_RULES,
    forbidden_public_names=frozenset(
        {"main.tex", "main.pdf", "config.yaml", "eval_points.json", "source_manifest.json"}
    ),
    generated_public=(
        "environment/materials/AGENTS.md",
        # Written only when the conversion had to drop a graphic the upstream
        # template referenced but the corpus does not ship.
        "environment/materials/upstream_data_warnings.md",
    ),
    generated_private=("tests/private/source_manifest.json",),
)
