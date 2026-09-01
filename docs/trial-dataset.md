# Public Trial Dataset

The benchmark inputs and the agent runs are separate products.

- Public task package: `Jack-Jieke-Wu/Paper-Writing-Exam`
- Public run archive: `Jack-Jieke-Wu/Paper-Writing-Exam-Trials`

The public repository stores sanitized Harbor trial packages for reproducible
analysis. Public visibility is not a substitute for secret handling: every
artifact is checked before upload, and benchmark, model-output, and
third-party redistribution terms still apply.

## What Is A Trial?

A trial is one complete Harbor execution of one benchmark task by one agent
configuration. The agent trajectory is the central part of a trial, but the
trial also records the final submission, Harbor result, verifier output, timing,
and reproducibility metadata.

The save path is deliberately a two-stage process. It can be run manually, or
the opt-in `paperbench-trial-export` Harbor JobPlugin can perform the second
stage after the final job result:

```text
harbor run [--plugin paperbench-trial-export]
    -> local Harbor job/trial directory
    -> scripts/export_trial.py
    -> local sanitized trial dataset directory
    -> hf upload
    -> Paper-Writing-Exam-Trials
```

Without the plugin, `harbor run` does not export or upload anything to Hugging
Face. With the plugin, export still happens locally first and upload is enabled
only with `--pk upload=true`. Both operations run on the host, never in the
evaluated task container.

## Automatic host-side publishing

Install the integration against Harbor `v0.22.0` (commit
`4407eb5227a2ff4f0d3f16b2eb48849382fdf276`):

```bash
python3 -m pip install -e '.[harbor]'
```

Use Harbor's repeatable plugin kwargs for the required provenance. The plugin
uses `JobResult.trial_results`, so Harbor retries are already resolved and
intermediate retry directories are not published:

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

For a local-only export, leave upload disabled (the default). The command above
uses the authorized public trial repository. For a different host-side dataset
repository, change:

```text
--pk upload=true
--pk dataset_repo=my-org/my-paper-writing-exam-trials
--pk revision=main
```

The plugin writes `trial-export-report.json` beside the Harbor job result. It
records per-trial export/upload status and the immutable Hugging Face commit
SHA when upload succeeds. `include_failed=true` and `include_cancelled=true`
can be supplied when those final results should also be exported. A failed
upload leaves the local sanitized output intact and does not change Harbor's
benchmark reward or original job result.

For multiple tasks, use `private_manifest_map=/path/to/task-manifests.json`
instead of one shared manifest. The mapping is keyed by Harbor task name or
task ID. If omitted, the plugin resolves a local task's
`tests/private/source_manifest.json` from the resolved Harbor task config when
possible; ambiguous resolution fails closed.

The plugin accepts no credential argument. `huggingface_hub` uses the host's
existing `hf auth` state or `HF_TOKEN`; these credentials are never passed to
the agent, verifier, task files, or trial archive.

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

One line in `data/trials.jsonl` describes one Harbor trial. Events are derived
from Harbor's native ATIF files (`agent/trajectory*.json`) and stored as one
line per ATIF step. The original ATIF trajectories and raw agent logs remain
in the trial archive so no information is lost by the query index.
The exporter accepts the ATIF versions implemented by Harbor `v0.20.0`
(`ATIF-v1.0` through `ATIF-v1.7`). Local file references to external
subagent trajectories must resolve to another allowlisted trajectory in the
same archive; remote references and missing targets are rejected.

## Provenance

Every trial must identify:

- `benchmark_hf_repo` and immutable `benchmark_hf_revision`;
- `task_id` and `task_checksum`;
- `harbor_repo_commit`;
- `agent_name`, `agent_version`, and `integration_commit`;
- model/provider and a hash of non-secret agent configuration;
- Harbor reward, official evaluator metrics, status, and timing;
- artifact hashes and `sanitization_version`.

Before exporting, provide the generated task's verifier-only
`tests/private/source_manifest.json` with `--private-manifest`. The exporter
compares SHA-256 values against that manifest so a ground-truth file that was
renamed into an otherwise allowed directory is still rejected. The manifest is
read locally and is never copied into the public trial dataset.

The benchmark task tree is not copied into this repository. A consumer can
resolve it from the public HF revision and verify the task checksum.

## Save A Trial

### 1. Keep The Harbor Output

Give Harbor an explicit jobs directory so the source trial is easy to locate:

```bash
JOB_ROOT=/path/to/harbor-jobs
JOB_NAME=paperwrite-pwb-0001

harbor run \
  --jobs-dir "$JOB_ROOT" \
  --path /path/to/Paper-Writing-Exam/paperwrite-bench-short/pwb-0001 \
  --agent codex \
  --model openai/gpt-5.6-sol \
  --yes --n-concurrent 1 \
  --job-name "$JOB_NAME"
```

Harbor stores the job under `$JOB_ROOT/$JOB_NAME` and creates one child
directory for each trial. For a single-step run, set `TRIAL_DIR` to the child
directory you want to publish, for example:

```bash
TRIAL_DIR="$JOB_ROOT/$JOB_NAME/<trial-directory-name>"
```

The exact child name is generated by Harbor. A single-step trial normally has
`result.json`, `agent/`, `verifier/`, and collected `artifacts/` files at its
root. A multi-step trial may instead place these directories below
`steps/<step-name>/`; the exporter handles both layouts.
The `--no-delete` option is useful when the task container itself must remain
available for debugging, but it is not the mechanism that publishes a trial.

### 2. Export And Sanitize It

Run the exporter from this repository. It reads one trial directory, creates a
single consistent snapshot, rejects credentials and verifier-private material,
and writes the archive plus the query indexes into `OUTPUT_DIR`:

```bash
TRIAL_DATASET_DIR=/path/to/Paper-Writing-Exam-Trials
TASK_DIR=/path/to/Paper-Writing-Exam/paperwrite-bench-short/pwb-0001
BENCHMARK_HF_REVISION=<40-character-Hugging-Face-commit>
HARBOR_REPO_COMMIT=<paperbench-harbor-commit>
INTEGRATION_COMMIT=<agent-integration-commit>
AGENT_CONFIG_FILE=/path/to/non-secret-agent-config.json
AGENT_VERSION=<agent-version-from-result.json>

python3 scripts/export_trial.py \
  --trial-dir "$TRIAL_DIR" \
  --output-dir "$TRIAL_DATASET_DIR" \
  --private-manifest "$TASK_DIR/tests/private/source_manifest.json" \
  --task-id pwb-0001 \
  --benchmark PaperWrite-Bench \
  --protocol short \
  --benchmark-hf-revision "$BENCHMARK_HF_REVISION" \
  --harbor-repo-commit "$HARBOR_REPO_COMMIT" \
  --agent-name codex \
  --agent-version "$AGENT_VERSION" \
  --integration-commit "$INTEGRATION_COMMIT" \
  --model openai/gpt-5.6-sol \
  --provider openai \
  --agent-config-file "$AGENT_CONFIG_FILE"
```

`--private-manifest` is read locally to compare source-material hashes. The
manifest itself is never copied into the public output. The agent config file
must contain no secrets; alternatively, replace `--agent-config-file` with
`--agent-config-hash <64-character-SHA-256>`.

On success, the exporter adds these files to `TRIAL_DATASET_DIR`:

```text
artifacts/<trial-id>.tar.gz
manifests/<trial-id>.json
data/trials.jsonl       # one summary record appended
data/events.jsonl       # one record per trajectory step, when events exist
```

The archive is deterministic and its SHA-256 is recorded both in
`data/trials.jsonl` and `manifests/<trial-id>.json`. The exporter refuses to
overwrite an existing trial ID.

### 3. Inspect Before Uploading

Inspect the generated metadata and archive locally:

```bash
python3 -m json.tool "$TRIAL_DATASET_DIR/manifests/<trial-id>.json"
tar -tzf "$TRIAL_DATASET_DIR/artifacts/<trial-id>.tar.gz"
```

The archive should contain the allowlisted trajectory, final submission,
Harbor result, verifier output, and agent diagnostics. It must not contain
`.env`, credential files, `solution/`, `tests/private/`, `eval_points.json`, or
ground-truth papers.

### 4. Upload The Sanitized Directory

Upload only the inspected exporter output, outside the evaluated task
container:

```bash
hf upload Jack-Jieke-Wu/Paper-Writing-Exam-Trials \
  "$TRIAL_DATASET_DIR" . \
  --repo-type dataset \
  --exclude '.git/**' \
  --commit-message "Add trial <trial-id>"
```

This creates a Hugging Face commit. Record the immutable commit SHA returned by
the upload as `TRIAL_DATASET_REVISION`; it is the revision to use when viewing
the trial. The output directory is the local staging area; the Hugging Face
repository is the durable public copy. Do not pass HF tokens or model
credentials into the Harbor task merely to publish its own artifacts.

## View One Trial

First read the summary record. This does not download the potentially larger
archive:

```bash
TRIAL_ID=6c45b4f4-d767-4adf-90b5-a59bcc300298
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

`data/events.jsonl` is an optional index for repositories that contain one or
more ATIF events. Download it separately when it is present:

```bash
hf download Jack-Jieke-Wu/Paper-Writing-Exam-Trials \
  data/events.jsonl \
  --repo-type dataset \
  --revision "$TRIAL_DATASET_REVISION" \
  --local-dir "$VIEW_DIR"
```

Print the selected summary and its indexed events:

```bash
python3 - "$VIEW_DIR/data/trials.jsonl" "$VIEW_DIR/data/events.jsonl" "$TRIAL_ID" <<'PY'
import json
import os
import sys

trials_path, events_path, trial_id = sys.argv[1:]

with open(trials_path, encoding="utf-8") as handle:
    for line in handle:
        item = json.loads(line)
        if item.get("trial_id") == trial_id:
            print(json.dumps(item, ensure_ascii=False, indent=2))

if os.path.exists(events_path):
    print("\nIndexed events:")
    with open(events_path, encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            if item.get("trial_id") == trial_id:
                print(json.dumps(item, ensure_ascii=False))
else:
    print("\nNo event index was published for this release.")
PY
```

To inspect the complete trial, download and unpack its archive:

```bash
hf download Jack-Jieke-Wu/Paper-Writing-Exam-Trials \
  "artifacts/$TRIAL_ID.tar.gz" \
  --repo-type dataset \
  --revision "$TRIAL_DATASET_REVISION" \
  --local-dir "$VIEW_DIR"

mkdir -p "$VIEW_DIR/unpacked"
tar -xzf "$VIEW_DIR/artifacts/$TRIAL_ID.tar.gz" -C "$VIEW_DIR/unpacked"
```

The most useful files are:

```text
$VIEW_DIR/unpacked/agent/trajectory*.json                 # single-step ATIF trajectory
$VIEW_DIR/unpacked/steps/*/agent/trajectory*.json          # multi-step trajectories
$VIEW_DIR/unpacked/artifacts/workspace/submission/         # single-step output
$VIEW_DIR/unpacked/steps/*/artifacts/workspace/submission/ # multi-step output
$VIEW_DIR/unpacked/harbor/result.json                      # Harbor result and reward
$VIEW_DIR/unpacked/verifier/evaluation.json                # optional official metrics
```

`data/events.jsonl` is a query index derived from the original ATIF trajectory;
the archive is the source to use when the complete original step structure or
agent logs are needed.

## Archive allowlist

The initial exporter may include:

- Harbor `result.json`;
- Harbor `config.json`, `lock.json`, `trial.log`, and `exception.txt` when present;
- native ATIF trajectories under `agent/trajectory*.json`;
- trial-root `agent/` and `verifier/` logs;
- `artifacts/workspace/submission/` and other Harbor-collected artifacts;
- `logs/agent/`;
- `logs/verifier/evaluation.json`;
- agent-specific checkpoints, stage history, and diagnostics located below the
  trial artifact root.

It rejects `solution/`, `tests/private/`, `eval_points.json`, ground-truth
papers, `.env`, auth files, SSH credentials, and unrelated host files.

## Upload policy

Run export and inspection locally first. For example:

```bash
python scripts/export_trial.py \
  --trial-dir /path/to/jobs/run/trial-id \
  --output-dir /path/to/Paper-Writing-Exam-Trials \
  --private-manifest /path/to/task/tests/private/source_manifest.json \
  --task-id pwb-0001 \
  --benchmark PaperWrite-Bench \
  --protocol short \
  --benchmark-hf-revision <immutable-revision> \
  --harbor-repo-commit <commit> \
  --agent-name codex \
  --agent-version <version> \
  --integration-commit <commit> \
  --agent-config-hash <sha256>
```

Upload only the resulting package and
metadata files. The upload step must fail closed if the source contains a
credential pattern or a forbidden private path. Never pass HF or model tokens
to a task container merely to publish its own artifacts; publishing happens
outside the evaluated container.
