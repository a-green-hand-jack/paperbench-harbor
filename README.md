# paperbench-harbor

Harbor adapters and evaluation infrastructure for two automated scientific-paper writing benchmarks:

- **PaperWritingBench**, introduced with *PaperOrchestra: A Multi-Agent Framework for Automated AI Research Paper Writing*.
- **PaperWrite-Bench**, introduced with *Paper Reconstruction Evaluation: Evaluating Presentation and Hallucination in AI-written Papers*.

The project converts upstream benchmark samples into isolated Harbor tasks before any writing agent is evaluated. Its primary concerns are reproducibility, public/private data separation, LaTeX artifact contracts, safe verification, and running the official benchmark evaluators alongside Harbor verification.

## Initial protocols

| Benchmark | Initial Harbor protocol | Writer network policy |
|---|---|---|
| PaperWritingBench | `sparse-plotoff` | Internet enabled; PaperOrchestra search sidecar available |
| PaperWrite-Bench | `short` | Internet enabled for the writer; verifier recompilation remains network-free |

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
└── figures/ (optional)
```

The verifier treats `main.tex` as the source of truth and recompiles it in a sandbox without ground truth or judge credentials.

Dataset release and reproducibility guidance is documented in
`docs/dataset-versioning.md`.

## Development status

This repository currently contains the project skeleton and implementation plan. The recommended implementation order is:

1. Shared task contract and public/private leakage audit. ✅
2. PaperWrite-Bench `short` adapter on a three-sample smoke subset. ✅
3. Oracle, NOP-agent, and LaTeX compilation checks. ✅
4. Full 51-task PaperWrite-Bench conversion. ✅
5. PaperWritingBench `sparse-plotoff` adapter on a four-sample subset. ✅
6. Controlled scholarly-search interface. ✅
7. Full 200-task PaperWritingBench conversion. ✅
8. Official evaluator integration. ✅
9. Upstream-versus-Harbor parity experiments.

The PaperWrite-Bench converter is implemented (`paperbench-harbor paperwrite-bench`)
with Jinja2 Harbor task templates, deterministic task ids, explicit
public-material allowlists, SHA-256 provenance manifests, and leakage
auditing. All 51 tasks (`pwb-0001`..`pwb-0051`) were verified on Harbor
0.20.0 with Docker: oracle reward 1.0, NOP reward 0.0. A real claude-code
agent (claude-sonnet-5 via the Apex gateway) also passed `pwb-0001`
end-to-end with reward 1.0.

The PaperWritingBench `sparse-plotoff` converter is implemented
(`paperbench-harbor paperwritingbench`) with the same shared contracts plus
bundled CVPR 2025 / ICLR 2025 author templates, official style files for
NeurIPS 2025, ICLR 2026, ICML 2025, ACL, ICCV 2025, AAAI 2025, and arxiv,
and an oracle that assembles a complete paper from the raw materials and the
verifier-only ground-truth citation cache. All 200 tasks
(`pwbw-0001`..`pwbw-0200`) were verified on Harbor: oracle reward 1.0, NOP
reward 0.0.

Official evaluator integration is implemented in the verifier. PaperWrite-Bench
uses vendored PaperRecon scoring for deterministic citation F1 and, when
`JUDGE_API_KEY` is configured, judge-backed per-section rubric scoring plus
figure/table coverage. PaperWritingBench uses vendored PaperOrchestra
autoraters for AgentReview, literature-review quality, and stage-1 citation F1
(reference extraction and title matching). These metrics are written to
`/logs/verifier/evaluation.json`; they are diagnostic benchmark metrics and do
not affect Harbor's binary reward. The PaperWritingBench evaluator skips all
LLM autoraters when no judge key is configured.

The repository provides a dependency-free, cutoff-aware scholarly-search
sidecar over a versioned JSONL index (`scripts/scholarly_search_sidecar.py`).
The sidecar is the reproducible retrieval primitive; populating a benchmark-
approved index and starting it alongside Harbor are deployment steps. Tasks
still retain internet access for compatibility with the upstream writer
surface. Official evaluator wiring has been completed, but upstream-versus-
Harbor score parity has not yet been established.

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
