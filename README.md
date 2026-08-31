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

## Dataset Release

The public Harbor dataset is available on [Hugging Face](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam).

| Harbor directory | Tasks | Protocol |
|---|---:|---|
| `paperwrite-bench-short` | 51 | PaperWrite-Bench `short` |
| `paperwritingbench-sparse-plotoff` | 200 | PaperWritingBench `sparse-plotoff` |

The current release is tagged `v0.2.0` at immutable revision
`5fe375dbd440409f0180e10dee213b1685c8f40d` and contains 251 tasks. For
reproducible runs, use that tag or revision instead of the Hub default branch.
Dataset release details are recorded in `docs/dataset-versioning.md`.

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

The binary smoke checks treat `main.tex` as the source of truth and recompile it in a
sandbox without ground truth or judge credentials. The optional official-metrics step
runs in the separate verifier and receives judge credentials only when explicitly
configured with Harbor's verifier environment flags below.

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

The latest bounded Codex API-key validation ran five tasks from each dataset
in parallel (`pwb-0001`..`pwb-0005` and `pwbw-0001`..`pwbw-0005`). All 10
completed with Harbor reward `1.0` and no trial errors. Nine official evaluator
artifacts were written; one PaperWritingBench evaluator run received empty
judge responses during citation title extraction and did not write
`evaluation.json`. This did not affect the Harbor binary reward.

For judge-backed runs, Harbor must pass credentials to the separate verifier container;
setting them only in the parent shell is insufficient. Use Harbor's verifier environment
flags with values sourced from a private secret file, for example:

```bash
set -a
. /path/to/private/judge.env
set +a
harbor run ... \
  --verifier-env 'JUDGE_API_KEY=${JUDGE_API_KEY}' \
  --verifier-env OPENAI_API_BASE=https://api.example.invalid/v1 \
  --verifier-env JUDGE_MODEL=gpt-5.4
```

The verifier templates use `JUDGE_API_KEY` as the explicit enable gate and bridge it to
`OPENAI_API_KEY` when the latter is not supplied. They also bridge `OPENAI_BASE_URL` to
`OPENAI_API_BASE`. Secret values are never embedded in task files or printed by the
evaluator.

The repository vendors the complete Apache-2.0 PaperOrchestra pipeline and
exposes its scholarly-search stages through a thin HTTP sidecar. Generated
PaperWritingBench Docker environments start the sidecar automatically before
the Harbor agent command; tasks still retain internet access for compatibility
with the upstream writer surface. Official evaluator wiring has been
completed, but upstream-versus-Harbor score parity has not yet been
established.

## paper-run agent

`paper-run` (an OpenCode-native autonomous manuscript-production harness) is
integrated as a first-class Harbor installed agent. It is registered by import
path, so no Harbor source change is needed:

```text
paperbench_harbor.agents.paper_run:PaperRun
```

Pinned versions (see `src/paperbench_harbor/agents/paper_run_core.py`):

- `paper-run` v0.2.0 via its official versioned installer (release tag commit
  `f952802a85c367be689c51c0cef14568b990cde8` at integration time)
- OpenCode `1.18.25` (matches the pinned lockfile)
- Node `20` via nvm

Run one task:

```bash
harbor run \
  --env-file /home/user/dev/paperbench-harbor/.env \
  --path /home/user/dev/paperbench-harbor/datasets/paperwrite-bench-short/pwb-0002 \
  --agent paperbench_harbor.agents.paper_run:PaperRun \
  --model openai/gpt-5.6-terra \
  --agent-kwarg variant=medium \
  --agent-env 'OPENAI_API_KEY=${OPENAI_API_KEY}' \
  --agent-env 'OPENAI_BASE_URL=${OPENAI_BASE_URL}' \
  --agent-timeout 14400 \
  --yes --no-delete --n-concurrent 1 \
  --job-name paperrun-pwb-0002
```

During debugging, keep `--no-delete` so the task container and its
`paper-run` project remain available after a failure. Remove it for unattended
batch runs where retaining containers is not needed.

The wrapper, inside the task container:

1. Installs Node and the pinned OpenCode runtime, then installs the pinned
   `paper-run` release with its checksum-verified official installer at
   `https://raw.githubusercontent.com/a-green-hand-jack/paper-run/v0.2.0/install.sh`.
2. Renders the task instruction into a valid harness `BRIEF.md` (validated by
   `agent-writing-harness` v0.3.0 `paper-brief.py`).
3. Writes a user-level OpenCode config pointing provider `openai` at
   `OPENAI_BASE_URL` (credentials are only read from the environment, never
   baked into files).
4. Runs `paper-run init --local --mode autonomous --model <model>`.
5. Stages the public benchmark materials into
   `<repo>/materials/` and commits them with a manual `paper-run checkpoint`,
   so the material assessment can see them and `paper-run start`'s
   clean-tree check passes.
6. Runs exactly one
   `paper-run start --headless --mode autonomous --model <model>` with
   `--variant <variant> --stage-timeout-multiplier 2`.
7. Exports the `paper/` tree into `/workspace/submission`. For PaperWrite-Bench,
   the supplied read-only bibliography is preserved as both `references.bib`
   and `refs.bib`; PaperWritingBench keeps the bibliography generated by
   paper-run. The wrapper also mirrors `.paper-run/`, `run.log` and publication
   PDFs under `/logs/agent/paper-run/` as trial artifacts.

Two paper-run behaviours are handled by the wrapper:

- **Headless permissions.** `paper-run` auto-approves no bash command, so a
  narrow set of read-only rules (`ls *`, `cat *`, `git status*`, `pdfinfo *`,
  `make *`, `pdflatex *`, ...) is added to the initialized project's
  `opencode.json` and committed with the materials checkpoint; everything else
  stays `ask` (fail-fast) in headless mode. The list is deliberately generous
  for the commands an autonomous writer legitimately uses inside the isolated
  container (inspection, git read, python, local file ops, publication build).
- **Material assessment.** It only considers files inside the writing repo, so
  public materials are copied into `<repo>/materials/` before `start`.
- **Locked contracts.** `PAPER.md ## What must not change silently` is a hard
  fail-closed section; the wrapper's brief explicitly tells the writer not to
  edit it, and to record lock candidates under `## Unresolved`.
- **Per-stage budgets.** The wrapper uses paper-run v0.2.0's supported
  `--stage-timeout-multiplier 2` option, so slower gateways can finish one
  autonomous run without modifying paper-run source.
- **Aggregate budget.** The full 13-stage run can exceed two hours. Keep the
  shared benchmark's original 1h task budget for other agents and pass
  `--agent-timeout 14400` when selecting paper-run.

The wrapper's single `paper-run start` execution budget is 4h. Harbor must be
given the matching `--agent-timeout 14400` override shown above.

## Run Harbor tasks on Ubuntu

Harbor runs on the Ubuntu box. The generated datasets are stored at:

```text
/home/user/dev/paperbench-harbor/datasets/paperwrite-bench-short
/home/user/dev/paperbench-harbor/datasets/paperwritingbench-sparse-plotoff
```

Keep runtime credentials in the private project file
`/home/user/dev/paperbench-harbor/.env` with mode `0600`. The file is not
committed. The recommended Codex path uses an OpenAI-compatible API key, not
ChatGPT OAuth:

```bash
ssh ubuntu-box
cd /home/user/dev/paperbench-harbor
codex --version
```

Run one task with the native Harbor Codex agent:

```bash
harbor run \
  --env-file /home/user/dev/paperbench-harbor/.env \
  --path /home/user/dev/paperbench-harbor/datasets/paperwritingbench-sparse-plotoff/pwbw-0001 \
  --agent codex \
  --model openai/gpt-5.6-sol \
  --agent-kwarg version=0.146.0 \
  --agent-kwarg reasoning_effort=high \
  --agent-kwarg web_search=live \
  --agent-env 'OPENAI_API_KEY=${OPENAI_API_KEY}' \
  --agent-env 'OPENAI_BASE_URL=${OPENAI_BASE_URL}' \
  --yes --n-concurrent 1 \
  --job-name codex-pwbw-0001
```

For a judge-backed run, pass credentials explicitly to the separate verifier
container. Codex OAuth `auth.json` cannot be used as the judge credential:

```bash
harbor run \
  --env-file /home/user/dev/paperbench-harbor/.env \
  --path /home/user/dev/paperbench-harbor/datasets/paperwritingbench-sparse-plotoff/pwbw-0001 \
  --agent codex --model openai/gpt-5.6-sol \
  --agent-kwarg version=0.146.0 \
  --agent-env 'OPENAI_API_KEY=${OPENAI_API_KEY}' \
  --agent-env 'OPENAI_BASE_URL=${OPENAI_BASE_URL}' \
  --verifier-env 'JUDGE_API_KEY=${JUDGE_API_KEY}' \
  --verifier-env 'OPENAI_API_KEY=${OPENAI_API_KEY}' \
  --verifier-env 'OPENAI_API_BASE=${OPENAI_API_BASE}' \
  --verifier-env 'JUDGE_MODEL=${JUDGE_MODEL}' \
  --yes --n-concurrent 1 \
  --job-name codex-pwbw-0001-judge
```

For long runs, use `nohup` so the SSH session can close safely:

```bash
nohup harbor run --env-file /home/user/dev/paperbench-harbor/.env \
  --config ~/paperbench-10-api-job.json \
  > ~/paperbench-10-api-key-parallel.log 2>&1 < /dev/null &
```

The config can contain multiple local datasets and task filters. For example,
the validated 10-task run used five tasks from each dataset and
`n_concurrent_trials: 10`:

```json
{
  "job_name": "paperbench-10-api-key-parallel",
  "jobs_dir": "/home/user/harbor-apex-smoke/jobs",
  "n_concurrent_trials": 10,
  "agents": [
    {
      "name": "codex",
      "model_name": "openai/gpt-5.6-sol",
      "n_concurrent": 10,
      "kwargs": {"version": "0.146.0", "reasoning_effort": "high", "web_search": "live"},
      "env": {
        "OPENAI_API_KEY": "${OPENAI_API_KEY}",
        "OPENAI_BASE_URL": "${OPENAI_BASE_URL}"
      }
    }
  ],
  "verifier": {
    "env": {
      "JUDGE_API_KEY": "${JUDGE_API_KEY}",
      "OPENAI_API_KEY": "${OPENAI_API_KEY}",
      "OPENAI_API_BASE": "${OPENAI_API_BASE}",
      "JUDGE_MODEL": "${JUDGE_MODEL}",
      "SEMANTIC_SCHOLAR_API_KEY": "${SEMANTIC_SCHOLAR_API_KEY}"
    }
  },
  "datasets": [
    {
      "path": "/home/user/dev/paperbench-harbor/datasets/paperwrite-bench-short",
      "task_names": ["pwb-0001", "pwb-0002", "pwb-0003", "pwb-0004", "pwb-0005"]
    },
    {
      "path": "/home/user/dev/paperbench-harbor/datasets/paperwritingbench-sparse-plotoff",
      "task_names": ["pwbw-0001", "pwbw-0002", "pwbw-0003", "pwbw-0004", "pwbw-0005"]
    }
  ]
}
```

Monitor a background job with its `result.json`:

```bash
python3 -c '
import json
p="$HOME/harbor-apex-smoke/jobs/paperbench-10-api-key-parallel/result.json"
print(json.load(open(p))["stats"])
'
```

Trial artifacts are stored below
`/home/user/harbor-apex-smoke/jobs/<job-name>/<trial-id>/artifacts/`. A
successful paper normally contains `workspace/submission/main.tex`,
`references.bib`, figures, and a compiled PDF. Harbor's binary reward is
independent from the optional official evaluator artifacts.

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
