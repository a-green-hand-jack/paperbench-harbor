# paperbench-harbor

`paperbench-harbor` is the source repository for Harbor adapters and
evaluation infrastructure for scientific paper-writing benchmarks. It turns
benchmark inputs into isolated Harbor tasks and connects different
paper-writing agents to the same submission contract and verifier.

## Public Hugging Face Datasets

The project publishes two different Hugging Face datasets. The first is the
executable benchmark; the second is the archive of runs performed against that
benchmark.

| Dataset | Purpose | Contents |
|---|---|---|
| [`Paper-Writing-Exam`](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam) | Benchmark task package | Harbor task directories, instructions, writer environments, oracle solutions, and verifiers |
| [`Paper-Writing-Exam-Trials`](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam-Trials) | Public run archive | Sanitized agent trajectories, submissions, logs, scores, and complete trial archives |

Trial publishing is opt-in. The following is the reproducible single-task
example used by the current integration: benchmark release `v0.3.1`
(`bfe2471c41f416d877e74bfa73cf0f29165c7567`), Harbor `v0.22.0`
(`4407eb5227a2ff4f0d3f16b2eb48849382fdf276`), and Codex
`openai/gpt-5.6-terra` with medium reasoning effort. Run it from a checkout of
this repository after configuring the host's provider credentials:

```bash
BENCHMARK_REVISION=bfe2471c41f416d877e74bfa73cf0f29165c7567
BENCHMARK_DIR=/path/to/Paper-Writing-Exam
hf download Jack-Jieke-Wu/Paper-Writing-Exam \
  --repo-type dataset --revision "$BENCHMARK_REVISION" \
  --include 'paperwrite-bench-short/pwb-0001/**' --local-dir "$BENCHMARK_DIR"
TASK_DIR="$BENCHMARK_DIR/paperwrite-bench-short/pwb-0001"
JOB_ROOT=/path/to/harbor-jobs
TRIAL_DATASET_DIR=/path/to/Paper-Writing-Exam-Trials
AGENT_CONFIG_HASH=$(printf '%s\n' \
  'agent=codex' 'model=openai/gpt-5.6-terra' 'reasoning_effort=medium' \
  | sha256sum | cut -d' ' -f1)

uv run --extra harbor harbor run \
  --jobs-dir "$JOB_ROOT" \
  --path "$TASK_DIR" \
  --agent codex \
  --model openai/gpt-5.6-terra \
  --ak reasoning_effort=medium \
  --plugin paperbench-trial-export \
  --pk output_dir="$TRIAL_DATASET_DIR" \
  --pk benchmark_hf_revision="$BENCHMARK_REVISION" \
  --pk harbor_repo_commit=4407eb5227a2ff4f0d3f16b2eb48849382fdf276 \
  --pk integration_commit="$(git rev-parse HEAD)" \
  --pk agent_config_hash="$AGENT_CONFIG_HASH" \
  --pk private_manifest="$TASK_DIR/tests/private/source_manifest.json" \
  --pk upload=true \
  --pk dataset_repo=Jack-Jieke-Wu/Paper-Writing-Exam-Trials \
  --pk revision=main \
  --yes --n-concurrent 1
```

This exports final retry results on the host. Add
`--pk upload=true --pk dataset_repo=Jack-Jieke-Wu/Paper-Writing-Exam-Trials` to
publish the sanitized files and report the immutable Hub commit SHA. The
example above includes those options. Omit the plugin for unchanged Harbor
behavior. The manual exporter plus `hf upload` workflow remains available as a
fallback; see
[`docs/trial-dataset.md`](docs/trial-dataset.md).

GitHub is the source of truth for how tasks and integrations are built.
Hugging Face is the source of truth for the bytes in a published benchmark
release. Generated task trees, source corpora, agent outputs, and credentials
are not committed to GitHub.

## Benchmark families

- **AI-PaperOrchestra** (upstream: `PaperWritingBench`): sparse research idea
  and experimental log to a conference paper.
- **AI-PaperRecon** (upstream: `PaperWrite-Bench`): research overview to a
  reconstructed paper.
- **LifeSci-PaperRecon**: project-original biology/life-sciences corpus using
  the PaperRecon-style task recipe.

The public release contains three protocols:

| Dataset directory | Tasks | Protocol |
|---|---:|---|
| `paperwrite-bench-short` | 51 | PaperWrite-Bench `short` |
| `paperwritingbench-sparse-plotoff` | 200 | PaperWritingBench `sparse-plotoff` |
| `lifesci-paperrecon-short` | 22 | LifeSci-PaperRecon `short` |

Do not combine protocol names when reporting results. Sparse/dense inputs,
plot settings, and overview variants are separate benchmark conditions.
The current release is tagged `v0.3.1` at immutable revision
`bfe2471c41f416d877e74bfa73cf0f29165c7567` and contains 273 tasks. It adds the
22-task LifeSci-PaperRecon configuration while preserving the two existing
configs. For reproducible runs, use that tag or the recorded immutable revision
instead of the Hub default branch. The previous `v0.3.0` and `v0.2.0` releases
remain available.
Dataset release details are recorded in `docs/dataset-versioning.md`.

Run a task directly from the Hugging Face repository without maintaining a
local dataset checkout. Harbor resolves the immutable repository revision and
manages its temporary task cache:

```bash
harbor run \
  --repo "https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam/tree/bfe2471c41f416d877e74bfa73cf0f29165c7567/lifesci-paperrecon-short" \
  --include-task-name lspr-0001 \
  --agent codex \
  --model <provider>/<model> \
  --yes --n-concurrent 1
```

Replace the configuration subdirectory and task name for another protocol.
The Dataset Viewer is disabled because this repository contains executable
Harbor task trees rather than compatible tabular splits. In this command,
`--repo` is Harbor's Git-repository dataset source; `--dataset` is reserved
for Harbor Hub packages.

## Public benchmark release

The public HF repository contains self-contained Harbor task directories:

```text
<task-id>/
├── task.toml
├── instruction.md
├── environment/
├── solution/
└── tests/
```

Use an immutable HF revision for experiments. The release record is maintained
in [`docs/dataset-versioning.md`](docs/dataset-versioning.md), including the
converter commit, upstream source revision, task counts, and HF commit.

The task writer sees only the public material allowlist. Ground-truth papers,
rubrics, citation labels, and evaluator metadata remain verifier-only. The
binary Harbor reward checks the submission contract and safe LaTeX
recompilation; optional official evaluator metrics are diagnostic and do not
change that binary reward.

## Run a task

Install Harbor, then run a task directly from the reproducible `v0.3.1`
benchmark release. This is a complete single-task example for
PaperWrite-Bench `short` task `pwb-0001`:

```bash
harbor run \
  --repo "https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam/tree/bfe2471c41f416d877e74bfa73cf0f29165c7567/paperwrite-bench-short" \
  --include-task-name pwb-0001 \
  --agent codex \
  --model openai/gpt-5.6-sol \
  --yes --n-concurrent 1 \
  --job-name paperwrite-bench-pwb-0001
```

This command lets Harbor download and cache the task itself. The model name is
an example; configure the corresponding provider credentials and endpoint in
your Harbor environment before running it. To run locally downloaded files
instead, use `hf download` with the same immutable revision and pass the task
directory to `harbor run --path`.

Other ready-to-run task examples are:

```bash
# PaperWritingBench, sparse input with plots disabled
harbor run \
  --repo "https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam/tree/bfe2471c41f416d877e74bfa73cf0f29165c7567/paperwritingbench-sparse-plotoff" \
  --include-task-name pwbw-0001 \
  --agent codex \
  --model openai/gpt-5.6-sol \
  --yes --n-concurrent 1 \
  --job-name paperwritingbench-pwbw-0001

# LifeSci-PaperRecon, short protocol
harbor run \
  --repo "https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam/tree/bfe2471c41f416d877e74bfa73cf0f29165c7567/lifesci-paperrecon-short" \
  --include-task-name lspr-0001 \
  --agent codex \
  --model openai/gpt-5.6-sol \
  --yes --n-concurrent 1 \
  --job-name lifesci-paperrecon-lspr-0001
```

For judge-backed official metrics, pass verifier variables explicitly with
Harbor's `--verifier-env` flags. Keep their values in a private environment
file and never place them in a task, image, command log, or trial archive.

## Agent integrations

The repository also provides the integration layer for paper-writing agents.
Each adapter documents its immutable version, runtime, writer-visible input
allowlist, model settings, credential boundary, output mapping, and artifact
layout. See [`docs/agents.md`](docs/agents.md).

The common output contract is:

```text
/workspace/submission/
├── main.tex
├── references.bib
└── figures/ (optional)
```

The integrated `paper-run` adapter is registered as:

```text
paperbench_harbor.agents.paper_run:PaperRun
```

It installs pinned runtime components inside the task container, stages public
materials, runs the writing harness, exports the paper tree, and records
diagnostics without exposing verifier-private files.

Pinned versions are `paper-run` v0.5.0 at immutable release commit
`9925848adf195e68d3f3e3039959f9f2c19fb7a3`, OpenCode `1.18.25`, and Node 20.
The wrapper builds the pinned source with its committed lockfile, validates the
generated paper brief, stages only public materials, and runs one autonomous
headless plan with `--stage-timeout-multiplier 2`. Because the full 13-stage
plan can exceed two hours, Harbor runs should pass
`--agent-timeout-multiplier 4` when selecting `paper-run`.

The generated headless policy remains deny-by-default. It allows only fixed
repository metadata checks, read-only directory inspection, and figure copies
from `materials/figures/` into `paper/figures/srcs/`. Interpreters, arbitrary
file mutation, publication tools, environment dumping, and network commands
remain unlisted. The adapter supports new-paper production only; external
manuscript `review`, `transfer`, and `adopt` workflows are intentionally not
exposed through the benchmark integration.

Adding an agent should require a thin wrapper and contract tests, not a fork of
the benchmark tasks. Agent runs are exported with `scripts/export_trial.py` to
the public trial dataset described in [`docs/trial-dataset.md`](docs/trial-dataset.md).

## Build and test

```bash
make install
make lint
make test
```

The converters can reconstruct upstream data into a local, ignored directory
and emit a release directory with `--output-dir`. Generated datasets and
upstream corpora are deliberately not tracked by Git.

## Upstream projects and licensing

- [Google PaperOrchestra](https://github.com/google-research/paper-orchestra)
- [Agent4Science-UTokyo PaperRecon](https://github.com/Agent4Science-UTokyo/PaperRecon)
- [Harbor benchmark template](https://github.com/harbor-framework/benchmark-template)

The repository contains vendored upstream evaluator/search code where needed;
see [`src/paperbench_harbor/vendor/NOTICE.md`](src/paperbench_harbor/vendor/NOTICE.md).
Benchmark data and upstream code remain subject to their original licenses and
redistribution terms. The Dataset Card records the public release's mixed
provenance rather than asserting a blanket project license.
