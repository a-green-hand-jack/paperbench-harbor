# Issue 70 Implementation Checklist

Authoritative scope: https://github.com/a-green-hand-jack/paperbench-harbor/issues/70
All six implementation phases remain tracked. An unchecked item is not complete.
The user has authorized committing and pushing the current implementation, but
not dataset upload/publication or issue closure. The latest direction is to stop
pytest and Hello World runs and focus verification on PaperSmith task production.

- [ ] Phase 1: structured request and displayed defaults; single/batch/verification/release thresholds; four entry permissions and CLI agreement; immutable source/rebuild revisions; separate local/upload/publish intent.
- [ ] Phase 2: evidence-first structured extraction; source assets with license/version/hash and missing/exclusion reasons; fact locations; synchronized public requirements/private evidence; boundary and sufficiency gates; preserve submission contract.
- [ ] Phase 3: four versioned knowledge packages with selection, schema, material contracts, executable research-type validators, review guidance, examples and sources; unsupported-type rejection; separate mathematical reconstruction/proof discovery; reviewed version maintenance.
- [ ] Phase 4: full-material independent structured review; actionable classified defects; directed retries; persistent stage/config/hash/report/error state; resume and stage rerun; downstream invalidation; honest isolation guarantees.
- [ ] Phase 5: writer-only real Harbor trials with model/revision/package/config/trajectory evidence; combined diagnostics separating environment/material/model causes; fidelity/semantic/determinism reuse; separate contract/material/scientific results; representative live task for each supported domain research type.
- [ ] Phase 6: bound task/private/construction delivery and honest target/approved/failed/blocked/unfinished counts; evidence/hash release gate; explicit upload/publish and remote SHAs; four entry/CLI/examples/resume/package/limitations documentation; natural-language live end-to-end delivery.
- [ ] Verification: actual PaperSmith construction, material review, conversion and delivery evidence; recheck independent-review fixes and record remaining criteria. Historical pytest/Hello World runs below are not PaperSmith acceptance evidence.

## Implementation And Verification Record

Implementation is present across all six phase surfaces, but no phase is marked
accepted until its complete criteria, including applicable live checks, pass.

- Phase 1 changes: request schema/display, one-task default, separate verification/release thresholds, four entry permissions, agent-approval promotion argument, mandatory immutable published-manifest revision, explicit upload intent.
- Phase 2 changes: typed located research evidence, source asset metadata, extraction before material generation, public requirement/private evidence agreement, copied-answer/path/symlink checks, adapter export of writing requirements.
- Phase 3 changes: versioned experimental LifeSci, simulated physics, synthesis/characterization chemistry and theorem/proof mathematics packages, typed quantitative/relational validators, unsupported capability/type rejection.
- Phase 4 changes: complete material staging, structured defects, input mutation checks, retry integration, atomic per-paper stage records and configuration/material-bound reuse. Independent review completed; second-round fixes await independent recheck.
- Phase 5 changes: real Docker Harbor trial invocation and artifact recording, material-review-aware diagnostics and separate scientific-quality status. Representative four-domain live acceptance has NOT completed.
- Phase 6 changes: batch counts and unfinished status, artifact-bound release checks, opt-in upload/publication and remote commit resolution, Chinese workflow and four updated natural-language entries. Natural-language-to-domain-delivery live acceptance has NOT completed.

Historical first-round checks on Linux using the existing Python 3.12 repository
environment (not verification of the latest fixes, and not task-production acceptance):

```text
.venv/bin/python -m pytest tests/test_papersmith_evidence.py tests/test_construction_core_review.py tests/test_release_candidate_supervisor.py scripts/test_publish_paperrecon_release.py tests/test_promote_lifesci_paperrecon_candidates.py -q
93 passed in 2.81s

.venv/bin/python -m pytest -q
461 passed in 7.10s

.venv/bin/python -m pytest scripts/test_publish_paperrecon_release.py scripts/test_promote_lifesci_paperrecon_candidates.py -q
45 passed in 0.97s

.venv/bin/python -m ruff check .
All checks passed!
```

The structured CLI describe-request check displayed target=1 and both remote
write intents=false without executing a build. The credential-safe provider
audit and one live OpenCode provider health request passed. A read-only Hub info
request returned an immutable dataset revision; no upload was performed.

The generated first-party Hello World task ran with the installed Codex
0.153.4 and model `openai/gpt-5.5` under Docker. The first foreground call hit
the tool's 120-second timeout; native `harbor job resume` then completed:

```text
Trials 1 | Exceptions 0 | Mean 1.000
Reward 1.0 | Count 1
```

Local, ignored evidence: `.cache/issue-70-live/jobs/hello-world-codex/`.
This is contract smoke evidence, not four-domain material acceptance.

## Parent Review

The parent completed native independent review in `ses_f8eabcc15ffend7gvS7wZjm108`.
The previous reviewer permission blocker is resolved. The implementation worker
reports fixes for findings 1-9 and 11-18 applied; these remain unchecked pending
independent recheck. Finding 10 is the incomplete full-domain acceptance below.

- [ ] Findings 1-3: initialized source IDs, explicit request semantics/handoff, pre-write Git-root guard.
- [ ] Findings 4-6 and 15: contained release layout and bound native result, trial report, construction review, knowledge, execution and trajectory evidence.
- [ ] Findings 7-8 and 17: verified Harbor env-template semantics; authoritative public-boundary checks with pinned-code exception and symlink rejection.
- [ ] Findings 9 and 11-14: all reviewer inputs hashed, consistent structured example, located defects and repair feedback, complete source/implementation invalidation.
- [ ] Findings 16 and 18: malformed trial output persisted as failure, identity-based honest batch counts.
- [ ] Finding 10: four representative live acceptances and natural-language-to-delivery run.

Still required: complete independent review and fix findings; representative
full-domain construction, fidelity/semantic/determinism audits and writer trials
for all four supported research types; natural-language-to-delivery live runs;
verification of any fixes and final criterion-by-criterion acceptance. Actual
remote upload/publication remains unauthorized and has not been attempted.

## Actual PaperSmith Progress At Commit

Local live evidence root (not committed):
`/home/user/harbor-apex-smoke/papersmith-issue70`.

- LifeSci: `2511.19535v1` completed construction, independent material review,
  fidelity/semantic/determinism checks, downstream trial and local archive staging.
  `lifesci-retry/run-summary.json` records approved_count=1, failed_count=0,
  blocked_count=0. This is one accepted task, not four-domain completion.
- Physics: `2608.24682v1` compiled, but material review rejected missing numerical
  setup, tolerances and error-metric definitions. See
  `physics-retry/run-summary.json` and its located review defects.
- Mathematics: `2609.02220v1` reached downstream execution after construction and
  audit gates; the writer reported "Selected model is at capacity." A subsequent
  material review timed out while investigating recurrence-boundary consistency.
  This is not an accepted delivery; see `mathematics/run-summary.json`.
- Chemistry: bounded screening produced zero eligible candidates in
  `chemistry-retry/candidates.json`; no constructed task is claimed.
- Fresh natural-language LifeSci entries displayed the request and invoked the
  runner. The final foreground interaction was interrupted; its runner completed
  the accepted LifeSci summary. A completed final natural-language response is
  not claimed.

The worker has stopped and reports no remaining PaperSmith processes. Current
code is being committed as implementation progress, not as closure of issue 70.
