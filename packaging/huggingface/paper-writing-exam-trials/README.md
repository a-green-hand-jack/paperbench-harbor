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

This public dataset contains sanitized records of completed evaluations against
[Paper-Writing-Exam](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam).
It preserves trial summaries, event indexes, allowlisted artifacts, final
submissions, and verifier results. It is not a runnable task dataset.

## Dataset relationship

| Dataset | Role | May it be used as a Harbor task? |
|---|---|---|
| [Paper-Writing-Exam](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam) | Canonical task input | Yes |
| `Paper-Writing-Exam-Trials` | Evidence from completed task runs | No |
| [Paper-Writing-Exam-Source-Archive](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam-Source-Archive) | Task-paper and source-input provenance | No |

Every trial records the immutable task-dataset revision, task ID, task checksum,
Harbor commit, integration revision, agent/model/provider, and non-secret
configuration hash. Match these fields before comparing trials.

## Layout

```text
data/trials.jsonl
data/events.jsonl
data/trials.schema.json
data/events.schema.json
artifacts/<trial-id>.tar.gz
manifests/<trial-id>.json
manifests/release.json
```

`trials.jsonl` has one result record per Harbor trial. `events.jsonl` is a
one-event-per-step index derived from the native ATIF trajectory. An artifact
archive preserves the allowlisted native trajectory, submission, agent logs,
Harbor `result.json`, and verifier `evaluation.json` needed to inspect that one
trial.

## Use trajectories carefully

Trajectories can be used for reproducibility checks, error analysis, auditing a
specific score, studying agent behavior, and aggregate analysis with compatible
task revisions. They are observational outputs of one agent configuration, not
ground truth, a task definition, or evidence of general capability.

Do not use trajectories as a training corpus. Do not infer that a final paper
was correct beyond the verifier result recorded for the matching task revision.
Never combine a trajectory with task-private ground truth absent from its
sanitized archive.

## Retrieve one trial

Use an immutable trial revision and download the summary/manifest first:

```bash
hf download Jack-Jieke-Wu/Paper-Writing-Exam-Trials \
  data/trials.jsonl \
  manifests/<trial-id>.json \
  --type dataset \
  --revision <trial-tag-or-commit> \
  --local-dir ./paper-writing-exam-trial
```

Then retrieve `artifacts/<trial-id>.tar.gz` only when the full trajectory or
submission is needed. Inspect its matching task revision in Paper-Writing-Exam;
use the source archive only for independent input-provenance review.

## Privacy and licensing

The exporter rejects credentials, cookies, private task material, ground-truth
papers, and unrelated host files. A public archive does not grant permission to
redistribute benchmark data, model outputs, or third-party source material
beyond their original terms. Review every new export before publication.

Maintainers publish sanitized trials with the exporter in
[paperbench-harbor](https://github.com/a-green-hand-jack/paperbench-harbor).
