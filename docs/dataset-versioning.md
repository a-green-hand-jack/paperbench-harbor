# Dataset Versioning

The runnable task dataset, trial dataset, and source archive are independently
versioned Hugging Face datasets. Every release must state which immutable
revision of each it uses; a mutable default branch is never sufficient for a
reproducible result.

## Release record

For every new or regenerated task release, record:

- the PaperBench Harbor merge commit and converter revision;
- pinned upstream revisions or source locators;
- task configuration and count;
- immutable Hugging Face task revision and stable tag;
- fidelity and deterministic-regeneration evidence;
- the matching source-archive revision/tag and the task-paper registry path.

The source archive stores construction inputs and task-paper mapping separately
from runnable tasks. Publishing or refreshing it must not change any task byte
or task hash. Conversely, a task release must not claim source-archive coverage
that has not been published at an immutable archive revision.

## Publishing workflow

1. Merge the converter change and record its commit.
2. Regenerate tasks from pinned upstream inputs.
3. Run task contracts, fidelity, deterministic regeneration, and any
   configuration-specific validation.
4. Publish task directories as a new immutable task-dataset revision/tag.
5. Build and verify the source archive from the exact release tree and original
   workflow inputs. The archive contains source trees plus manifests, never
   task runtime files.
6. Publish the archive and its task-paper registry as a separate immutable
   dataset revision/tag.
7. Update the relevant Hugging Face cards with the three revisions and their
   relationship. GitHub documents the maintainer workflow, not a duplicate task
   user guide.

## PaperRecon candidate-release gate

New PaperRecon domains first publish reviewable candidate revisions, not public
dataset tags. Candidate manifests record the construction revision, source
archive revision, LKM discovery snapshot, independently verified provenance,
and the SHA-256 of the independent verifier approval record that selected every
paper. The discovery snapshot is produced by Harbor's official `bohr lkm
search` adapter and is replayable evidence of the leads presented to screening;
screening agents must not call the raw Bohrium endpoint or require
`BOHR_ACCESS_KEY`.

Physics, Chemistry, and Mathematics may receive their first public `v0.1.0`
tags only when each domain has at least 20 independent-verifier-approved tasks that have been
fully rebuilt and pass task contracts, fidelity, deterministic regeneration,
semantic review, and source-archive verification. LKM is a discovery input
only; it cannot substitute for independent source or license verification. The
promoter performs those authoritative arXiv/e-print/GitHub checks separately
and should reuse cached responses with bounded backoff when a provider returns
`403` or `429`, rather than treating rate limiting as a candidate rejection.

## Current task release

[`Jack-Jieke-Wu/Paper-Writing-Exam`](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam)
has 274 tasks at tag `v0.4.1`, whose immutable task revision is
`367bbf67ea05d0ec3d580e062aadf5636b45fc65`.

The release contains 51 `paperwrite-bench-short` tasks, 200
`paperwritingbench-sparse-plotoff` tasks, 22 repaired
`lifesci-paperrecon-short` tasks, and one `hello-world` smoke task. The LifeSci
repair was generated with converter revision
`ffcdc76f74a1711d2157b9bf6aa5c10b49183800`: it verified 144 source tables and
144 writer-visible table fragments across all 22 tasks.

That converter revision is immutable release provenance, not a claim that a
released dataset should track a moving branch. The complete LifeSci repair
series is already present on the current `main` as patch-equivalent changes;
future maintenance starts from `main`, while reproduction of `v0.4.1` continues
to cite the fixed converter revision above.

Task selection and execution instructions are normative in the
[Paper-Writing-Exam dataset card](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam), not here.

## Current source archive

[`Paper-Writing-Exam-Source-Archive`](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam-Source-Archive)
maps this task release at its immutable `v0.1.0` tag, target commit
`328f2ca7ee8b68cbf2b5af60ad9ff1b85f47cce0`. Its registry has 274 task records,
including 273 archived upstream source trees and the explicitly non-applicable
first-party `hello-world` record. Its per-file manifest covers 14,388 source
files.

## Historical releases

- `v0.4.0` added the first-party `hello-world/hello-world-0001` integration
  task at `fac54a81702f62b38c765de9e85615b4eb31a470`.
- `v0.3.1` is a historical LifeSci release with an instruction/material mismatch
  fixed by `v0.4.1`; reproduce old results only from its own immutable revision.
- `v0.3.0` is the 251-task Issue #20 remediation release at
  `77d2b1abf3560a30c9ea1471c2483608e0ce4ee1`.

No historical release is rewritten or deleted. Dataset-card-only commits are
not task releases; reports must identify the immutable task revision actually
used.
