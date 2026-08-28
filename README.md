# paperbench-harbor

Harbor adapters and evaluation infrastructure for two automated scientific-paper writing benchmarks:

- **PaperWritingBench**, introduced with *PaperOrchestra: A Multi-Agent Framework for Automated AI Research Paper Writing*.
- **PaperWrite-Bench**, introduced with *Paper Reconstruction Evaluation: Evaluating Presentation and Hallucination in AI-written Papers*.

The project converts upstream benchmark samples into isolated Harbor tasks before any writing agent is evaluated. Its primary concerns are reproducibility, public/private data separation, LaTeX artifact contracts, safe verification, and later integration of the official benchmark evaluators.

## Initial protocols

| Benchmark | Initial Harbor protocol | Writer network policy |
|---|---|---|
| PaperWritingBench | `sparse-plotoff` | Controlled scholarly retrieval only |
| PaperWrite-Bench | `short` | No network |

The protocols are deliberately separate. Sparse/dense inputs, PlotOn/PlotOff settings, and short/long reconstruction overviews must not be mixed in one reported result.

## Repository layout

```text
paperbench-harbor/
├── src/paperbench_harbor/
│   ├── common/                    # shared contracts, manifests, and audits
│   └── adapters/
│       ├── paperwritingbench/     # PaperWritingBench -> Harbor
│       └── paperwrite_bench/      # PaperWrite-Bench -> Harbor
├── scripts/                       # command-line entry points
├── tests/                         # conversion and leakage tests
├── docs/                          # design and implementation notes
└── datasets/                      # generated Harbor datasets; not committed
```

Each generated Harbor task is expected to contain:

```text
<task-id>/
├── task.toml
├── instruction.md
├── environment/
├── solution/
└── tests/
```

The writer-facing environment receives only a strict allowlist of public files. Ground-truth papers, evaluation rubrics, citation labels, and evaluator metadata remain verifier-only.

## Unified submission contract

Both adapters use the same expected writer output:

```text
/workspace/submission/
├── main.tex
├── references.bib
├── figures/
└── final.pdf
```

The verifier treats `main.tex` as the source of truth and recompiles it in a sandbox without ground truth or judge credentials.

## Development status

This repository currently contains the project skeleton and implementation plan. The recommended implementation order is:

1. Shared task contract and public/private leakage audit. ✅
2. PaperWrite-Bench `short` adapter on a three-sample smoke subset. ✅
3. Oracle, NOP-agent, and LaTeX compilation checks. ✅
4. Full 51-task PaperWrite-Bench conversion.
5. PaperWritingBench `sparse-plotoff` adapter on a four-sample subset. (1 task validated)
6. Controlled scholarly-search interface.
7. Full 200-task PaperWritingBench conversion.
8. Official evaluator integration and parity experiments.

The PaperWrite-Bench converter is implemented (`paperbench-harbor paperwrite-bench`)
with Jinja2 Harbor task templates, deterministic task ids, explicit
public-material allowlists, SHA-256 provenance manifests, and leakage
auditing. The first three tasks (`pwb-0001`..`pwb-0003`) were verified on
Harbor 0.20.0 with Docker: oracle reward 1.0, NOP reward 0.0. A real
claude-code agent (claude-sonnet-5 via the Apex gateway) also passed
`pwb-0001` end-to-end with reward 1.0.

The PaperWritingBench `sparse-plotoff` converter is implemented
(`paperbench-harbor paperwritingbench`) with the same shared contracts plus
bundled CVPR 2025 / ICLR 2025 author templates and an oracle that assembles a
complete paper from the raw materials and the verifier-only ground-truth
citation cache. The first task (`pwbw-0001`) was verified on Harbor: oracle
reward 1.0, NOP reward 0.0.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

The generated benchmark datasets can be large and may include upstream materials subject to their original licenses and distribution terms. They are intentionally excluded from Git.

## Upstream projects

- `google-research/paper-orchestra`
- `Agent4Science-UTokyo/PaperRecon`
- `harbor-framework/benchmark-template`

## License

A project license has not yet been selected. Upstream source code and benchmark data remain governed by their respective licenses and terms.
