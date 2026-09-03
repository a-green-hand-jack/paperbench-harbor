---
pretty_name: Paper-Writing Exam Source Archive
language:
- en
tags:
- paper-writing
- provenance
- source-archive
- harbor
license: other
viewer: false
---

# Paper-Writing Exam Source Archive

This dataset is the immutable provenance archive for
[Paper-Writing-Exam](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam).
It stores the task-paper registry and the original workflow inputs used to
construct a fixed task release. It is an archive product, not a runnable Harbor
task dataset.

## Dataset relationship

| Dataset | Purpose | May Harbor run it? |
|---|---|---|
| [Paper-Writing-Exam](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam) | Runnable benchmark task trees | Yes |
| [Paper-Writing-Exam-Trials](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam-Trials) | Sanitized trial trajectories and results | No |
| `Paper-Writing-Exam-Source-Archive` | Registry plus original construction inputs | No |

No task directory, solution, verifier, or trial artifact is part of this
archive. Archive updates do not alter a task release or its checksum.

## Current coverage

The initial archive maps the 274-task `Paper-Writing-Exam` release at
`v0.4.1` / `367bbf67ea05d0ec3d580e062aadf5636b45fc65`:

- 51 `paperwrite-bench-short` tasks;
- 200 `paperwritingbench-sparse-plotoff` tasks;
- 22 `lifesci-paperrecon-short` tasks; and
- one first-party `hello-world` smoke task, which correctly has no source paper
  or external archive input.

It contains 273 archived upstream source trees and a per-file SHA-256 manifest.
The LifeSci source records include the pinned arXiv identifier/version, source
URL, paper license, code locator, and code revision recorded by the build. The
two adapted upstream benchmark families use their official stable sample IDs
and pinned upstream revisions where no canonical arXiv mapping was available in
the upstream dataset.

## Files

```text
README.md
archive-metadata.json
registry/task-paper-registry.jsonl
manifests/source-archive-manifest.jsonl
sources/
```

`registry/task-paper-registry.jsonl` has one record for each `(config, task_id,
task release)`. It links the task identity and checksum to the upstream sample
or paper, fixed conversion revision, and source archive tree. The first-party
smoke task is explicitly marked `not_applicable` rather than being assigned a
fictional paper.

`manifests/source-archive-manifest.jsonl` records every archived file's
repository-relative path, size, SHA-256, source kind, and paper/source metadata.

## How to use this archive

Use an immutable archive revision when inspecting provenance:

```bash
hf download Jack-Jieke-Wu/Paper-Writing-Exam-Source-Archive \
  registry/task-paper-registry.jsonl \
  --type dataset \
  --revision <archive-tag-or-commit> \
  --local-dir ./paper-writing-exam-source-archive
```

Use the registry to locate a source tree and compare it with a task's release
identity. Do not mount, copy, or expose these files as a Harbor task's
`environment/materials/`, `solution/`, or `tests/` content. The task dataset
remains self-contained and is the sole source for evaluation input.

## Licensing and redistribution

Each archive record preserves its upstream locator and license metadata. The
archive does not replace the original licenses of PaperWrite-Bench,
PaperWritingBench/PaperOrchestra, LifeSci source papers, code repositories, or
conference templates. Reuse and redistribution must comply with the per-source
terms. A code locator with no declared license remains a locator; it is not a
new permission grant.
