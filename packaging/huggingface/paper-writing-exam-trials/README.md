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
