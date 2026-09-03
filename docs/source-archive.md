# Source Archive

The source archive is a separate Hugging Face dataset for immutable task-paper
provenance and retained construction inputs. It is not a Harbor task
configuration: converters must never copy archive files into
`environment/materials/`, `solution/`, `tests/`, or any other runnable task
path.

## Current archive

[`Paper-Writing-Exam-Source-Archive`](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam-Source-Archive)
`v0.1.0` is the archive paired with the 274-task `Paper-Writing-Exam`
`v0.4.1` release at task revision
`367bbf67ea05d0ec3d580e062aadf5636b45fc65`. The archive's immutable target
commit is `328f2ca7ee8b68cbf2b5af60ad9ff1b85f47cce0`.

It contains:

- one task-paper registry record for every task/configuration pair;
- 273 archived upstream source trees, covering all 51 PaperWrite-Bench, 200
  PaperWritingBench, and 22 LifeSci-PaperRecon tasks;
- a SHA-256 manifest for 14,388 archived source files; and
- one `hello-world` record marked `not_applicable`, because the first-party
  smoke task has no external paper or source archive input.

The registry connects a task's immutable release identity and checksum to its
upstream sample or paper, conversion revision, source location, and licensing
metadata. It is for provenance review and source auditing, not for supplying
extra context to an evaluated agent.

## Archive boundaries

The archive never contains runnable task directories, oracle solutions,
verifier fixtures, or trial artifacts. Refreshing the archive must not modify a
task file or task checksum. Conversely, a task release cannot claim archive
coverage until the matching archive revision and registry have been verified
and published.

Each archived input retains the upstream license and redistribution terms. A
source that may be located but not redistributed remains a locator with its
identity and rationale; the archive does not create new distribution rights.

## Maintainer implementation

The implementation is maintained on `main` in
`src/paperbench_harbor/provenance/archive.py` and exposed through
`scripts/build_source_archive.py`. It builds a source-only archive from a fixed
task-release tree and the retained PaperWrite-Bench, PaperWritingBench, and
LifeSci source roots; it then writes the registry and per-file manifest.

Before publication, run the builder against explicit immutable task and
converter revisions, then validate the staged archive with `--verify-only`.
The verification checks registry structure, archive-tree hashes, and the
absence of runnable-task content.

## Future releases

For every new task release:

1. merge the converter changes into `main` and record the exact build revision;
2. regenerate and validate the task release from pinned upstream inputs;
3. publish and tag the immutable task dataset revision;
4. build and verify the matching source archive from that exact task tree; and
5. publish and tag the archive, then cross-link both immutable revisions in the
   dataset cards.

The build revision is historical provenance for that release. A later `main`
may contain patch-equivalent fixes, but it must not replace the recorded
revision when reproducing the older immutable dataset.
