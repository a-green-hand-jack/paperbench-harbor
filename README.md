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
example used by the current integration: benchmark release `v0.4.1`
(`367bbf67ea05d0ec3d580e062aadf5636b45fc65`), Harbor `v0.22.0`
(`4407eb5227a2ff4f0d3f16b2eb48849382fdf276`), and Codex
`openai/gpt-5.6-terra` with medium reasoning effort. Run it from a checkout of
this repository after configuring the host's provider credentials:

```bash
BENCHMARK_REVISION=367bbf67ea05d0ec3d580e062aadf5636b45fc65
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
The current release is tagged `v0.4.1` at immutable revision
`367bbf67ea05d0ec3d580e062aadf5636b45fc65` and contains 274 tasks. It retains
the existing 252 non-LifeSci tasks and repairs the 22-task LifeSci-PaperRecon
configuration so the 144 source tables are represented by 144 writer-visible
table fragments. For reproducible runs, use that tag or the recorded immutable
revision instead of the Hub default branch. Earlier releases remain available.
Dataset release details are recorded in `docs/dataset-versioning.md`.

Run a task directly from the Hugging Face repository without maintaining a
local dataset checkout. Harbor resolves the immutable repository revision and
manages its temporary task cache:

```bash
harbor run \
  --repo "https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam/tree/367bbf67ea05d0ec3d580e062aadf5636b45fc65/lifesci-paperrecon-short" \
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

Install Harbor, then run a task directly from the reproducible `v0.4.1`
benchmark release. This is a complete single-task example for
PaperWrite-Bench `short` task `pwb-0001`:

```bash
harbor run \
  --repo "https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam/tree/367bbf67ea05d0ec3d580e062aadf5636b45fc65/paperwrite-bench-short" \
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
  --repo "https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam/tree/367bbf67ea05d0ec3d580e062aadf5636b45fc65/paperwritingbench-sparse-plotoff" \
  --include-task-name pwbw-0001 \
  --agent codex \
  --model openai/gpt-5.6-sol \
  --yes --n-concurrent 1 \
  --job-name paperwritingbench-pwbw-0001

# LifeSci-PaperRecon, short protocol
harbor run \
  --repo "https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam/tree/367bbf67ea05d0ec3d580e062aadf5636b45fc65/lifesci-paperrecon-short" \
  --include-task-name lspr-0001 \
  --agent codex \
  --model openai/gpt-5.6-sol \
  --yes --n-concurrent 1 \
  --job-name lifesci-paperrecon-lspr-0001
```

For judge-backed official metrics, pass verifier variables explicitly with
Harbor's `--verifier-env` flags. Keep their values in a private environment
file and never place them in a task, image, command log, or trial archive.

## Fast End-to-End Smoke Test

After changing the benchmark, run the generated Hello World task before a
long representative-task evaluation. It uses the normal Harbor task layout,
workspace, Codex agent and isolated verifier, but its deterministic writing
brief is intentionally small. Generate it from the checked-out integration
code, then run the exact Codex configuration used for the smoke gate:

```bash
SMOKE_ROOT=/tmp/paperbench-harbor-smoke
JOB_ROOT=/path/to/harbor-jobs

uv run paperbench-harbor hello-world --output-dir "$SMOKE_ROOT"
# For a local Codex OAuth login, use the existing auth file only at runtime.
# With an API key, omit this prefix and export OPENAI_API_KEY instead.
CODEX_FORCE_AUTH_JSON=1 uv run --extra harbor harbor run \
  --jobs-dir "$JOB_ROOT" \
  --path "$SMOKE_ROOT/hello-world/hello-world-0001" \
  --agent codex \
  --model openai/gpt-5.6-terra \
  --ak reasoning_effort=medium \
  --yes --n-concurrent 1 \
  --job-name paperbench-hello-world-terra-medium
```

A successful run has binary reward `1` and records the Codex model and
reasoning configuration in the job metadata. The task also checks that the
agent consumed its mounted brief, rather than accepting arbitrary compilable
LaTeX. It is a fast integration signal, not a substitute for contract,
fidelity, determinism or representative real-task validation. See
[`docs/hello-world-smoke.md`](docs/hello-world-smoke.md) for the release and
verification procedure. The OAuth credential is injected only into the
ephemeral agent container; never place `auth.json` or API keys in a task,
image, repository, or job archive.

## Submission contract

Every task in every protocol grades the same deliverable: a complete LaTeX
source tree at a fixed location inside the task container.

```text
/workspace/submission/
├── main.tex
├── references.bib
└── figures/ (optional)
```

The contract is agent-neutral, and running a published task never requires
installing this repository. Harbor's native agents (`codex`, `claude-code`)
write into it directly. An external writing harness with its own workspace
layout needs a thin Harbor agent wrapper that exports its output tree into
this contract; that wrapper belongs to whoever runs the harness. The benchmark
ships no agent adapters.

See [`docs/submission-contract.md`](docs/submission-contract.md) for what the
verifier checks and what a wrapper has to get right.

Agent runs are exported with `scripts/export_trial.py` to the public trial
dataset described in [`docs/trial-dataset.md`](docs/trial-dataset.md).

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
