# Documentation Inventory

This inventory is the documentation control record for issue #41. GitHub owns
construction, validation, publishing, and maintenance. The three Hugging Face
dataset cards own detailed task and trajectory use. Version-specific statements
must cite an immutable release, tag, or current code revision.

| Document | Audience | Canonical home | Status | Maintenance rule |
|---|---|---|---|---|
| `README.md` | Maintainers | GitHub | Updated | Link to dataset cards; do not duplicate task tutorials |
| `CONTRIBUTING.md` | Contributors | GitHub | Keep | Repository contribution process |
| `docs/dataset-versioning.md` | Release maintainers | GitHub | Updated | Record task and source-archive revisions |
| `docs/documentation-inventory.md` | Maintainers | GitHub | New | Update when a document is added or migrated |
| `docs/fidelity-audit.md` | Maintainers | GitHub | Keep | Replace historical numbers only with generated evidence |
| `docs/hello-world-smoke.md` | Maintainers | GitHub | Keep | First-party integration fixture, not end-user benchmark guide |
| `docs/huggingface-paper-writing-exam.md` | Maintainers | GitHub | Updated | Card ownership and publication check only |
| `docs/implementation-plan.md` | Maintainers | GitHub | Historical | Mark historical decisions; do not describe current release behavior without verification |
| `docs/lifesci-paperrecon-construction.md` | Maintainers | GitHub | Keep | Construction and validation workflow |
| `docs/lifesci-paperrecon.md` | Maintainers | GitHub | Historical/current split | Treat phase reports as dated evidence, not current task instructions |
| `docs/naming-convention.md` | Maintainers | GitHub | Keep | Stable terminology |
| `docs/non-ml-benchmark-survey.md` | Maintainers | GitHub | Historical research | Issue #2 scope only; no task usage guide |
| `docs/paper-orchestra-sidecar.md` | Maintainers | GitHub | Keep | Sidecar operation |
| `docs/papersmith-architecture.md` | Maintainers | GitHub | Keep | Construction architecture |
| `docs/issue-70-todo.md` | Maintainers | GitHub | In progress | Full six-phase implementation and verification checklist |
| `docs/papersmith-workflow.md` | Maintainers | GitHub | New | Structured request, evidence, resume, trials and explicit release operations |
| `docs/release-regression-deltas.md` | Release maintainers | GitHub | Keep | Document expected task-byte changes by release |
| `docs/scholarly-search-sidecar.md` | Maintainers | GitHub | Keep | Sidecar operation |
| `docs/source-archive.md` | Release maintainers | GitHub | Keep | Source-archive release gate and evidence requirements |
| `docs/submission-contract.md` | Maintainers | GitHub | Keep | Submission/verifier contract |
| `docs/trial-dataset.md` | Trial maintainers | GitHub | Updated | Export and sanitization only; link users to HF card |
| `packaging/huggingface/paper-writing-exam/README.md` | Task users | Hugging Face | Updated | Dataset relations, task selection, use, material boundary |
| `packaging/huggingface/paper-writing-exam-trials/README.md` | Trial users | Hugging Face | Updated | Trajectory retrieval, use, and limits |
| `packaging/huggingface/paper-writing-exam-source-archive/README.md` | Provenance reviewers | Hugging Face | New | Registry, archive boundaries, and licensing |

## Release check

Before publishing a documentation update, verify that the task card's task
counts and revision match the task manifest, the trial card links the correct
task dataset, and the source-archive card links the matching registry/revision.
`tests/test_documentation_references.py` enforces the stable cross-dataset
navigation in this repository; it does not replace release-specific review.
