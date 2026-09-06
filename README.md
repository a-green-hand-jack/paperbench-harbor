# PaperSmith

PaperSmith turns a scientific-paper selection request or a specified paper into
independently reviewed **Harbor writing tasks**. No domain selection, knowledge
pack, checkout agent files, or manual approval-file exchange is required.

This repository is also the conversion and distribution center for
PaperWritingBench, PaperWrite-Bench and the existing PaperRecon datasets. Their
`paperbench-harbor` conversion interface and submission contract remain available.

## Install

Requires Python 3.12+ with `venv`/pip. From a trusted current clone:

```sh
sh install.sh
export PATH="$HOME/.local/bin:$PATH"
papersmith doctor --json
```

The installer builds and installs a **wheel**, not an editable link. The default
environment is `~/.local/share/papersmith/venv`; executables are linked from
`~/.local/bin`. Installation works outside the checkout. Re-run to upgrade.
`PAPERSMITH_PREFIX`, `PAPERSMITH_BIN_DIR`, `PAPERSMITH_PYTHON` and
`PAPERSMITH_SOURCE` override these locations/source selection.

For remote installation, replace `COMMIT` with a trusted full 40-character commit
that contains this installer and product. Both installer and source are pinned:

```sh
curl -fsSL https://raw.githubusercontent.com/a-green-hand-jack/paperbench-harbor/COMMIT/install.sh \
  | PAPERSMITH_REF=COMMIT sh
```

Uncommitted local implementation is not available at a remote revision. The
installer intentionally refuses an unpinned remote source. Install OpenCode
separately and configure your provider using its documented authentication flow.
`pdftotext` (Poppler) is required for PDF source extraction. `doctor` checks CLI
dependencies and model discovery without reading credential files or making a
paid request; authentication remains unverified until a real call succeeds.

## Create Tasks

```sh
papersmith create 'Discover suitable scientific papers on any topic' \
  --count 5 --output /path/outside-checkout/my-run --headless --json
papersmith status /path/outside-checkout/my-run --json
papersmith resume /path/outside-checkout/my-run --headless --json
papersmith validate /path/outside-checkout/my-run --json
```

The count is **delivered admitted tasks**, not proposed candidates. Rejected
papers are recorded and replaced automatically. A DOI, paper URL or detailed
selection request can replace the example. Requests may name accessible source
URLs; source bytes and license evidence are retrieved and retained privately.
Use `--source /path/to/scoped-research` to import local scientific files privately.
Provide provenance/license context in the request; local files do not waive licensing.
There is no fixed scientific-topic list and no scientific-domain blocker.

Execution defaults to `openai/gpt-5.6-terra`. All three gates default to
`openai/gpt-5.6-sol`; override with `--model provider/model` and
`--review-model provider/model`. Private account aliases may be supplied by the
caller but are not public defaults. Provider integration is through OpenCode.

```text
proposal -> gate1 -> materials -> gate2 -> convert -> gate3 -> deliver
```

- Gate 1 checks actual sources, licenses, availability and suitability for a
  writing task. Scientifically unnecessary code may be marked not applicable
  with justification; this never waives license requirements.
- Gate 2 compares materials against source evidence, including methods, results,
  figures, tables, references and context. Sufficiency means enough to **write**,
  not an obligation to re-run experiments or reproduce the whole research project.
- Gate 3 reviews actual Harbor files, fidelity, conversion determinism, verifier,
  paths, submission contract and answer isolation. It does not require a writer
  trial or reward of one.

Reviews use fresh sessions and a different role, with no file-writing or shell
tools. The same configured review model can perform every gate. This is process
independence, not a claim of independent scientific authority. Model responses
must pass schemas and artifact checks; a builder cannot author its own approval.
Every review dimension cites current input files by path, SHA256, exact excerpt
and validated line/page location. Gate 1 must cite each source's retrieved
identity/license binding, not merely a license name. Publisher/repository metadata,
redirect destinations and relevant response headers are retained; version strings
remain claims while actual downloaded snapshots are identified by SHA256.
Web-enabled discovery cannot read workspace files. Local-source proposal building,
materials and reviews are offline at the tool layer and use explicit read scopes.
Only the user-provided public selection request is sent to web-enabled discovery,
not private source content or review feedback. Canonical metadata-derived paper
identities and source hashes, rather than model-selected labels, control deduplication.

## Outputs And Recovery

`run.json` holds checkpoints; `events.jsonl` and stderr expose controller-selected
structured progress without raw provider diagnostics. stdout contains one JSON
result with `--json`. Each phase has a unique attempt directory, inputs/outputs
hashes, timestamps, requests and real-session receipts. Research content in the
workspace is private; do not publish it indiscriminately.

`status` reports the four phases and three gates, paths and stale/missing evidence.
`validate` makes no model calls and exits nonzero unless the requested number of
deliveries still matches the current evidence. `resume` holds a workspace lock,
reuses passed unchanged nodes, and restarts interrupted or failed nodes. Changes
to inputs/implementation invalidate dependent evidence. Previous attempts remain
on disk. Ctrl-C or `docker stop` interrupts; no phase has a default wall-clock
limit. Invalid model artifacts and repair verdicts trigger automatic feedback;
infrastructure/authentication failures stop with a resumable checkpoint.

Each delivered path is a real Harbor task containing `instruction.md`,
`task.toml`, `environment/`, `tests/`, and a manifest. Only allowlisted public
materials enter the writer image. Original sources and reference material are
under the separate verifier's `tests/private/`. The existing structural verifier
checks LaTeX compilation and citations, not scientific quality. No fake task,
pre-existing oracle, model self-reported readiness or synthetic evidence is used.
`task_ready`, downstream writing/scoring and public publication are separate.
Nothing uploads automatically.

Sources currently support public HTTPS PDF, HTML, text, CSV/JSON and scoped binary
assets. Opaque archives are not automatically unpacked; select direct source
files. Controller retrieval rejects private-network URLs and oversized sources.
Exact excerpt checks plus semantic reviews are complementary, not a proof of
every scientific claim. Run untrusted research in the supplied Docker workflow.

## Benchmark Distribution

```sh
paperbench-harbor --help
paperbench-distribute --help
paperbench-distribute audit-fidelity --help
paperbench-distribute build-source-archive --help
paperbench-distribute export-trial --help
```

The old root scripts are removed. Necessary provenance, audit, reconstruction,
release and sanitized-trial operations are packaged under
`paperbench_harbor.distribution`, behind the explicit `paperbench-distribute`
interface. Optional dataset/release integrations require the corresponding
`paperbench-harbor[datasets,harbor,trials]` extras in the installed environment.
Existing releases retain their own stricter publication policies; these are not
hidden requirements of generic local creation.

## Development

See [DEV.md](DEV.md) for installed-product Docker verification, narrow provider
mounts, monitoring and recovery. There is no root scripts directory, checkout
agent entry point or replacement unit-test suite. The generated Harbor verifier
is benchmark functionality, not a repository pytest suite.

**Acceptance status:** the installed-product Docker run produced five distinct
Harbor tasks. All 15 independent review gates accepted; final offline
`papersmith validate` returned `task_ready: true`, `task_ready_count: 5`, and no
integrity failures. Actual interruption/resume preserved unchanged passed stages.
See the live evidence record in [DEV.md](DEV.md). This is task-production
acceptance, not a downstream writer trial, image-build certification, or scientific
quality certification. Older stopped runs and volumes remain preserved.
