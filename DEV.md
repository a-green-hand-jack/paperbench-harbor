# PaperSmith Developer Workflow

## Build The Installed Product

```sh
make lint
sh docker/e2e.sh build
sh docker/e2e.sh exec papersmith --version
sh docker/e2e.sh doctor --json --headless
PAPERSMITH_NETWORK=none sh docker/e2e.sh run \
  'Discover suitable scientific papers on any topic' --count 5 \
  --output /runs/request-shape --describe-request --headless --json
```

Docker uses root `install.sh` to build/install the current source wheel into
`/opt/venv`, then removes build source. Runtime cwd is `/runs`, with no source
mount and no `PYTHONPATH`. Source changes require `build` again. Dependency layers
are cached; source layers and the wheel are rebuilt when bytes change. The
allowlisted build context excludes `.env*`, auth files, caches and host state.
Never place credentials under arbitrary source filenames.

`doctor` without credentials may fail model discovery. Even a successful doctor
does not prove authentication or task construction. `--describe-request` writes
no task/workspace and makes no calls. `status` and `validate` on an unknown path
return a JSON error and nonzero status. No synthetic unit suite or fake E2E task
is used. The benchmark's shipped verifier remains intact.

## Narrow Provider Mounts

By default there are **no credential/config mounts**. Configure only the provider
needed for the run. Do not mount the host home, Docker socket, entire OpenCode
configuration tree, or entire account directory. Do not read or log credential
contents. Do not use `opencode debug config`.

| Variable | Purpose |
| --- | --- |
| `PAPERSMITH_OPENCODE_CONFIG` | Absolute secret-free OpenCode JSON/JSONC file, read-only at `/opt/opencode.json`, selected with `OPENCODE_CONFIG` |
| `PAPERSMITH_OPENCODE_AUTH` | Optional single OpenCode auth file mounted read-only at `/state/home/.local/share/opencode/auth.json` |
| `PAPERSMITH_READONLY_PATHS` | Newline-separated absolute individual provider modules, credential files or dependency directories, mounted read-only at their original paths |
| `PAPERSMITH_INPUT` | Optional scoped research directory mounted read-only at `/input`; pass `--source /input` to import it privately |
| `PAPERSMITH_NETWORK` | `bridge` by default; explicit `none` allowed, host networking refused |
| `PAPERSMITH_VOLUME_PREFIX` | Dedicated persistent runs/state/cache volume names |
| `PAPERSMITH_IMAGE` | Image tag, default `paperbench-papersmith:dev` |
| `PAPERSMITH_CONTAINER_NAME` | Optional name for monitoring/stopping a detached controller |
| `PAPERSMITH_DETACH` | `1` launches detached and retains its container |

Use `docker/opencode.example.json` as a secret-free built-in-provider example.
For an external OAuth provider, use a reviewed secret-free config selecting its
exact npm module and credential-file path, and explicitly list that module, its
required sibling modules/dependencies, and only the chosen auth file in
`PAPERSMITH_READONLY_PATHS`. Absolute imports retain their paths. The wrapper
reuses the existing narrow same-path mount adapter; broad `HOST_CONFIG` mode is
retired. It does not change generated host configuration or copy credentials
into the image/repository. Read-only OAuth refresh may fail; refresh the host
login externally, then resume. The host's OpenCode remains usable.

The image's passwd home matches the caller's home path for provider adapters
that consult passwd; runtime `HOME` is `/state/home`. For adapters using fixed
absolute account paths, explicitly mount those individual files at those paths.
Do not confuse an isolated named volume with a bind mount of the host home.

## Live Acceptance, Run Separately

Only after provider configuration and explicit authorization for paid calls:

```sh
PAPERSMITH_DETACH=1 PAPERSMITH_CONTAINER_NAME=papersmith-five \
  sh docker/e2e.sh run 'Discover suitable scientific papers on any topic' \
  --count 5 --output /runs/issue71-five --headless --json
docker logs -f papersmith-five
sh docker/e2e.sh status /runs/issue71-five --json
docker stop --time 60 papersmith-five
sh docker/e2e.sh status /runs/issue71-five --json
sh docker/e2e.sh resume /runs/issue71-five --headless --json
sh docker/e2e.sh validate /runs/issue71-five --json
```

Public defaults are execution `openai/gpt-5.6-terra` and all review gates
`openai/gpt-5.6-sol`. Supply `--model` and `--review-model` externally if the
authorized provider uses account aliases. No private alias is hardcoded.

`run` maps to `papersmith create`; `status`, `resume`, `validate`, `doctor` map
directly to installed CLI commands. `exec` accepts any installed command and
does not implicitly launch a model. Build explicitly before a fresh run or
resume after editing. Preserve the image ID when exact implementation replay
matters: `docker image inspect paperbench-papersmith:dev --format '{{.Id}}'`.

The named `<prefix>-runs` volume contains `/runs/issue71-five`, including
`run.json`, append-only `events.jsonl`, and all attempt directories. JSON results
name final task directories. `docker logs` records structured progress and the
final JSON result; raw provider output is deliberately suppressed. Receipts retain
model IDs, session IDs, timings and exit codes. Use OpenCode's session tooling to
inspect provider-side failures, never dump raw auth/config diagnostics.

Interrupt **after a gate has passed**, record the checkpoint and stop time, then
resume. Acceptance must show `checkpoint_reused` for unchanged passed nodes,
continuation from the interrupted node, five distinct admitted task paths, and
real separate-session evidence for each review gate. No wall-clock limit is
applied to model phases or the run. Rejections are replenished; pathological
model/schema failures can keep repairing until the operator interrupts.

Do not equate build, doctor, request display or a successful process exit with
task delivery. `validate` checks the current hash-bound evidence and requested
count. Downstream oracle/nop acceptance is a separate explicit host operation,
described below; never publish or upload implicitly. Historical stopped volumes/runs listed in HANDOFF.md
are untouched and must not be restarted or deleted by this workflow.

## Failure Handling

Generic delivered tasks now explicitly disable writer-phase and verifier-phase
network access while retaining the baseline for environment setup. Their verifier
enforces declared neutral source citation keys (or a supplied bibliography key),
fails on BibTeX errors, and checks the final compilation log for unresolved citations.
These are generic-only template branches; upstream benchmark renderings stay unchanged.
Review prompts carry gate-specific JSON object keys and the controller's mandatory
conversion-evidence IDs, including the installed Harbor layout-validation report.

OpenCode 1.18.29 checks `read` permissions against worktree-relative paths (`/` is
the worktree for these non-Git runs). The controller grants only the selected
paths in that representation as well as their absolute form, not a root-wide
read permission. Required-artifact read errors now stop as `ModelAccessError`
instead of being misclassified as scientific repair; allowlisted `artifact_read`
events and receipt entries expose actual completed/error reads without tool payloads.

Mechanical evidence bookkeeping is controller-owned. Reviewers select IDs from a
saved `evidence-catalog.json` and supply substantive judgments; each ID already
contains its actual path, hash, range and excerpt. `review-bindings.json` records
the deterministically expanded selections. Materials may select source-support
IDs or supply a unique excerpt for controller resolution; ambiguous quotes fail
explicitly rather than binding to an arbitrary occurrence.

Proposals supply source/metadata URLs, not exact publisher-rendered quotations.
The controller extracts citation/canonical identity fields and recognized license
links from fetched publisher metadata, retains original snapshots, and supplies
anchored extraction evidence for independent license/authority review. Extracted
links are not automatic license approval. Legacy quote fields can be parsed as
recovery inputs but are discarded, never promoted into review evidence.

A changed implementation can recover a hash-verified completed proposal and its
source snapshots as inputs to a NEW offline proposal session and current review.
`proposal_input_recovered`/`source_snapshot_reused` mean input reuse, not an unchanged
passed checkpoint. Actual unchanged nodes emit `checkpoint_reused`. Three consecutive
mechanical validation failures at a phase in one explicit invocation stop with a
structured `blocked_reason`; infrastructure failures stop immediately. No phase
wall-clock cap is imposed and the admitted five-task target is unchanged.

Discovery with web tools has no filesystem read permission and receives only the
user's public selection request, generic controller repair guidance and public
DOI/arXiv exclusions. Never put confidential content in a public discovery request.
Local-source proposals instead run offline with access only to the imported
source directory. Materials and review sessions deny webfetch/websearch and read
only their explicitly selected current source/artifact paths. Source acquisition
remains controller-owned; no private review feedback is sent to web-enabled discovery.

Paper identity is derived from retrieved primary DOI/arXiv/canonical metadata,
with paper-level aliases and source hashes enforcing deduplication. Proposal labels
and duplicate identity/receipt fields in `run.json` are not acceptance evidence.
Current validation reads the hash-bound attempt's `receipt.json`, checks model,
role, session, exit status, read/network policy and actual response-file hash,
and audits terminal failed/rejected/interrupted attempts as well as passed ones.
Required manuscript headings use schema-enforced plain ASCII words/punctuation,
without LaTeX commands or reserved characters (write `and`, not `&`).

Existing version-1 checkpoints load without rewriting their attempts. Legacy
receipts lacking the new evidence contract are reported explicitly and cannot be
promoted into current acceptance. On a parent-authorized restart, affected nodes
rerun and the old artifacts remain in history; no receipt or approval is fabricated.
Implementation changes invalidate affected checkpoints. Prove unchanged-checkpoint
reuse with the same new image before/after interruption, rather than disguising
an implementation upgrade as unchanged execution. Do not stop an active old-image
container merely because a separate replacement image has been built.

Review evidence now uses workspace-relative current artifact paths, SHA256 values,
and checked line/page excerpts. Source-support locators are enforced, not treated
as descriptive strings. Checkpoint current/history paths must match the candidate
attempt layout; symlinks and external evidence paths are rejected before reads.
Source retrieval validates the actual connected IP before TLS/HTTP, including
redirects, and does not use environment HTTP proxies. Retrieved metadata/license
snapshots are hash-bound; remote version claims do not imply immutable upstreams.

Generic conversion invokes the installed Harbor task parser before gate 3 and
records `harbor-validation.json`. It does not build a nested image or run a writer.
Its writer image installs no Claude agent. The generic-only verifier additionally
requires 200 prose words and the declared section headings with 20 words each;
requirements map to those sections. This rejects empty/template-only submissions,
not scientifically incorrect prose. Existing upstream verifier output is unchanged.

- Missing executable/model: fix the named dependency/provider; doctor makes no
  paid call and reports authentication as unverified.
- Auth/network failure: controller records `blocked`, preserves earlier phases,
  and exits nonzero. Fix infrastructure externally and call `resume`.
- Invalid source/material artifact: targeted repair feedback goes to a fresh
  builder session; no manual approval exchange is needed.
- Reviewer `repair`: return to proposal for gate 1 or source/license findings,
  otherwise materials for gates 2/3.
  Reviewer `reject`: preserve exclusion and discover a replacement paper.
- Stale evidence: input/output/implementation hashes invalidate affected nodes.
  Never edit checkpoint hashes to force readiness.
- Existing output/active controller: use `resume`; a nonblocking filesystem lock
  prevents two controllers from writing the same run concurrently.

Containers run as the ordinary host UID/GID with a read-only image, dropped
capabilities, no-new-privileges, a PID limit and temporary `/tmp`. Only dedicated
runs/state/cache volumes are writable. This is containment, not a guarantee
against a compromised kernel/provider module. Model tools cannot execute shell
commands or write files; controller parsing/conversion owns task bytes.

## Original Ground Truth And Oracle Scope

### Ground-Truth V2 Corrections

`paperbench-papersmith:ground-truth-v2` removes the direct-proposal-PDF shortcut.
Even a supplied PDF with the right title and DOI must have an observed authoritative
acquisition relationship. The controller obtains `citation_pdf_url` when present,
or the known arXiv abs-to-PDF relationship. Cached PDFs require matching acquisition
URL, metadata SHA256 and PDF SHA256 bindings; old unbound PDF caches are refetched.

Source discovery inspects marked source/archive/download links selected by suffix,
relation, MIME type, visible/accessibility text or download attribute, including
extensionless endpoints. It records the original tag/location plus response MIME,
Content-Disposition filename and body inspection. Known PDF/image links are excluded;
HTML/PDF/image responses are not promoted to TeX, and HTML landing pages are not
crawled. No candidates means `not_discovered`; failed/non-TeX candidates mean
`unavailable_in_inspected_candidates`, never exhaustive absence.

Oracle retries receive only the fixed category `conversion_retry` or
`initial_conversion`. No prior exception text, private paths or reviewer excerpts
are interpolated into its prompt. Its legitimate manuscript, bibliography,
portable source and normal verifier contract remain unchanged.

Construction, PDF parsing and oracle compilation retain unlimited default wall-clock
duration and existing operator interruption/resource limits. No timeout was added.
Building v2 neither stops nor resumes `papersmith-five-ground-truth-v1`; the parent
owns that decision and all live model/Harbor runs.

Implementation is ready for live orchestration, **not yet live-accepted**. No new
five-task model run, task image build, or Harbor oracle/nop reward is claimed.
The historical five exports below remain unchanged and do not satisfy the new
mandatory original-PDF/oracle contract. Do not overwrite their run or export paths.

The four steps and three gates are unchanged. Proposal acquisition now requires
`sources/ground_truth/paper.pdf`, automatically following focal `citation_pdf_url`
instead of trusting a builder's choice of HTML. `pdfinfo` and `pdftotext` verify
parseability, pages, extractable prose and focal first-page title/identifier.
Gate 1 must cite the actual PDF, text and acquisition manifest and assess its
visual readability, rights and original-source availability.
Acceptances also require receipt evidence of direct original PDF/text reads, and
gate 3 must directly read the oracle preview; catalog-only judgments cannot pass.
The manifest retains
publisher source-link search and attempted original-TeX retrieval evidence. No
source found means **unavailable in searched sources**, not fabricated TeX.
ZIP/tar/gzip source bundles are boundedly extracted without executing originals;
gate 1 must assess identity and dependency completeness before accepting them.

Gate 2 must compare public materials to the actual original PDF/text. Conversion
copies the exact ground truth into `tests/private/ground_truth/`, labels model
notes `reference_notes.md`, rejects byte-identical originals and long private prose
in the writer image, and leaves semantic leakage checking to the independent gate.

Conversion's internal `oracle` attempt uses execution `openai/gpt-5.6-terra` in a
fresh offline session, reading only `instruction.md` and public materials. It
authors structured scientific manuscript content, tables, figure references,
bibliography and per-requirement coverage. Controller-owned TeX rendering escapes
model text, bundles public figures, and compiles without shell escape. Fixed
materials plus a fixed oracle response must render byte-identical source trees;
the compiled preview is reused byte-for-byte, not claimed to be independently
bit-reproducible. Nested oracle receipts and all artifacts are checkpoint-bound.
Gate 3 (`openai/gpt-5.6-sol`, like gates 1/2) reviews the new manuscript and rendered
preview against every public writing requirement and the private original. A
notes dump, dummy padding, unsupported claims or copied original is not acceptable.
No phase/model wall-clock cap has been added.

Harbor **0.22.0**'s installed `OracleAgent` uploads `solution/` to `/solution` and
executes `solve.sh`; its `NopAgent` does nothing. The bundled solve script copies
portable manuscript source and assets into `/workspace/submission` and compiles
them. It does not access private GT, edit tests, or write reward files. The generated
verifier checks the same normal submission contract for both agents. Empty nop
submissions fail explicit assertions and produce reward 0 through `tests/test.sh`.

Use externally selected narrow provider mounts as documented above. For a fresh
five-task run, preserving old volumes and exports:

```sh
export PAPERSMITH_IMAGE=paperbench-papersmith:ground-truth-v1
export PAPERSMITH_VOLUME_PREFIX=papersmith-five-ground-truth-v1
sh docker/e2e.sh build
PAPERSMITH_DETACH=1 PAPERSMITH_CONTAINER_NAME=papersmith-five-ground-truth-v1 \
  sh docker/e2e.sh run 'Discover suitable scientific papers on any topic' \
  --count 5 --output /runs/five-ground-truth-v1 \
  --model openai/gpt-5.6-terra --review-model openai/gpt-5.6-sol --headless --json
sh docker/e2e.sh status /runs/five-ground-truth-v1 --json --headless
sh docker/e2e.sh validate /runs/five-ground-truth-v1 --json --headless
```

For the current five PLOS papers, replace the selection prompt with an explicit
request for exactly these five identities (one candidate at a time):
`10.1371/journal.pone.0297034`, `10.1371/journal.pone.0304214`,
`10.1371/journal.pone.0274664`, `10.1371/journal.pone.0268440`,
`10.1371/journal.pone.0305882`. Their publisher metadata exposes PDF acquisition;
original TeX availability must be searched and reported rather than assumed.
Existing source snapshots can be recovered only through normal hash-verified
proposal recovery and NEW review stages; old approvals cannot authorize new GT.
For cross-run cache reuse, use `create --source-cache /runs/issue71-five` while
selecting the existing `PAPERSMITH_VOLUME_PREFIX=papersmith-issue71-five` runs
volume and the **new** output `/runs/five-ground-truth-v1`. This preserves the old
run and copies only hash-verified proposal acquisition inputs into the new run's
private `source-cache/`. All new proposal/review sessions still run. Keep the old
workspace at its recorded absolute path; do not rewrite checkpoint paths/hashes.
The fresh-volume command above intentionally has no cache to reuse.

Export the five **validated delivered paths**, including `solution/` and `tests/`,
to a new host directory such as `results/five-ground-truth-v1/`. With the retained
controller container, each exact path returned in `tasks` can be exported with:

```sh
# Create the NEW export directory once; never use the historical export path.
mkdir results/five-ground-truth-v1
docker cp papersmith-five-ground-truth-v1:DELIVERED_TASK_PATH results/five-ground-truth-v1/
```

Repeat `docker cp` for the five actual paths, not proposal/conversion attempts.
Then run the ten true trials on the **trusted Ubuntu host** (not inside PaperSmith):

```sh
HARBOR_BIN="$PWD/.venv/bin/harbor" sh docker/acceptance.sh \
  results/five-ground-truth-v1 results/five-ground-truth-v1-harbor
```

The host default `harbor` observed during implementation was 0.20.0; the existing
`.venv/bin/harbor` is 0.22.0. The wrapper refuses other versions and pre-existing
jobs directories. It invokes the installed CLI, not checkout agent code. Exact
single-task equivalents (use unique job names/directories) are:

```sh
.venv/bin/harbor run --path results/five-ground-truth-v1/candidate-0001 \
  --agent oracle --env docker --n-attempts 1 --n-concurrent 1 --max-retries 0 \
  --jobs-dir results/five-ground-truth-v1-harbor --job-name candidate-0001-oracle --yes
.venv/bin/harbor run --path results/five-ground-truth-v1/candidate-0001 \
  --agent nop --env docker --n-attempts 1 --n-concurrent 1 --max-retries 0 \
  --jobs-dir results/five-ground-truth-v1-harbor --job-name candidate-0001-nop --yes
```

Acceptance requires exactly ten completed trials, zero trial exceptions, actual
generated-verifier CTRF evidence, every oracle reward 1 and every nop reward 0.
`acceptance.json` is written from real trial results only. A compile preview or
gate acceptance is not a substitute for these trials. The writer and separate
verifier images are built by host Harbor; no Docker socket enters the autonomous
construction container. No credentials are needed for oracle/nop.

Known boundaries: PDF identity checks are deliberately conservative and may reject
unusual title extraction; archives may lack dependencies and need source repair;
unsupported Unicode/figures or an inadequate manuscript must be repaired before
gate 3. Scientific adequacy remains a substantive independent model assessment,
not a new deterministic science scorer. Live five-task/ten-trial acceptance remains
the parent's separate orchestration work.

## Issue 71 Historical Acceptance (Before Original-Ground-Truth Contract)

本轮已通过安装后的产品 CLI 在 Docker 内交付 **5/5** 个不同论文的 Harbor task。
不是源码导入、mock、Hello World 或下游 writer 的替代结果。

- 执行：`openai/gpt-5.6-terra`；三个审核点：`openai/gpt-5.6-sol`。
- controller 退出码 0，最终 `papersmith validate --json --headless` 退出码 0。
- `status=task_ready`、`task_ready_count=5`，`failures=[]`、`integrity_failures=[]`。
- 15 个不同审核会话全部接受，5 个目录均通过安装后的 Harbor `Task` 模型加载。
- 实际中断材料阶段再恢复，未变的 proposal/gate1 被复用；整个开发运行保留 68 次
  checkpoint 复用事件。实现或契约变更导致的失效单独记录，不冒充未变阶段复用。
- 共 6 个候选，第 1 个被拒绝，未计入产物。没有预设论文主题。

| 本地 task 目录 | 规范 DOI | 公开材料文件数 |
| --- | --- | --- |
| `results/issue71-five/candidate-0002` | `10.1371/journal.pone.0297034` | 17 |
| `results/issue71-five/candidate-0003` | `10.1371/journal.pone.0304214` | 9 |
| `results/issue71-five/candidate-0004` | `10.1371/journal.pone.0274664` | 11 |
| `results/issue71-five/candidate-0005` | `10.1371/journal.pone.0268440` | 8 |
| `results/issue71-five/candidate-0006` | `10.1371/journal.pone.0305882` | 9 |

`results/issue71-five/` 是 gitignored 的本地导出，不随源码提交。其
`delivery-summary.json` 记录审核 session/receipt 路径、输入输出哈希、恢复次数和镜像身份；
`final-validation.json` 保留完整校验输出；`export-manifest.json` 记录导出哈希。
原始阶段产物和失败历史继续保留在 volume `papersmith-issue71-five-runs` 的
`/runs/issue71-five`，认证状态 volume 不属于交付包。

最终镜像为 `paperbench-papersmith:issue71-schema-v7`，ID：
`sha256:8cdd920b6dbd9b0e3fb9c238bef374aed0fce8b5648592f46673b7625694ac66`。
容器 `papersmith-issue71-five-10` 已完成并退出，没有继续补选。源码基线为
`631c01c` 加本轮未提交实现；摘要记录实际源码 SHA，而不是声称仅该提交可复现。

不调用模型、不加载认证、断网重新校验保留的工作区：

```sh
PAPERSMITH_IMAGE=paperbench-papersmith:issue71-schema-v7 \
PAPERSMITH_VOLUME_PREFIX=papersmith-issue71-five \
PAPERSMITH_NETWORK=none \
sh docker/e2e.sh validate /runs/issue71-five --json --headless
```

本轮完成的是通用制题 E2E。没有执行下游写作、五个任务各自的 Docker 镜像构建或
论文科学质量认证，没有上传或发布数据集，也没有自动 commit/push。
