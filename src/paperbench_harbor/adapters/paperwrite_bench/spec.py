"""PaperWrite-Bench's layout, as data.

The shared conversion staging helper consumes this spec directly. The
regression tests check its predicted copies against the produced task tree, and
the fidelity audit independently recovers source origins from bytes.

LifeSci-PaperRecon reuses this shape (see `SPEC` in
`adapters/lifesci_paperrecon/harbor.py`) because its corpus is built to this
layout on purpose -- that is what made it a 75-line shim rather than a second
converter.
"""

from __future__ import annotations

from paperbench_harbor.adapters.spec import (
    VARIANT,
    BenchmarkIdentity,
    CopyRule,
    RenderDefaults,
    UpstreamLayoutSpec,
)

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
    CopyRule(
        "resources/template.tex",
        "environment/materials/template.tex",
        required=True,
        may_be_rewritten=True,
    ),
    CopyRule("resources/references.bib", "environment/materials/references.bib"),
    CopyRule("resources/figure_summary.txt", "environment/materials/figure_summary.txt"),
    CopyRule("resources/table_summary.txt", "environment/materials/table_summary.txt"),
    # Optional on the historical corpus; required by LifeSci's source-table
    # contract once a constructed sample declares it.
    CopyRule("resources/table_inventory.json", "environment/materials/table_inventory.json"),
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
    CopyRule(
        "resources/research_overview_short.md",
        "tests/private/research_overview_short.md",
        protocols=("long",),
    ),
    CopyRule(
        "resources/research_overview_long.md",
        "tests/private/research_overview_long.md",
        protocols=("short",),
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
    identity=BenchmarkIdentity(
        benchmark="PaperWrite-Bench",
        task_id_prefix="pwb",
        tags=("paper-writing", "latex", "scientific-writing", "paperwrite-bench"),
        relevant_experience=(
            "Benchmark adaptation of PaperWrite-Bench into the Harbor task format, "
            "preserving the upstream writing-agent contract."
        ),
        agents_md_dir="agents_md",
        agents_md_fallback="AGENTS_method.md",
    ),
    paper_glob=PAPER_GLOB,
    discovery_marker=DISCOVERY_MARKER,
    variant_sources=VARIANT_SOURCES,
    public=PUBLIC_RULES,
    private=PRIVATE_RULES,
    forbidden_public_names=frozenset(
        {"main.tex", "main.pdf", "config.yaml", "eval_points.json", "source_manifest.json"}
    ),
    forbidden_public_ignore_globs=("materials/code/**",),
    generated_public=(
        "environment/materials/AGENTS.md",
        # Written only when the conversion had to drop a graphic the upstream
        # template referenced but the corpus does not ship.
        "environment/materials/upstream_data_warnings.md",
    ),
    generated_private=("tests/private/source_manifest.json",),
    style_resolution="package-scan",
    render=RenderDefaults(grader_module="grader_pwb"),
)
