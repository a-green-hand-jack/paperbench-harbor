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

Every paper must account for its e-print source, PDF, and extracted source-tree
manifest. A paper with a code repository must also account for its code
snapshot. Missing mappings, movable revisions, bad hashes, or a silent
redistribution exclusion fail before an archive is created.

## Release Procedure

1. Materialize the intended task release and prepare the approved source
   archive plan outside that task directory.
2. Run `scripts/build_source_archive.py --plan ... --dataset-root ... --output
   ...`; the output must be a separate empty directory.
3. Run a deterministic, semantic `scripts/audit_fidelity.py` report for every
   task configuration.
4. Run `scripts/verify_release_provenance.py` with the plan, task release,
   archive, and one `--audit-summary CONFIG=...` for each configuration. It
   fails unless all tasks are registered, copied input hashes still match, and
   every configuration has a fully passing deterministic semantic audit tied to
   the planned converter revision.
5. Upload the two immutable products, tag both releases, and put the final
   runnable-dataset revision, source-archive revision, registry link, and gate
   evidence in their Hugging Face dataset cards.

The archive builder hashes the entire local task tree before and after it
writes. An archive refresh that changes a task byte is a failure, rather than a
new benchmark release.
