# PaperSmith Architecture

The installed Python package owns the CLI, schema, OpenCode runtime and controller
under `paperbench_harbor.papersmith`. Root `install.sh` installs a wheel outside
the checkout. `docker/e2e.sh` exercises the same installer and public commands.

`schema.py` defines generic proposals, source/license provenance, supported public
materials, writing requirements, coverage and independent review verdicts.
`runtime.py` uses fresh OpenCode sessions with read/web tools, no shell or writes,
and controller-selected observable event metadata. `product.py` retrieves source
bytes, checks excerpts, orchestrates repairs/checkpoints and renders Harbor tasks
with the existing shared templates and verifier. `cli.py` exposes create, status,
resume, validate and doctor with headless/JSON operation.

All model artifacts and review evidence are private, versioned attempt outputs.
Only declared public materials enter the writer image. Readiness requires the
current delivered task, three accepted independent reviews, unchanged source and
implementation fingerprints, and the requested admitted count. Structural
verification, scientific judgment, downstream writing and publication are distinct.

Existing benchmark adapters remain under `adapters/`; necessary explicit release,
audit and reconstruction operations are packaged under `distribution/` and
available through `paperbench-distribute`. Legacy domain modules remain for
persisted benchmark contracts, but are not prerequisites of generic creation.

See [DEV.md](../DEV.md) for runtime boundaries and the pending five-task live
acceptance, including interrupted recovery. No new unit-test suite is introduced.
