# Public Trial Dataset

The benchmark inputs and the agent runs are separate products.

- Public task package: `Jack-Jieke-Wu/Paper-Writing-Exam`
- Public run archive: `Jack-Jieke-Wu/Paper-Writing-Exam-Trials`

The public repository stores sanitized Harbor trial packages for reproducible
analysis. Public visibility is not a substitute for secret handling: every
artifact is checked before upload, and benchmark, model-output, and
third-party redistribution terms still apply.

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
