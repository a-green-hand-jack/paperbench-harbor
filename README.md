# PaperSmith

PaperSmith turns a scientific-paper selection request or a specified paper into
independently reviewed **Harbor writing tasks**. No domain selection, knowledge
pack, checkout agent files, or manual approval-file exchange is required.

The default task is a **full scientific manuscript**, not a concise summary.
`--task-kind summary` deliberately selects a summary; models and reviewers cannot
silently narrow the locked objective. `--identifiers identified` is the default;
`--identifiers anonymized` withholds focal identifiers where lawful, never required
asset credit or honest citation metadata. Anonymization is not a license waiver.

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
`pdftotext` and `pdfinfo` (Poppler), `pdflatex` and `bibtex` are required for original
PDF validation and synthetic oracle compilation. `doctor` checks CLI
dependencies and model discovery without reading credential files or making a
paid request; authentication remains unverified until a real call succeeds.

## Create Tasks

```sh
papersmith create 'Discover suitable scientific papers on any topic' \
  --count 1 --output /path/outside-checkout/my-run --headless --json
papersmith status /path/outside-checkout/my-run --json
# Review the first accepted task, then explicitly expand the same run:
papersmith resume /path/outside-checkout/my-run --count 5 --headless --json
papersmith validate /path/outside-checkout/my-run --json
```

The count is **delivered admitted tasks**, not proposed candidates. In default
`--selection discovery`, rejected papers are recorded and replaced automatically.
For exact papers, use `--selection fixed --paper DOI_OR_ARXIV` (repeat `--paper`);
retrieved canonical identities must match that allowlist. Fixed mode blocks on
rejection rather than substituting another paper. Count cannot exceed the allowlist;
you can admit the first one before `resume --count N`. A DOI in free-form discovery
text is not a fixed-identity guarantee. `--describe` / `--describe-request` shows
the resolved contract, allowlist, count and replacement policy without calls or writes.
Requests may name accessible source
URLs; source bytes and license evidence are retrieved and retained privately.
Use `--source /path/to/scoped-research` to import local scientific files privately.
Provide provenance/license context in the request; local files do not waive licensing.
`--source-cache /path/to/prior-run` copies hash-verified acquisition inputs from an
existing workspace into a **new** run. It copies no approvals and still runs a new
proposal, actual PDF acquisition/validation, and all three reviews. Keep the prior
workspace at its recorded path; relocated checkpoint snapshots are not accepted.
There is no fixed scientific-topic list and no scientific-domain blocker.

Execution defaults to `openai/gpt-5.6-terra`. All three gates default to
`openai/gpt-5.6-sol`; override with `--model provider/model` and
`--review-model provider/model`. Private account aliases may be supplied by the
caller but are not public defaults. Provider integration is through OpenCode.

```text
proposal -> gate1 -> materials -> gate2 -> convert -> gate3 -> deliver
```

- Gate 1 checks actual sources, licenses, availability and suitability for a
  writing task, including the mandatory original PDF and evidenced original-TeX
  availability (or explicit unavailability). Scientifically unnecessary code may be marked not applicable
  with justification; this never waives license requirements.
- Gate 2 compares materials against the actual original PDF/text, including methods, results,
  figures, tables, references and context. Sufficiency means enough to **write**,
  not an obligation to re-run experiments or reproduce the whole research project.
- Gate 3 reviews actual Harbor files, fidelity, conversion determinism, verifier,
  exact private ground truth, paths, submission contract, answer isolation and the
  synthetic oracle's scientific adequacy against the locked objective and every writing
  requirement. **Actual Harbor oracle reward 1 and nop reward 0 are mandatory**, before
  the independent Sol scientific assessment. A separate downstream writer evaluation is not required.

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
Conversion internally uses a fresh execution-model session to author a synthetic
reference manuscript from **only public instruction/materials**. Controller-owned
rendering creates portable TeX, bibliography and local assets; compilation precedes
gate 3. This is not a fourth gate or a downstream writer evaluation.
Only the user-provided public selection request is sent to web-enabled discovery,
not private source content or review feedback. Canonical metadata-derived paper
identities and source hashes, rather than model-selected labels, control deduplication.

## Outputs And Recovery

`run.json` holds checkpoints; `events.jsonl` and stderr expose controller-selected
structured progress without raw provider diagnostics. stdout contains one JSON
result with `--json`. Each phase has a unique attempt directory, inputs/outputs
hashes, timestamps, requests and real-session receipts. Research content in the
workspace is private; do not publish it indiscriminately.

`status` quickly reads the checkpoint snapshot, without full artifact hashing; it
does not certify freshness or acceptance. `validate` is authoritative.
`validate` makes no model calls and exits nonzero unless the requested number of
deliveries still matches the current evidence. `resume` holds a workspace lock,
reuses passed unchanged nodes, and restarts interrupted or failed nodes. Changes
to inputs/implementation invalidate dependent evidence. Previous attempts remain
on disk. Ctrl-C or `docker stop` interrupts; no phase has a default wall-clock
limit. Invalid model artifacts and repair verdicts trigger automatic feedback;
infrastructure/authentication failures stop with a resumable checkpoint.

Each delivered path is a real Harbor task containing `instruction.md`,
`task.toml`, `environment/`, `tests/`, `solution/`, and a manifest. Only allowlisted public
materials enter the writer image. `tests/private/ground_truth/paper.pdf` is mandatory:
actual publisher/repository bytes, never an LLM reconstruction. Its manifest binds
identity, source/version, license evidence, acquisition and file hashes, PDF parsing,
readability, page count and title/identifier checks. Publisher `citation_pdf_url`
is fetched automatically even when the proposal selects HTML or supplies a PDF.
Proposal/imported PDF bytes cannot bypass that authoritative relationship:
the controller acquires the observed publisher PDF (or the known arXiv abs-to-PDF
relationship). Cache reuse requires that URL, metadata hash and PDF hash binding;
title/DOI checks are complementary, not proof of authority. Unrelated PDF links
and HTML error bodies are not accepted as a paper. An actual `paper.html` snapshot
is retained when available. Original TeX/dependencies are retained when retrieved;
otherwise the manifest explicitly records unavailability in the searched sources
with publisher-link/repository retrieval evidence, not a claim that no source exists anywhere.
Discovery includes semantically marked source/archive/download links without URL
extensions and records content type, disposition filename and actual body inspection.
`not_discovered` means no candidate in the recorded search;
`unavailable_in_inspected_candidates` is limited to those candidates. There is no crawl.
Model-generated `reference_notes.md` is explicitly non-authoritative.
Public materials include a genuine `template/main.tex` and BibTeX bibliography,
not Markdown renamed as a template. Starter compilation is recorded separately and
does not satisfy the completed-submission verifier. Relevant tables have controller-
generated CSV/JSON with exact cells, source anchors, captions, units, notes, missing
values and precision policies, plus original images when available and lawful.
Item-level coverage records include/substitute/exclude/unavailable dispositions with
reasons for relevant figures, tables, supplements, methods, claims, hypotheses,
authors' interpretation and limitations. This does not require every photograph or
full experimental reproduction. Each redistributed asset has its own rights and credit.
`solution/solve.sh` installs and compiles the bundled **synthetic oracle**, not the
original PDF, and never edits the verifier or rewards. Only Harbor's oracle agent
receives that solution bundle. The structural verifier checks LaTeX compilation,
sections and citations, not scientific quality. No model self-reported readiness
or synthetic artifact is used as original ground truth.
`task_ready`, downstream writing/scoring and public publication are separate.
Nothing uploads automatically.

Successful oracle model responses survive mechanical compile failures. Resume
reuses a hash-bound response only for unchanged public inputs/model/schema after
compile failure or interruption; scientific repairs may require a new response.
`papersmith identity --json` exposes stable installed content identity separately
from the acceptance protocol. `papersmith acceptance-status --state PATH --json`
reads worker lifecycle snapshots; observed/copying/executing are not acceptance.
Historical workspaces without the locked contract remain untouched and cannot be
promoted into new-contract acceptance. Create a new run, optionally reusing verified
source acquisitions, rather than editing old receipts or forcing migration.

Sources support public HTTPS PDF, HTML, text, CSV/JSON and scoped binary
assets. Original-source ZIP/tar/gzip bundles are retained and boundedly unpacked
without executing their contents; original identity/dependency completeness still
requires gate 1 review. Controller retrieval rejects private-network URLs and oversized sources.
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

**Current scope status:** implementation only; the new original-ground-truth and
synthetic-oracle contract has not yet completed five-task generation or the ten
real Harbor oracle/nop trials. Gate 3 now automatically requires real oracle=1 and
nop=0 execution before its semantic review and delivery. `docker/e2e.sh run|resume`
supervises the installed trusted host worker using Harbor 0.22.0, with read-only
receipts and no Docker socket in the model container. No manual export is needed.
Start with `create --count 1`, then `resume --count 5` to explicitly expand the same
target while reusing unchanged successes. See [DEV.md](DEV.md) for exact commands.

**Historical acceptance (before this contract):** the installed-product Docker run produced five distinct
Harbor tasks. All 15 independent review gates accepted; final offline
`papersmith validate` returned `task_ready: true`, `task_ready_count: 5`, and no
integrity failures. Actual interruption/resume preserved unchanged passed stages.
See the live evidence record in [DEV.md](DEV.md). This is task-production
acceptance, not a downstream writer trial, image-build certification, or scientific
quality certification. Those old HTML-only tasks are not current ground-truth/oracle
acceptance. Old checkpoints are invalidated by implementation/input hashes, never
silently upgraded; use a new run/export suffix. Older runs and volumes remain preserved.
