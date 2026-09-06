# PaperSmith Handoff

## 2026-09-07 Current Contract-v3 Progress

This handoff records the latest live push toward the ideal PaperSmith shape.
The working tree is Ubuntu `main`; no credentials or auth-file contents were
read or copied. The wrapper repair and this handoff are delivered together in
the commit that contains this section.

### Shipped wrapper repair

`docker/e2e.sh` now keeps the `/runs` volume non-empty during root
initialization, preventing Docker from copying root-owned image workdir metadata
over the caller-owned volume when the controller uses `--workdir /runs`. It also
passes the validator-approved `RUFF_CACHE_DIR=/cache/ruff` value. The provider's
Node dependency directory must be supplied as an explicit read-only mount; a
direct import check succeeded inside the image.

### Live evidence

The fresh contract-v3 run is retained in the private acceptance state under
`papersmith-current-v3-real3-2004351`, with run root `/runs/current-v3-one`.
The model provider initialized and the run reached proposal, original-PDF
acquisition, checkpoint reuse and gate1 independent review. Gate1 correctly
rejected several candidate/reviewer outputs for source-bound provenance,
original-availability citations, HTTP 202 evidence and malformed/truncated JSON.
The latest container was stopped after it became orphaned, so the run is
`interrupted`, not accepted. No five-task extension and no Harbor oracle/nop
acceptance are claimed.

### Verification

- `sh docker/e2e.sh build` passed.
- `sh -n docker/e2e.sh` passed.
- `.venv/bin/ruff check .` passed (`All checks passed!`).
- `python -m compileall -q src` passed (only pre-existing vendor escape warnings).
- `git diff --check` passed.

### Next operator action

Resume `/runs/current-v3-one` with the same locked provider/model configuration
and narrow read-only provider mounts. First address the gate1 reviewer contract
format/provenance failures; then continue through gate2, conversion, gate3,
actual Harbor `oracle=1`/`nop=0`, and only afterward extend the target to five.
Keep all prior attempts and volumes; do not force-migrate historical runs.

GitHub tracking issue for the ideal end-state: create separately from this code
delivery and keep it open until the current contract-v3 acceptance criteria are
met.

## FD9 Lifecycle Integration Verified

The installer-held environment lock now survives detached `acceptance.launch`
through explicit `pass_fds=(9,)`. The installed worker requires exactly the declared
FD9, verifies its regular-file inode against the resolved environment's lock path
and checks Linux exclusive FLOCK metadata. No explicit unlock is performed; the
supervisor owns the inherited description until exit. Docker children close inherited
descriptors. Process-start installed identity/protocol are frozen; the worker checks
disk identity for changes instead of redefining its heartbeat identity.

Current installed image: `paperbench-papersmith:contract-v3-fd9`.
Image ID: `sha256:2aaf4170e1af6edd66e703eb1c281a65804f84b2009a736f2dbacd587ef2e26d`.
Image wheel and independently rebuilt current-source wheel both SHA256:
`7cb8164bb433b2c3d3a896dcd15f5cf6a07a1620c83c0ea084a1f3b49bbf5c75`.
Installed package identity matches between the existing host venv and image:
`37553504046fde08f3bfc5124ac0a60f96eb95183b1c2409012086e856d071a3`.

Credential-free installed observations (network disabled, no model calls):

- Wrapper `run --describe` with `PAPERSMITH_DETACH=1` and a nonexistent host Python
  succeeded synchronously with `model_calls=0`; no host invocation/state was created.
- The wrapper installed the exact image wheel into the existing `.venv` under its
  environment lock. A deliberate missing-workspace resume exited 1 before any model
  work, with an exited foreground supervisor and unchanged process/disk identity.
- A directly invoked installed detached worker ran a real `create --describe-request`
  controller. Its own container was briefly paused solely to observe concurrency.
  Supervisor PID `1890357` retained FD9 after the launcher exited: device `66306`,
  inode `6323012`. Docker child PID `1890484` held no descriptor for that inode.
- Owned container `bb20d0e326b4751d11c47605279415f1b755739a7c1a337b63f91fabf75340d9`
  had worker label `bec11d37b425495da6979dfa3d4e9099` and the current image ID.
- A real concurrent wrapper invocation exited 2 with `Host environment is in use;
  no packages were changed.` Installed identity, package inode and mtime were unchanged,
  and no competitor invocation directory was created.
- Heartbeat retained the frozen identity while the controller was paused. After
  unpause the real describe controller and supervisor exited 0, `model_calls=0`,
  owned-container cleanup reported stopped, and a new nonblocking lock acquisition
  succeeded only after supervisor exit.
- The first event-observation attempt missed its pause because the Docker event
  formatter used the wrong field; that real detached describe still exited 0. The
  corrected observer used `.Actor.ID` and established the overlap evidence above.
- Ruff and `git diff --check` passed. No model/Harbor scientific E2E or commits ran.

The fixture containers are stopped and retained; old runs were not touched. The
managed disposable observation directory is cleaned after recording this evidence.
The root `.papersmith-environment.lock` is an intentional runtime inode, not a source
file: do not commit it or unlink it as a cleanup shortcut. Parent scientific review
and one-then-five acceptance launch remain separate from these lifecycle checks.

## Current Comprehensive Optimization

Base: clean `main` at `267cf81` on Ubuntu. This phase owns PaperSmith source,
common templates and product docs; installer lifecycle remains with the parallel
agent (`install.sh`, Docker wrapper/image and `pyproject.toml` are not edited here).
No commit/push, pytest, paid model call or long Docker E2E is authorized in this
phase. The parent owns native review and subsequent live launch.

Contract v3 locks full manuscript by default, explicit summary/identifier policies,
discovery versus fixed canonical papers and coherent replacement/count behavior.
Materials now require item coverage, per-asset rights/credit and structured tables
with cell anchors, exact CSV/JSON values and interpretation metadata. Conversion
uses the public real TeX starter; template proof is distinct from a completed oracle.
Compile failures retain the successful model response for mechanical resume.
All reviews share the locked objective. Real Harbor oracle=1/nop=0 remains mandatory
alongside Sol scientific review, never replaced by template compilation.

Installer integration surface: `papersmith identity --json` returns stable installed
content identity and separate acceptance protocol; `papersmith acceptance-status
--state PATH --json` reports request lifecycle snapshots. Reuse the installer agent's
governed installation/process lifecycle, do not create duplicate environments.

Next live sequence, only when parent launches: build/install the current image;
create one task; inspect original PDF/TeX availability, genuine starter, structured
tables and rights/coverage; confirm three reviews and actual oracle/nop receipts;
then expand the same target to five and verify interrupted checkpoint reuse.
The delivery artifact index links all these proofs. Keep existing results, volumes
and history unchanged. Old PNG-table/Markdown-template successes do not establish
the current scientific contract, and old runs are not force-migrated.

Static verification completed for this phase:

- `.venv/bin/ruff check src/paperbench_harbor/papersmith`: `All checks passed!`
- `.venv/bin/python -m compileall -q src/paperbench_harbor/papersmith`: exit 0.
- `uv build --wheel --out-dir /tmp/opencode/papersmith-contract-v3-wheel`: successful.
- `.venv/bin/python -m zipfile -t /tmp/opencode/papersmith-contract-v3-wheel/paperbench_harbor-0.2.0-py3-none-any.whl`: archive integrity passed.
- `git diff --check`: exit 0.
- Source CLI `create --help`, `identity --json` and no-write `--describe --json`
  checks passed, including fixed canonical DOI normalization and deliberate summary/
  anonymized selection; request display reports `model_calls: 0`. Invalid argparse
  input returns structured JSON with `classification: usage` and exit 2.

Wheel SHA256: `0dd0012f5cdcdb4e3bb81c7553e5b1098405920bc4e2c2ee7149a6f65c98f1b2`.
Source CLI checks explicitly used `PYTHONPATH=src`; the initial existing-venv probe
loaded the old installed wheel and is NOT evidence for this implementation. No
environment was overwritten or duplicate runtime installation created. Current-image
installed CLI checks and real scientific/oracle/nop acceptance remain parent-launched.

Everything below is historical context, not current launch instructions or proof
of this optimization's acceptance. README and DEV define the current interface.

## Issue 71 Implementation Handoff

The sections below preserve the stopped issue-70 run history. Their old script
commands and review-model choices are not current instructions. Issue #71 now
uses installed `papersmith` through root `install.sh` and `docker/e2e.sh`; see
README.md and DEV.md. Execution defaults to `openai/gpt-5.6-terra`; all three
independent reviews use `openai/gpt-5.6-sol` unless explicitly overridden.

The current implementation is uncommitted. Static lint, wheel build and installed
Docker CLI checks are separate from acceptance. No paid construction was started.
The parent should run native review and the five arbitrary-topic task acceptance,
including interruption after a passed gate and evidence of checkpoint reuse.
Existing stopped runs, containers, volumes and unique artifacts remain preserved.
The new no-model checks use volume prefix `papersmith-issue71-install-checks`.

## 停止状态

用户要求停止所有本次工作、提交当前修改并交接。已停止容器
`papersmith-physics-e2e-terra-2`，没有删除容器、volume、checkpoint 或产物。
停止后 `docker ps --filter name=papersmith` 没有运行中容器。
其他项目的容器没有操作。不要自动恢复，等待用户再次授权继续。

Issue：https://github.com/a-green-hand-jack/paperbench-harbor/issues/70
工作目录：Ubuntu 上的 `~/orca/projects/paperbench-harbor`，分支 `main`。
本次只 commit，不 push、不关闭 Issue、不上传或发布数据集。

## 最新用户要求

- PaperSmith 在 Docker 内端到端运行，目标产物是 Harbor task。
- 不用 pytest，也不运行下游 Hello World；根目录 `tests/` 已按要求删除。
- 默认允许联网，允许挂载 OpenCode 和 Codex 配置及必要认证文件。
- 制题阶段不设默认时长上限，不再用 60 秒试跑代替实际制题。
- 支持 checkpoint，从失败或中断节点恢复，不重复有效的成功阶段。
- 构建模型使用 `openai-evelyn/gpt-5.6-terra`，不要使用 `gpt-6-astra`。
- 材料评审、转换语义评审仍为 `apex-claude/claude-sonnet-5`，执行后端是
  OpenCode CLI，不是 Claude Code。

## 已实现

此前提交：`1571477` 为证据驱动制题框架，`a4f37bc` 为 Docker/配置挂载/删除测试目录，
`4b5bbda` 为早期有界物理诊断记录。本次提交包含：

- evidence/build/materials/validate/review/delivery 和 conversion/audit/archive
  的原子 checkpoint、输入输出指纹、历史与唯一 attempt 日志。
- 未完成的 `running` 节点可重试；review 基础设施失败只重试评审；明确拒绝则返回材料修复。
- 模型、模板、来源、相关实现按阶段使结果失效；timeout/重试预算变化不清空科学结果。
- 制题 subprocess、评审及编译默认无限时；HTTP 请求/可用性探测等低层超时保留。
- `task_ready` 表示构建并审计得到 Harbor task，与可选的下游 trial 和发布验收分开。
- 可选 trial 的成功结果通过证据复核后可复用，不强制在制题容器中运行下游 Docker。
- 本地 dirty 代码的产物记录 base commit、实现 digest 和 dirty 状态；正式发布拒绝不完整或 dirty provenance。
- Docker wrapper 支持后台运行、显式容器名、无缓冲日志；默认 bridge 网络、只读源码与配置、专用 volume，无宿主 Docker socket。

开发说明：`DEV.md`。详细入口：`scripts/run_paperrecon_domain.py`。
恢复核心：`src/paperbench_harbor/construction/core/{pipeline,state}.py`。

## 真实运行到哪里

论文：`2608.24682v1`，Chebyshev interpolation in Einstein-Boltzmann codes，
内部 ID `paper_1`。复用已核验候选和 SHA-bound approval；未伪造批准或成功 checkpoint。

首轮无限时任务使用 `openai-evelyn/gpt-6-astra`，提取期间账号额度耗尽，
OpenCode 返回 `The usage limit has been reached`，三次调用后退出 1。
下载资产和研究证据文件保留。这不是 Docker 权限或超时错误。

用户恢复账号后要求改为 Terra。第一次恢复命令误用了
`verifier/agent-approval.json` 路径，立即失败；实际文件是根目录的
`/runs/physics-e2e/agent-approval.json`，已用正确路径重新启动。

最新 Terra 容器 ID：`5db728c5e42259be01022d68eb986e3bed11fc8c0b525f2021964a542bbf43d8`。
用户停止时仍在 evidence 阶段。停止后读取 checkpoint 确认 `evidence.status=running`，
这是中断记录，不是通过记录。尚未获得本轮完整 `task_ready` Harbor task，不能宣称 Issue 完成。

持久 volumes：

- `papersmith-physics-e2e-runs`：任务、材料、日志与 checkpoint。
- `papersmith-physics-e2e-state`：容器会话与状态，可能含认证相关状态，不应公开归档。
- `papersmith-physics-e2e-cache`：缓存。

运行根目录 `/runs/physics-e2e`，重要路径：

- `candidates.json`、`agent-approval.json`、`approved_scaleup.jsonl`。
- `scratch/paper_1/original/`：已获取的源资产和研究证据。
- `build/paper_1/stages.json`：当前 evidence 中断节点。
- `stages.json`：后续转换、审计、归档 checkpoint，前面未通过时可能尚不存在。
- `execution.json`、`request.json`、`run-summary.json`：执行配置与摘要；强制停止时摘要可能仍是上一轮状态，应结合 checkpoint 判断。
- `logs/`：各阶段唯一日志；`runner.log` 是首轮启动的日志，不代表后续所有容器。
- 预期最终目录：`dataset/physics-paperrecon-short/`、`source-archive/`，尚未确认生成。

## 授权继续后的恢复命令

先阅读 `DEV.md` 和 checkpoint，不要删除或重置 volume，不要重新生成批准文件。
使用新容器名，避免与已停止的历史容器冲突：

```sh
export PAPERSMITH_HOST_CONFIG=1
export PAPERSMITH_VOLUME_PREFIX=papersmith-physics-e2e
export PAPERSMITH_READONLY_PATHS="$HOME/.config/opencode/account-auth/gpt-evelyn.auth.json
$HOME/.config/opencode/account-keys/apex-claude.key"
export PAPERSMITH_DETACH=1
export PAPERSMITH_CONTAINER_NAME=papersmith-physics-e2e-terra-resume

sh scripts/papersmith-docker.sh run \
  --domain physics --research-type simulation --target-count 1 \
  --run-root /runs/physics-e2e \
  --candidates /runs/physics-e2e/candidates.json \
  --agent-approval /runs/physics-e2e/agent-approval.json \
  --model openai-evelyn/gpt-5.6-terra \
  --reviewer-model apex-claude/claude-sonnet-5 \
  --conversion-reviewer-model apex-claude/claude-sonnet-5 \
  --promote --build --convert --audit --stage-candidate --resume
```

不要加 `--timeout`。不要同时启动两个写同一 run-root 的 runner。上述只读认证挂载
是用户明确授权的范围；不读取/打印凭据，不将凭据写入镜像、仓库或日志，不运行
`opencode debug config`。已提交代码不代表旧 dirty 阶段被追认为 clean 发布证据。

## 验证与剩余工作

容器内 OpenCode、Codex 的短真实请求此前均成功。checkpoint 修改经过容器内 Ruff、
Python 编译及无凭证的合成恢复场景检查，覆盖成功复用、失败重试、材料变化、损坏状态、
trial 证据篡改和 dirty 发布拒绝。这些不能替代物理端到端验收。

独立代码审查已做一轮，发现的 runner 指纹、checkpoint schema、失败分类、trial 复用和
dirty provenance 问题已有修复；最终补丁尚未重新独立复审。停止时只做提交前 diff 检查，
没有启动新实验或测试。

下一位执行者需在用户授权后：恢复 Terra evidence；根据真实错误逐节点修复；完成材料
构建和独立评审；完成转换、fidelity/semantic/determinism 审计；检查实际 Harbor task
目录和 `task_ready` 摘要；记录耗时和恢复证据。无需为此先运行下游写作 Agent。
