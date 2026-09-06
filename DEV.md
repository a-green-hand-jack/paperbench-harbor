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
count. Do not run a downstream writer, demand reward=1, publish or upload as an
implicit acceptance step. Historical stopped volumes/runs listed in HANDOFF.md
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

## Issue 71 实际验收结果

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
