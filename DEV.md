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
export BUILD_MODEL=openai-evelyn/gpt-6-astra

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
  --promote --build --convert --audit --stage-candidate
```

两个验证模型必须彼此不同且不同于筛选模型；材料审核仍须满足独立性契约。
不能把换账号当作独立模型。外层 `opencode run --model ...` 不会替内部 runner
设置模型；构造用 `--model`，材料审核用 `--reviewer-model`，验证用上述两个参数。
Codex 探针成功也不意味着构造器从 OpenCode 自动改用 Codex。

目标数是通过验收的任务数，不是候选数。上述本地阶段没有指定 `--trial-model`，
不能宣称完整 accepted delivery；真实 Harbor writer trial 仍须在另行授权的执行环境中完成，
并显式设置 `--trial-model`、`--trial-agent` 等参数。此容器没有 Docker socket，
不能为通过验收而接入宿主 socket 或跳过 trial 门禁。本地暂存不会自动上传或发布。

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
