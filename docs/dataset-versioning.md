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

`Jack-Jieke-Wu/Paper-Writing-Exam` currently contains the 251-task release at
revision `b3672c640689d377dd17ccc2960d215c8d64dd7f`. That revision predates
the issue #6 follow-up fixes. The next regenerated release should use a new
version and document the merge commit and final Hub revision in its dataset
card.
