# Harbor Adapter Implementation Plan

## Objective

Convert PaperWritingBench and PaperWrite-Bench into two independent Harbor datasets before evaluating any writing agent.

The conversion layer must preserve upstream task semantics while introducing:

- deterministic task identifiers;
- strict public/private material separation;
- a shared LaTeX submission contract;
- safe compilation of untrusted generated LaTeX;
- oracle and NOP-agent validation;
- source-revision and file-hash manifests;
- later integration of the official benchmark evaluators.

## Dataset families

### PaperWritingBench

Initial dataset: `paperwritingbench-sparse-plotoff`.

Writer-visible materials:

- `idea_sparse.md`;
- `experimental_log.md`;
- conference template and guidelines;
- provided figures for PlotOff;
- a controlled scholarly-search interface.

Verifier-only materials:

- original paper PDF or LaTeX;
- target-paper identity mapping;
- ground-truth citation caches;
- P0/P1 labels;
- evaluator prompts, metadata, and outputs.

Later datasets should encode other protocols in distinct dataset names, such as `sparse-ploton` and `dense-plotoff`.

### PaperWrite-Bench

Initial dataset: `paperwrite-bench-short`.

Writer-visible materials:

- selected `research_overview_short.md`, renamed to `research_overview.md`;
- empty-section LaTeX template;
- fixed `references.bib`;
- figure and table assets plus summaries;
- optional source code.

Verifier-only materials:

- ground-truth LaTeX and PDF;
- `eval_points.json`;
- the non-selected overview variant;
- evaluator outputs and reproduction judgments.

The writer has no network access in this dataset.

## Task contract

Each task must contain `task.toml`, `instruction.md`, `environment/`, `solution/`, and `tests/`.

The writer produces:

```text
/workspace/submission/
├── main.tex
├── references.bib
└── figures/ (optional)
```

`main.tex` is authoritative. The verifier recompiles it in a restricted compiler environment with no ground truth, no judge credentials, no network, and shell escape disabled.

## Security boundary

Use a three-stage verification path:

1. Receive declared artifacts from the writer environment.
2. Recompile and normalize them in a sandbox containing no private benchmark data.
3. Run ground-truth and LLM-judge evaluation in a separate process after compilation.

Private files must never be copied into the agent Docker build context. Adapters must use an explicit allowlist, not directory-level copying followed by exclusions.

## Adapter CLI contract

Both converters should support:

- `--source`;
- `--output-dir`;
- `--limit`;
- `--overwrite`;
- `--task-ids`;
- pinned upstream revision metadata.

Benchmark-specific arguments:

- PaperWritingBench: `--protocol sparse-plotoff`;
- PaperWrite-Bench: `--overview short`.

## Development sequence

1. Finalize common task templates, submission checks, and manifest schema.
2. Implement PaperWrite-Bench `short` conversion for three task IDs.
3. Validate Harbor parsing, environment builds, oracle output, NOP failure, and leakage audit.
4. Convert all 51 PaperWrite-Bench tasks.
5. Implement PaperWritingBench `sparse-plotoff` conversion for four task IDs.
6. Add a uniform, cutoff-aware scholarly-search sidecar.
7. Convert all 200 PaperWritingBench tasks.
8. Add dataset-level metric aggregation.
9. Integrate official rubric, citation, hallucination, literature-review, and review evaluators.
10. Run upstream-versus-Harbor parity experiments before benchmarking custom agents.

## Acceptance criteria

- 251 deterministic, unique task IDs across the two initial datasets.
- 100% valid task configuration parsing.
- 100% successful environment builds.
- Zero private-material leaks.
- 100% oracle smoke pass.
- 0% NOP-agent pass.
- Consistent compilation toolchain and artifact paths.
- Pinned upstream revisions and verifier model identifiers.
- Failed-generation samples retained in aggregate reporting.
