# paperbench-harbor

`paperbench-harbor` builds, verifies, releases, and maintains Harbor task
datasets for paper-writing agents. It is the maintainer repository, not the
canonical end-user manual for a released benchmark.

## Published datasets

| Dataset | Role | Canonical documentation |
|---|---|---|
| [Paper-Writing-Exam](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam) | Runnable Harbor tasks | Task selection, material boundary, running, and version pinning |
| [Paper-Writing-Exam-Trials](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam-Trials) | Sanitized agent trajectories and results | Trajectory schema, retrieval, and analysis limits |
| [Paper-Writing-Exam-Source-Archive](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam-Source-Archive) | Immutable task-paper registry and construction inputs | Provenance lookup and source-archive licensing |

The task dataset is the only dataset a Harbor evaluation runs. Trial data is
evidence about an evaluation; it is not a replacement task dataset or training
corpus. The source archive is for provenance and independent review only; no
Harbor task may read it at runtime.

## Maintainer documentation

- [Dataset versioning](docs/dataset-versioning.md): release records, immutable
  revisions, and source-archive publication.
- [Documentation inventory](docs/documentation-inventory.md): ownership and
  current status of every repository document.
- [Fidelity audit](docs/fidelity-audit.md): source-to-task validation rules.
- [LifeSci construction](docs/lifesci-paperrecon-construction.md): PaperSmith
  build and validation path.
- [Trial exporter maintenance](docs/trial-dataset.md): sanitize and publish
  trial records without exposing private task material.
- [Architecture](docs/papersmith-architecture.md): the construction core and
  domain-plugin contracts.

For task execution, configuration-specific materials, and trajectory analysis,
use the dataset cards linked above. GitHub keeps only the construction and
maintenance contracts so a release does not create two competing user manuals.

## OpenCode workflows

The repository has two human-gated OpenCode entry points. They orchestrate
screening, verification, and evidence collection but cannot directly edit the
repository or bypass a required audit. The converting and publishing programs
remain deterministic, separately auditable maintainer commands.

### Onboard an existing benchmark

`benchmark-onboard` evaluates a public, fixed benchmark for Harbor packaging.
It stops at a SHA-bound human approval; only then may a release operator
materialize and audit the approved layout.

```mermaid
flowchart TD
    request([Candidate benchmark request]) --> onboard[OpenCode: benchmark-onboard]
    onboard --> scope[Screen the paper-writing task boundary]
    scope --> eligible{In scope?}
    eligible -- no --> rejected([Report rejection and stop])
    eligible -- yes --> candidate[Write a candidate claim in isolated scratch]
    candidate --> verify[Independently verify revision, license, manifest hash, and count]
    verify --> verified{Evidence valid?}
    verified -- no --> rejected
    verified -- yes --> layout[Propose a generic Harbor layout in scratch]
    layout --> approval{Human SHA-bound approval?}
    approval -- not yet --> hold([Stop at the approval gate])
    approval -- yes --> materialize[Release operator runs materialize_onboarded_benchmark.py]
    materialize --> audits[Structural and semantic fidelity audits plus two deterministic rebuilds]
    audits --> passed{All audits pass?}
    passed -- no --> failed([Retain evidence; do not publish])
    passed -- yes --> archive[Build and verify matching source-archive provenance]
    archive --> publish([Manually publish immutable dataset and archive revisions])
```

### Build tasks from papers

PaperSmith has four human-gated paper-to-task agents: `papersmith-lifesci`,
`papersmith-physics`, `papersmith-chemistry`, and `papersmith-mathematics`.
They share a public-materials-to-paper-reconstruction protocol while retaining
domain-specific screening policies and writing instructions. LKM is the first
candidate-discovery provider for PaperSmith: it improves recall and ranking,
but never establishes source, license, code, or reconstructability facts.

```mermaid
flowchart TD
    request([Natural-language paper request]) --> papersmith[OpenCode: one of four PaperSmith domain agents]
    papersmith --> kind{Collect new papers or rebuild a published corpus?}

    kind -- collect --> parse[Parse domain, target count, guidance, and explicit paper IDs]
    parse --> lkm[LKM discovery and ranked candidate snapshot]
    lkm --> fallback{LKM available?}
    fallback -- no --> searchfallback[Record failure; query arXiv and Semantic Scholar]
    fallback -- yes --> screen[Screen LKM candidates in isolated scratch]
    searchfallback --> screen
    screen --> liveverify[Independently verify paper and code provenance, licenses, and eligibility]
    liveverify --> valid{Eligible and verifiable?}
    valid -- no --> reportrejected([Report rejected or unverifiable candidates])
    valid -- yes --> humanapproval{Human SHA-bound approval?}
    humanapproval -- not yet --> hold([Stop at the approval gate])
    humanapproval -- yes --> promote[Promote approved paper IDs and immutable approval SHA]
    promote --> construct[Construct source corpus with one isolated OpenCode build and review session per paper]
    construct --> convert[Convert the corpus to Harbor tasks]
    convert --> fidelity[Fidelity, determinism, and semantic audits]
    fidelity --> collectionpassed{All audits pass?}
    collectionpassed -- no --> failed([Report evidence; do not publish])
    collectionpassed -- yes --> collectionreport([Stage auditable candidate release evidence])

    kind -- rebuild --> manifest[Download the current immutable published manifest]
    manifest --> supervisor[Run the release-candidate supervisor]
    supervisor --> rebuild[Reconstruct and review every published paper]
    rebuild --> coverage[Audit complete reachable TeX table coverage]
    coverage --> coveragepassed{Coverage passes?}
    coveragepassed -- no --> failed
    coveragepassed -- yes --> reconvert[Convert the rebuilt corpus to Harbor tasks]
    reconvert --> releaseaudit[Run the fidelity audit]
    releaseaudit --> releasepassed{run-summary.json is passed?}
    releasepassed -- no --> failed
    releasepassed -- yes --> releasereport([Produce release-candidate evidence])
```

These workflows establish task-construction correctness only. They do not score
or make claims about the performance of a paper-writing agent.

For Physics, Chemistry, and Mathematics, a domain is not ready for public
release until it has at least 20 human-approved, fully rebuilt tasks that pass
the same conversion, fidelity, determinism, and semantic audits. Candidate
revisions are review artifacts identified by immutable SHAs, not public version
tags.

## Benchmark families

The current published task release has four configurations:

- `paperwrite-bench-short`: Harbor adaptation of PaperWrite-Bench.
- `paperwritingbench-sparse-plotoff`: Harbor adaptation of PaperWritingBench.
- `lifesci-paperrecon-short`: PaperSmith-built LifeSci paper reconstruction
  tasks.
- `hello-world`: a first-party integration smoke task, not a source-paper
  benchmark.

The next candidate-release generation adds `physics-paperrecon-short`,
`chemistry-paperrecon-short`, and `mathematics-paperrecon-short`. They remain
unpublished until their 20-task per-domain acceptance gates have passed.

The precise task counts, release revision, compatibility notes, and task IDs
are maintained in the [Paper-Writing-Exam dataset card](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam).

## Build and verify

Install the development dependencies and run the repository checks:

```bash
uv sync --all-extras
uv run --all-extras pytest -q
uv run --all-extras ruff check .
```

Build a source-only provenance archive from a fixed task release and retained
upstream inputs:

```bash
uv run --all-extras python scripts/build_source_archive.py \
  --release-root <immutable-task-release-tree> \
  --output-dir <source-archive-staging-dir> \
  --dataset-repo Jack-Jieke-Wu/Paper-Writing-Exam \
  --dataset-revision <immutable-task-revision> \
  --converter-revision <paperbench-harbor-revision> \
  --paperwrite-source <paperwrite-bench-source> \
  --paperwritingbench-source <paperwritingbench-source> \
  --lifesci-source <lifesci-source-corpus> \
  --physics-source <physics-source-corpus> \
  --chemistry-source <chemistry-source-corpus> \
  --mathematics-source <mathematics-source-corpus> \
  --config hello-world \
  --config paperwrite-bench-short \
  --config paperwritingbench-sparse-plotoff \
  --config lifesci-paperrecon-short \
  --config physics-paperrecon-short \
  --config chemistry-paperrecon-short \
  --config mathematics-paperrecon-short
```

The command writes a registry and original-source archive but never copies a
Harbor task, solution, verifier, or trial into that archive. Re-run it with
`--verify-only --output-dir <source-archive-staging-dir>` before publishing.

## License and security boundaries

Upstream benchmark data, paper sources, code, and conference templates retain
their original licenses. Source archives record the relevant terms and fixed
locations; they do not grant a new redistribution license.

Benchmark task data, verifier-private material, credentials, and unredacted
agent output must never be included in training corpora or published by a
maintenance workflow unless its dedicated policy explicitly permits it.
