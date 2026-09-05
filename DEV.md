# PaperSmith 开发指南

本指南面向维护者，在 Ubuntu 上用 Docker 运行当前 checkout 的 PaperSmith
构造程序。完整隔离与认证说明见 [Docker 文档](docs/papersmith-docker.md)，
请求、审核与发布契约见 [工作流](docs/papersmith-workflow.md)。

## 启动与实时源码

从仓库根目录以普通用户运行，不用 sudo：

```sh
sh scripts/papersmith-docker.sh build
sh scripts/papersmith-docker.sh run --help
sh scripts/papersmith-docker.sh exec python scripts/verify_paperrecon_candidates.py --help
PAPERSMITH_NETWORK=none sh scripts/papersmith-docker.sh run \
  --domain physics --research-type simulation \
  --run-root /runs/physics-01 --target-count 1 --describe-request
```

`--describe-request` 只验证并展示请求，不构造任务、不调用模型。
`run` 调用 `scripts/run_paperrecon_domain.py`，`exec` 执行给定命令，
`shell` 进入交互 shell。镜像包含 OpenCode、Codex、Python 依赖和 TeX 工具。

- 源码在宿主原绝对路径只读 bind mount；宿主改动后，下一个 Python 进程即使用新代码。
  已导入模块和运行中的 agent 不会热重载，需重启进程；依赖或 Dockerfile 变化才需重建。
- `/runs` 保存构造产物，`/state/home` 保存容器 HOME/会话，`/cache` 保存缓存，
  三者都是专用持久 volume；`/tmp` 是临时 tmpfs。退出和重建不会清空 volume。
- 默认 `PAPERSMITH_NETWORK=bridge` 允许联网，不是出口白名单；设为 `none` 可主动断网。
  不挂载宿主 HOME 或 Docker socket，不使用 host network；源码与镜像文件系统只读。
- 默认 volume 前缀按 checkout 路径和 UID 区分；独立实验可固定使用
  `PAPERSMITH_VOLUME_PREFIX`。同一组 volume 内的运行能互读写数据，不能当作相互隔离。

## 配置与认证

默认不导入宿主配置或凭据。`PAPERSMITH_HOST_CONFIG=1` 只读挂载宿主 OpenCode
配置、插件/依赖及 Codex 配置与 auth；OpenCode 账号文件等额外依赖必须通过
`PAPERSMITH_READONLY_PATHS` 明确列出，每行一个绝对路径，保持同路径挂载。
宿主配置模式下 `HOME` 字符串与宿主相同，但可写内容仍来自专用 state volume。
配置引用的外部依赖不会自动全部挂载；下一次 wrapper/CLI 调用加载最新挂载和配置。

配置权限和认证权限不同：配置可能执行插件，auth 挂载则允许容器程序使用该账号。
只读不等于凭据不可读取或不可外传，联网时尤其要限定账号和依赖范围。
只处理路径，不读取、打印、复制秘密，不运行 `opencode debug config`。
只读 auth 也可能无法保存刷新后的 token。单文件配置/auth 替代模式及限制见 Docker 文档。

2026-09-05 在 Ubuntu 容器内验证以下两条真实 CLI 调用成功，均为 `exit_code=0`、
`exact_response=true`、`diagnostic_categories=[]`。重新运行会发起模型请求：

```sh
PAPERSMITH_HOST_CONFIG=1 sh scripts/papersmith-docker.sh exec python scripts/probe_papersmith_clis.py codex --model gpt-6-astra --timeout 60 --output /runs/cli-probes/codex.json

PAPERSMITH_HOST_CONFIG=1 PAPERSMITH_READONLY_PATHS="$HOME/.config/opencode/account-auth/gpt-evelyn.auth.json" sh scripts/papersmith-docker.sh exec python scripts/probe_papersmith_clis.py opencode --model openai-evelyn/gpt-6-astra --timeout 60 --output /runs/cli-probes/opencode.json
```

这证明对应 CLI/账号的真实模型请求可用，不证明 physics 构造、材料审核或 writer trial 成功。

## 分阶段构造

以下是按当前 CLI 参数定义编写的执行命令，不是已成功运行的 physics 记录。
联网筛选、验证和构造会产生模型费用，需在已授权的运行中执行。

```sh
export PAPERSMITH_HOST_CONFIG=1
export PAPERSMITH_READONLY_PATHS="$HOME/.config/opencode/account-auth/gpt-evelyn.auth.json"
export BUILD_MODEL=openai-evelyn/gpt-5.6-terra

# 1. 发现与筛选，输出 /runs/physics-01/candidates.json。
sh scripts/papersmith-docker.sh run \
  --domain physics --research-type simulation --target-count 1 \
  --run-root /runs/physics-01 --model "$BUILD_MODEL"

# 2. 先设置真实可用的两个独立验证模型及材料审核模型。
# 按这些 provider 的需要扩展只读路径清单，不填入密钥值。
: "${VERIFIER_MODEL_A:?set an authorized verifier model}"
: "${VERIFIER_MODEL_B:?set a second independent verifier model}"
: "${REVIEWER_MODEL:?set an independent material reviewer model}"
sh scripts/papersmith-docker.sh exec python scripts/verify_paperrecon_candidates.py \
  --domain physics --candidates /runs/physics-01/candidates.json \
  --run-root /runs/physics-01/verifier --minimum-approved 1 \
  --screening-model "$BUILD_MODEL" \
  --verifier-model-a "$VERIFIER_MODEL_A" --verifier-model-b "$VERIFIER_MODEL_B"

# 3. 仅在精确候选 SHA 的双验证批准后继续本地构造与暂存。
sh scripts/papersmith-docker.sh run \
  --domain physics --research-type simulation --target-count 1 \
  --run-root /runs/physics-01 \
  --candidates /runs/physics-01/candidates.json \
  --agent-approval /runs/physics-01/verifier/agent-approval.json \
  --model "$BUILD_MODEL" --reviewer-model "$REVIEWER_MODEL" \
   --promote --build --convert --audit --stage-candidate --resume
```

两个验证模型必须彼此不同且不同于筛选模型；材料审核仍须满足独立性契约。
不能把换账号当作独立模型。外层 `opencode run --model ...` 不会替内部 runner
设置模型；构造用 `--model`，材料审核用 `--reviewer-model`，验证用上述两个参数。
Codex 探针成功也不意味着构造器从 OpenCode 自动改用 Codex。

目标数是完成制题的 Harbor 任务数，不是候选数。当前 runner 在候选批准、证据提取、
材料构造与绑定、结构/LaTeX 校验、独立材料评审、转换、fidelity/semantic/determinism
审计全部通过后报告 `construction_status: task_ready`；指定 `--stage-candidate` 时还须
完成 source archive。没有试写时顶层 `status: task_ready`、`trial_status: not_run`，退出码 0。
`task_ready_count` 和 `construction_unfinished_count` 统计制题，`trial_acceptance` 单独保存
试写验收计数；`approved_count` 仍只统计真实试写通过数，没有试写时为 0。

`task_ready` 不等于 tested/accepted delivery 或 release-ready。真实 Harbor writer trial
仍须在另行授权的执行环境中完成，并显式设置 `--trial-model`、`--trial-agent`、
`--trial-agent-version`。显式试写未通过时返回非零退出码，验收状态单独记录；发布器仍要求
`status: passed`、真实 trial 证据及原有发布门禁。此容器没有 Docker socket，不接入宿主
socket，也不启动宿主编排器。本地暂存不会自动上传或发布。

## 默认时限与恢复

构造 subprocess 默认 `timeout=None`，没有阶段时长上限：证据、构建、筛选、候选验证、
材料评审、conversion semantic review、fidelity 审计和 LaTeX 编译均不预设秒数。
runner 可显式传 `--timeout <正整数秒>`；结构化请求对应 `timeout_seconds`，默认 `null`。
它限制相应 subprocess 调用，不是整个任务的总预算。`audit_fidelity.py --timeout` 单独
限制 semantic reviewer。`--max-turns` 默认 3，控制修复尝试次数，不是时长限制。
低层 HTTP 连接/读取、单次文献检索请求、`opencode models` 的可用性检查仍可有限时，
不代表科学构造阶段预算。生成的下游 Harbor writer/verifier 预算及独立试写预算保持不变。

同一 volume、同一 `/runs/physics-01` 根目录，原样重跑上面的完整 runner 命令并带
`--resume`。不需要手动调用单个函数，也不需要重新执行候选筛选或改写已批准候选。

- `/runs/physics-01/build/<paper-id>/stages.json`：evidence、build、materials、validate、review、delivery。
- `/runs/physics-01/stages.json`：conversion、audit、archive；这是完整 runner 的 checkpoint 路径。
- `/runs/physics-01/dataset/physics-paperrecon-short/`：审计后的 Harbor 任务及 manifest。
- `/runs/physics-01/source-archive/`：仅在指定 `--stage-candidate` 时生成。
- `/runs/physics-01/run-summary.json`：制题状态、任务路径、审计 SHA 和独立的试写状态。

checkpoint JSON 原子替换，保存当前输入/输出哈希、attempt ID、错误、报告与历史。
schema_version=1 的结构与阶段记录须通过校验；未知版本或损坏记录报错，不静默丢弃。
`config` 保留首次记录的配置，`current_config` 表示本次调用，`config_history` 保存变化历史；
配置变化仍由各阶段输入哈希决定失效范围，不清空所有 checkpoint。转换、审计、归档
也绑定实际 runner helper 实现与对应有效选项，不只绑定库代码。
只有 `passed` 且当前输入和输出匹配的节点可复用；中断留下的 `running` 节点会重试。
调整 timeout、重试次数或并发不会使科学结果失效；换材料 reviewer 只重跑评审及受影响
的下游，不重提取证据或构建材料。`--conversion-reviewer-model` 只选择转换语义评审模型，
其默认值由 `CONVERSION_REVIEWER_MODEL` 或代码默认模型解析。

基础设施阻塞的评审恢复时只重试评审；明确拒绝的评审保留具体缺陷，恢复时交给构建器
修复材料，再校验和独立评审。构建或修复进程失败不能因旧材料可编译而获得通过。
公开绑定 SHA、构造元数据与评审记录不参与原始证据哈希；真实源文件、相关实现和模板
字节变动会使受影响节点失效。旧版粗粒度 checkpoint 不会被自动追认为新门禁通过。
日志使用唯一文件名，LaTeX/评审目录按尝试隔离，失败审计与旧转换/归档目录保留。

需要主动重跑时，完整命令保留 `--resume` 并加
`--rerun-stage evidence|build|materials|validate|review|conversion|audit|archive` 中的一个值。
指定节点及下游会重跑；上游仍须有有效 checkpoint。一个 run-root 只由一个 runner 写入，
不要并行恢复同一个根目录。以上描述是当前实现和 CLI 契约，不是 live physics 成功记录。

显式启用下游 trial 时，`trials/<task-id>/stages.json` 保存独立 checkpoint。
`--resume` 只复用 `verify_trial_evidence` 重新验证通过的成功试写，并核对任务、材料评审、
模型/Agent 版本、知识包、结果与轨迹哈希；缺失、失败或篡改的记录不会获得试写验收。
未指定 trial 参数时仍不启动试写，也不影响 `task_ready`。

## Dirty 本地开发与发布

允许直接修改宿主源码并从只读 bind mount 运行，不要求先 commit。新进程记录
`implementation.base_commit`、`implementation.implementation_sha256`、`implementation.dirty`
以及 digest 范围；这些信息进入 execution、构造 checkpoint/交付结果、run summary、
fidelity evidence 和 archive metadata/registry。dirty 转换使用
`local:<base-commit>:<implementation-sha256>` revision，明确不是仅凭 HEAD 可复现的不可变提交。
digest 只读取限定源码/模板/依赖声明路径，排除凭据、auth、日志和运行产物；未跟踪文件仅
纳入该范围内的 `.py`、`.sh`、`.j2` 源码，不读取未跟踪 auth JSON。

本地 dirty 输出可达到 `task_ready`，但发布门禁拒绝 dirty、缺失或不一致的实现 provenance。
正式发布须在显式固定的 clean revision 上重新生成匹配证据；提交代码本身不会把旧 dirty
结果追认为 clean。已运行的 Python/agent 进程不热重载本次修改；不要为了加载修复而停止
正在执行的实验，由负责该实验的操作者决定后续新进程何时启动。

## 文档检查

```sh
sh scripts/papersmith-docker.sh exec python scripts/check_documentation_references.py
sh scripts/papersmith-docker.sh exec ruff check .
```

此检查覆盖必需的数据集引用和 `docs/*.md` 清单，不是构造验收。
根目录 `tests/` 已退役；本开发流程不运行 pytest 或 Hello World。

## 本轮物理验证记录

2026-09-05，基于提交 `a4f37bc`，在容器中复用论文
`2608.24682v1`（Chebyshev interpolation in Einstein-Boltzmann codes）的既有
材料，分别调用原生构建和独立评审接口，各执行一轮、限时 60 秒，没有连续重试。

| 项目 | 结果 |
| --- | --- |
| 既有研究证据、结构与材料检查 | 通过 |
| 模板与原论文 LaTeX 编译 | 均通过 |
| OpenCode 构建模型 `openai-evelyn/gpt-6-astra` | 超时，退出码 124 |
| 独立评审模型 `openai-jieke/gpt-5.6-terra` | 超时，退出码 124，无有效 verdict |
| 本轮制题验收 | 未通过；未执行下游 trial、上传或发布 |

这是一轮有界诊断，不是从筛选到交付的完整验收。仅
`resources/writing_requirements.json` 发生变化，没有完成新的材料构建。
诊断将集成评审关闭后单独运行独立评审，因此构建函数返回的 `status: ok`
只表示既有材料通过结构检查；必须同时读取构建阶段失败和独立评审阻塞记录，
不能把该状态作为 accepted task。

产物保存在 volume `papersmith-physics-docker-01-runs`：

```sh
PAPERSMITH_VOLUME_PREFIX=papersmith-physics-docker-01 \
sh scripts/papersmith-docker.sh exec python -m json.tool \
  /runs/physics-docker-01/bounded-summary.json
```

同目录下的 `execution.json` 保存调用参数，`build-result.json`、
`review-result.json`、`construction-evidence.json` 和
`build/paper_1/stages.json` 保存分阶段证据。`logs/` 保留原始调用日志，
不要直接公开或无筛选地打印。验证结束后没有遗留此轮容器进程。
