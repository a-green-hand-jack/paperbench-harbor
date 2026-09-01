# Dataset Versioning

The published Hugging Face dataset is versioned independently from this
repository, but every dataset release must be traceable to the exact converter
code and upstream source data used to produce it.

## Release Record

For each regenerated dataset, record:

- the PaperBench Harbor merge commit;
- the converter source revision;
- the upstream benchmark source revision or archive;
- the protocol and task counts;
- the final Hugging Face commit revision;
- a stable Hugging Face tag such as `v0.2.0`.

The generated `dataset-manifest.jsonl` is the task-level record. The dataset
card should also contain a short changelog mapping each public version to its
source and converter revisions.

## Publishing Workflow

1. Merge and record the code change in GitHub.
2. Regenerate all tasks from the pinned upstream source using the merged code.
3. Run converter tests and dataset integrity checks, including representative
   Docker build-context checks.
4. Upload the regenerated directories to the Hugging Face dataset repository.
5. Record the final Hub commit SHA and create a release tag, for example
   `v0.2.0`.
6. Use that tag or the immutable commit SHA in benchmark runs. Do not rely on
   the dataset repository's default branch for reproducible experiments.

Previous revisions must remain available. A corrected release creates a new
revision; it does not rewrite or delete the old one.

## Current Dataset

[`Jack-Jieke-Wu/Paper-Writing-Exam`](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam)
contains the 251-task public release. The Hub refs must be treated literally:
as of 2026-09-01, tag `v0.3.1` points to
`bfe2471c41f416d877e74bfa73cf0f29165c7567`, while the earlier tag `v0.2.0` points
to `b13998a4b895ad7f07ee0fc38c98fb3dcb4c300e`; the default `main` branch
points to `5fe375dbd440409f0180e10dee213b1685c8f40d`. Use the tag or commit
SHA explicitly in experiments. The earlier revision
`b3672c640689d377dd17ccc2960d215c8d64dd7f` remains available for historical
comparison but predates the issue #6 follow-up fixes.

Generated task trees are local build outputs. Download them from the immutable
HF revision for evaluation, or pass an external directory to the converter's
`--output-dir`; do not commit them to this repository.

Agent trial archives are maintained separately in the public
`Jack-Jieke-Wu/Paper-Writing-Exam-Trials` dataset and are linked to this public
release through the immutable revision, task ID, and task checksum.

## Documentation-Only Hub Updates

Updating the Dataset Card advances the Hub `main` commit without changing any
task bytes. The Dataset Card added on 2026-09-01 is commit
`f9260ee7599b87b7482b5872de61f14c43cef892`; it does not constitute a new task
release. Experiment records must continue to identify the immutable task
revision they actually downloaded.
