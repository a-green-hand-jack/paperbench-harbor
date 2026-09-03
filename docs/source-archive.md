# Source Archive Release Gate

The source archive is a separate Hugging Face dataset for immutable provenance
records and legally redistributable construction inputs. It is not a task
configuration and converters must never read it. In particular, archive files
must not be copied to `environment/materials/`, `solution/`, `tests/`, or any
other runnable task path.

## Plan Contract

`scripts/build_source_archive.py` accepts a strict schema-v1 JSON plan. It
requires a pinned runnable dataset revision and converter/workflow commits,
then records a separate paper-level identity for every task. A paper record
contains its canonical title, arXiv version and URLs, verified license, code
repository and fixed code revision (or an explicit no-code explanation), plus
the fetch date and source-archive manifest release identifier.

Each construction input records its kind, immutable source URL, fetch time,
byte count, SHA-256, and one of two treatments:

- `archived`: copy independently rehashed bytes to the archive at a safe
  archive-relative path.
- `locator-only`: retain its immutable locator, byte count, hash, and a
  concrete redistribution-exclusion explanation without copying it.

Every arXiv paper must account for its e-print source, PDF, and extracted
source-tree manifest. A venue-only paper must explicitly mark its arXiv fields
as not applicable and explain why. A paper with a code repository must also
account for its code snapshot. Missing mappings, movable revisions, bad hashes,
or a silent redistribution exclusion fail before an archive is created.

## Release Workflow

The release workflow is executed by
`scripts/run_release_workflow.py --spec ... --audit-output ...
--archive-output ... --evidence-output ...`. Its strict schema-v1 JSON spec
pins the task converter revision, the workflow revision, the semantic-review
model, and every audit's source, task tree, upstream revision, protocol, and
per-task worker count.

It starts all declared configuration audits concurrently (bounded by the spec's
`max_concurrent_audits`) and always passes `--semantic-review` with the named
reviewer model. It verifies that every produced summary represents the exact
task tree, has a pinned workflow revision, passes the two independent
determinism rebuilds, and contains one successful semantic review per task.

Only after those full audits pass does the workflow build the separate source
archive, validate the registry and copied hashes, run the source-archive gate
for the configurations covered by the archive plan, and write one
machine-readable release-workflow evidence file. A failure leaves no successful
gate evidence, so it cannot be used to create a release tag.

The intended sequence is:

1. Materialize candidate task trees and upload them only to an isolated
   candidate Hugging Face revision. Its immutable commit is recorded in the
   source-archive plan; it is not a public release tag.
2. Prepare the human-approved archive plan and source inputs outside every
   runnable task directory.
3. Run the release workflow. It performs the complete deterministic and
   semantic audit of every declared configuration in parallel, then builds and
   verifies the archive and its provenance gate.
4. Upload the source archive, create immutable tags for the verified runnable
   candidate revision and its archive revision, then publish the workflow
   evidence and links in both dataset cards.

`scripts/build_source_archive.py` and
`scripts/verify_release_provenance.py` remain useful independent verification
commands, but a release workflow must use the orchestrator above rather than
hand-compose a partial audit. This makes source-archive production a required
part of each future release workflow, not an after-the-fact document.

The archive builder hashes the entire local task tree before and after it
writes. An archive refresh that changes a task byte is a failure, rather than a
new benchmark release.

## Current Scope

The source archive being added in the PR #42 release cycle covers the 22-task
LifeSci-PaperRecon configuration. The repository owner explicitly decided not
to backfill a source archive for the already published 51 PaperWrite-Bench or
200 PaperWritingBench tasks. Those configurations remain subject to their
conversion, regression, isolation, and semantic-audit gates, but are not task
registrations in this LifeSci archive plan or release gate. A later decision to
archive either legacy configuration must use a separate complete plan; it must
not silently reuse or weaken the LifeSci registry.
