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

Harbor task-tree repositories are not conventional tabular datasets. When the
Hugging Face Dataset Viewer cannot infer compatible splits, set `viewer: false`
in the dataset card instead of adding synthetic `train`/`validation`/`test`
data. The card should document the sparse `hf download --include` task-fetch
command and the immutable revision used for reproduction. The Viewer setting is
card metadata on the moving `main` revision and does not modify an immutable
task release.

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
currently contains the 273-task release at tag `v0.3.1` and revision
`bfe2471c41f416d877e74bfa73cf0f29165c7567`. The current `main` card revision
`08850e7f61b0624de8537d24dffec22e3d8c1823` disables the Dataset Viewer because
the repository contains executable Harbor task trees rather than tabular
splits. This metadata-only update leaves the immutable `v0.3.1` task tree
unchanged. The release adds the 22-task `lifesci-paperrecon-short`
configuration to the two existing configurations. The previous `v0.3.0` and
`v0.2.0` releases remain available for reproducing earlier results.

For a direct single-task run, use the Hugging Face CLI include pattern to fetch
only the matching task, then pass that local task directory to Harbor. The full
dataset is not downloaded:

```bash
hf download Jack-Jieke-Wu/Paper-Writing-Exam \
  --repo-type dataset \
  --revision bfe2471c41f416d877e74bfa73cf0f29165c7567 \
  --include 'lifesci-paperrecon-short/lspr-0001/**' \
  --local-dir ./paper-writing-exam

harbor run \
  --path ./paper-writing-exam/lifesci-paperrecon-short/lspr-0001 \
  --agent codex \
  --model <provider>/<model> \
  --yes --n-concurrent 1
```

On the Ubuntu Harbor host, the corresponding generated task trees are:

```text
/home/user/dev/paperbench-harbor/datasets/paperwrite-bench-short
/home/user/dev/paperbench-harbor/datasets/paperwritingbench-sparse-plotoff
```
