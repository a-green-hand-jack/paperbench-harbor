---
pretty_name: Paper-Writing Exam Agent Trials
language:
- en
tags:
- paper-writing
- agent-trajectory
- evaluation
- harbor
task_categories:
- text-generation
license: other
---

# Paper-Writing Exam Agent Trials

This is a **public** archive of complete agent trials run on the public
`Jack-Jieke-Wu/Paper-Writing-Exam` benchmark. It contains sanitized trajectories,
agent outputs, final papers, Harbor results, verifier metrics, and agent-specific
diagnostics.

The repository is public by design. Access to this repository does not permit
redistribution of the benchmark, model outputs, or third-party source material.
Every upload must still pass the local fail-closed exporter checks.

## Layout

```text
README.md
data/
├── trials.jsonl
├── events.jsonl
├── trials.schema.json
└── events.schema.json
artifacts/
└── <trial-id>.tar.gz
manifests/
├── release.json
└── <trial-id>.json
```

`data/trials.jsonl` has one record per Harbor trial. `data/events.jsonl` has one
record per step derived from Harbor's native ATIF files
(`agent/trajectory*.json`). The compressed archive contains the original ATIF
trajectories, allowlisted submission, agent logs/checkpoints, Harbor
`result.json`, and verifier `evaluation.json`.
For Harbor `v0.20.0`, accepted native trajectory versions are
`ATIF-v1.0` through `ATIF-v1.7`; local file-based subagent references must
resolve to included trajectory files.

Archives retain Harbor's native `agent/`, `verifier/`, `steps/`, and
`artifacts/` directories so single-step and multi-step trials remain
reconstructable.

## Saving A New Trial

`harbor run` writes a trial locally. The recommended opt-in path is the
host-side `paperbench-trial-export` plugin; the manual exporter below remains
the fallback when the plugin is not installed:

```bash
python3 scripts/export_trial.py \
  --trial-dir /path/to/harbor-jobs/<job-name>/<trial-id> \
  --output-dir /path/to/Paper-Writing-Exam-Trials \
  --private-manifest /path/to/task/tests/private/source_manifest.json \
  --task-id pwb-0001 \
  --benchmark PaperWrite-Bench \
  --protocol short \
  --benchmark-hf-revision <immutable-benchmark-commit> \
  --harbor-repo-commit <paperbench-harbor-commit> \
  --agent-name codex \
  --agent-version <agent-version> \
  --integration-commit <integration-commit> \
  --model <provider>/<model> \
  --provider <provider> \
  --agent-config-file /path/to/non-secret-agent-config.json
```

The exporter creates `artifacts/<trial-id>.tar.gz`,
`manifests/<trial-id>.json`, and appends a record to `data/trials.jsonl`. When
the trial contains ATIF events, it also appends their one-event-per-step index
to `data/events.jsonl`. It performs the credential/private-file checks before
committing those outputs. Inspect the result, then upload the staging
directory separately:

```bash
hf upload Jack-Jieke-Wu/Paper-Writing-Exam-Trials \
  /path/to/Paper-Writing-Exam-Trials . \
  --repo-type dataset \
  --exclude '.git/**' \
  --commit-message "Add trial <trial-id>"
```

Record the immutable commit SHA returned by this upload as
`TRIAL_DATASET_REVISION`; use that value in the viewing commands below.

The full workflow, including how to choose `--jobs-dir`, is documented in the
source repository's [`docs/trial-dataset.md`](https://github.com/a-green-hand-jack/paperbench-harbor/blob/main/docs/trial-dataset.md).

## View One Trial

Use the trial ID from `data/trials.jsonl`, then download its summary and
manifest without downloading every archive:

```bash
TRIAL_ID=<trial-id>
TRIAL_DATASET_REVISION=<40-character-Hugging-Face-commit>
VIEW_DIR=/tmp/paper-writing-trial
mkdir -p "$VIEW_DIR"

hf download Jack-Jieke-Wu/Paper-Writing-Exam-Trials \
  data/trials.jsonl \
  "manifests/$TRIAL_ID.json" \
  --repo-type dataset \
  --revision "$TRIAL_DATASET_REVISION" \
  --local-dir "$VIEW_DIR"
```

If `data/events.jsonl` exists in the selected release, download it separately
to inspect the one-event-per-step index.

To view the complete trajectory and final output, download and unpack the
single archive:

```bash
hf download Jack-Jieke-Wu/Paper-Writing-Exam-Trials \
  "artifacts/$TRIAL_ID.tar.gz" \
  --repo-type dataset \
  --revision "$TRIAL_DATASET_REVISION" \
  --local-dir "$VIEW_DIR"
mkdir -p "$VIEW_DIR/unpacked"
tar -xzf "$VIEW_DIR/artifacts/$TRIAL_ID.tar.gz" -C "$VIEW_DIR/unpacked"
```

Then inspect:

```text
$VIEW_DIR/unpacked/agent/trajectory*.json                 # single-step trajectory
$VIEW_DIR/unpacked/steps/*/agent/trajectory*.json          # multi-step trajectories
$VIEW_DIR/unpacked/artifacts/workspace/submission/         # single-step output
$VIEW_DIR/unpacked/steps/*/artifacts/workspace/submission/ # multi-step output
$VIEW_DIR/unpacked/harbor/result.json
$VIEW_DIR/unpacked/verifier/evaluation.json
```

`data/events.jsonl` is a one-event-per-step index derived from the original
Harbor ATIF trajectory. The original trajectory and agent logs are preserved in
the archive.

## Provenance

Each trial references the benchmark without duplicating its task tree using:

- `benchmark_hf_repo` and immutable `benchmark_hf_revision`;
- `task_id` and `task_checksum`;
- `harbor_repo_commit`;
- `agent_name`, `agent_version`, and `integration_commit`;
- model/provider and a hash of non-secret configuration;
- Harbor reward, official metrics, timing, and artifact SHA-256.

Exports require the task's verifier-only `tests/private/source_manifest.json`
and a SHA-256 hash of the non-secret agent configuration (or a configuration
file from which that hash can be computed).
The exporter compares source-material hashes before writing any output, and
does not copy that manifest into this repository.

## Security and privacy

The exporter rejects API keys, bearer tokens, cookies, credential files, host
credentials, encoded credentials, `solution/`, `tests/private/`,
`eval_points.json`, ground-truth papers, and unrelated host files. It scans a
single temporary source snapshot, then derives the archive, event index, and
manifest from that same snapshot. It does not upload task containers or publish
from inside an evaluated container.

Do not upload raw environment files, authentication state, prompts containing
secrets, or data that the benchmark license does not permit you to retain.
Review every generated manifest before uploading it to this public repository.

Schemas are stored in `data/*.schema.json`. The local exporter and its tests are
maintained at:

<https://github.com/a-green-hand-jack/paperbench-harbor>
