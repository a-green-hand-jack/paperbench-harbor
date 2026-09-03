"""PaperWritingBench's layout, as data.

The shape that made this a separate 426-line converter rather than a config of
the PaperWrite-Bench one is visible in three fields below: papers are nested
under a hand-listed venue (`VENUES`), the writer's material is `raw_materials/`
rather than `resources/`, and the conference kit is a whole directory keyed by
venue instead of individual style files discovered from the LaTeX.
"""

from __future__ import annotations

from paperbench_harbor.adapters.spec import CopyRule, UpstreamLayoutSpec

#: Hand-listed, because the upstream archive has no manifest to enumerate.
VENUES = ("cvpr2025", "iclr2025")

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
    benchmark="PaperWritingBench",
    task_id_prefix="pwbw",
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
    generated_public=("environment/materials/upstream_data_warnings.md",),
    generated_private=("tests/private/source_manifest.json",),
)
