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

Harbor task-tree repositories are not conventional tabular datasets. When the
Hugging Face Dataset Viewer cannot infer compatible splits, set `viewer: false`
in the dataset card instead of adding synthetic `train`/`validation`/`test`
data. The card should document the direct Harbor `--repo` task-fetch command
and the immutable revision used for reproduction. This metadata does not
modify the immutable task release.

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
currently contains the 274-task release at tag `v0.4.0`, whose immutable task
revision is `fac54a81702f62b38c765de9e85615b4eb31a470`. It adds the standalone
`hello-world/hello-world-0001` configuration to the 273-task `v0.3.1` release.
The earlier `v0.3.1`, `v0.3.0`, and `v0.2.0` releases remain available and must
be used when reproducing results from those releases.

For a direct single-task run, point Harbor at the Hugging Face dataset tree and
filter by task name. No user-managed local dataset checkout is required:

```bash
harbor run \
  --repo "https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam/tree/fac54a81702f62b38c765de9e85615b4eb31a470/hello-world" \
  --include-task-name hello-world-0001 \
  --agent codex \
  --model <provider>/<model> \
  --yes --n-concurrent 1
```

Harbor uses its own task cache and repository checkout internally. The
immutable revision and task filter keep the run reproducible. `--dataset` is
reserved for Harbor Hub packages; use `--repo` for this Hugging Face Git source.

### v0.4.0

- Hugging Face task revision: `fac54a81702f62b38c765de9e85615b4eb31a470`;
- stable tag: `v0.4.0`;
- PaperBench Harbor merge commit:
  `55b216fc72abfd45e6265d0fb3378b83c95f42f5`;
- configuration: one first-party `hello-world/hello-world-0001` task using
  protocol `hello-world`;
- contract validation and deterministic regeneration: passed;
- real-agent end-to-end evidence: Harbor `0.22.0` ran the immutable Hub task
  with Codex `0.153.0`, `openai/gpt-5.6-terra`, and
  `reasoning_effort=medium`; the trial completed without exception and received
  reward `1.0`. Its sanitized trajectory is Trial
  `ff37fdb1-2bd0-47da-b763-a267e2fe32a4` at
  `Jack-Jieke-Wu/Paper-Writing-Exam-Trials` revision
  `7d2e41f8020a265eb7df9697b1e6e4362407b399`.

### Known defect in v0.3.1

19 of the 22 `lifesci-paperrecon-short` tasks instruct the writing agent to
read `/workspace/materials/tables/`, which those tasks do not ship. Only
`lspr-0014`, `lspr-0019` and `lspr-0022` have that directory. Seven tasks also
lack the `upstream_data_warnings.md` safeguard. `paperwrite-bench-short` is
unaffected, because all 51 of its papers have tables.

The cause is that this release was generated at converter revision
`b0eee6a28295b0e00c33e58bbad6813fdb8ecd50`, which predates `024c1cd`. That
commit made the instruction's tables/figures paragraphs conditional and added
the release-blocking `missing_instruction_material` contract check. Regenerating
this release from the current `main` therefore fails closed rather than
re-emitting the defect.

Anyone reproducing results from `v0.3.1` should know that its LifeSci
instructions do not describe their own materials. Tracked in issue #37.

### v0.3.1

- Hugging Face commit revision: `bfe2471c41f416d877e74bfa73cf0f29165c7567`;
- stable tag: `v0.3.1`;
- PaperBench Harbor merge commit: not available at publication time because
  this release was generated before its implementation branch was merged;
- converter/source revision: `b0eee6a28295b0e00c33e58bbad6813fdb8ecd50`;
- source: the project-original LifeSci-PaperRecon corpus, with 22 admitted
  papers (`paper_1`, `paper_2`, `paper_3`, `paper_6`, `paper_8`, `paper_11`,
  `paper_15`, `paper_17`, `paper_18`, `paper_19`, `paper_20`, `paper_21`,
  `paper_23`, `paper_24`, `paper_26`, `paper_28`, `paper_29`, `paper_30`,
  `paper_32`, `paper_33`, `paper_35`, and `paper_38`);
- protocol: LifeSci-PaperRecon `short`, task IDs `lspr-0001` through
  `lspr-0022`;
- source verification: 22/22 deterministic construction gates passed, including
  restricted template/oracle compilation; the Harbor fidelity audit passed
  22/22 tasks with `determinism_ok: true`;
- Harbor smoke evidence: on `lspr-0001` downloaded from `v0.3.1`, Harbor 0.20.0
  produced oracle reward `1.0` and NOP reward `0.0`, with no trial exceptions;
- real-agent end-to-end evidence: Harbor 0.20.0 ran `lspr-0001` and `lspr-0002`
  from the byte-matched release tree with Codex 0.151.0,
  `openai/gpt-5.6-terra`, and Harbor agent kwarg `reasoning_effort=medium`, which
  invoked Codex with `-c model_reasoning_effort=medium`. Both trials completed
  without exceptions and received reward `1.0`; for each generated
  submission, the independent verifier passed its structure,
  no-shell-escape recompilation, and citation-definition tests;
- the LifeSci configuration currently provides
  Layer-1 binary Harbor verification only, with no Layer-2 paper-quality
  evaluator;
- licensing: 21 source papers are `CC BY 4.0` and one is `CC BY-SA 4.0`.
  Linked code-repository license status is recorded per paper and is not
  treated as a construction blocker when no license is declared. Users must
  follow the per-source terms recorded in verifier-only provenance.

The v0.3.1 LifeSci metadata correction updated the recorded arXiv primary
categories for `paper_26` to `cs.AI`, `paper_30` to `q-bio.QM`, and `paper_38`
to `stat.ME`, then regenerated and re-audited the Harbor tasks. No previous Hub
revision was rewritten or deleted.

### v0.3.0

The 251-task Issue #20 remediation release is at tag `v0.3.0` and commit
`77d2b1abf3560a30c9ea1471c2483608e0ce4ee1`. It regenerated the PaperWrite-Bench
and PaperWritingBench configurations using Harbor converter revision
`e60acc60e1aa69de91e63c4c5b225867407777ba`, pinned PaperWrite-Bench revision
`9779a2a4a9adf7feb43f3e2df7d8e4b1a0b6e858`, and pinned PaperWritingBench
revision `2d2a66677dcefe8595cd3b767da131d5e36d1970`. The release passed fidelity and
deterministic-regeneration audits for all 51 and 200 tasks, respectively.

### v0.2.0

The corrected 251-task release is at tag `v0.2.0` and revision
`5fe375dbd440409f0180e10dee213b1685c8f40d`. It was generated from Harbor merge
commit `738db763c80c2e06f844bff5c5c2269aa0e6cdd6`. The earlier revision
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
