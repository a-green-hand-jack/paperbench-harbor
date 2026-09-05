# PaperSmith 制题流程

PaperSmith 是制题系统，不是参试写作 Agent，也不是完整的论文质量裁判。
所有新请求复用 `construction/core`、领域插件、统一 runner、转换器及 fidelity
审计。旧 corpus 和 adapter 的研究类型保留原有读取契约，不自动获得新门禁认证。

## 输入与权限

自然语言入口为 `.opencode/agent/papersmith-{lifesci,physics,chemistry,mathematics}.md`。
修改入口后须退出并重新启动 OpenCode；当前会话不热加载配置。
例如：`opencode run --agent papersmith-physics "制作一个数值模拟写作重构任务，不上传也不发布"`。

入口必须先展示完整的结构化解析结果。安全默认值是目标 1、写作重构、充分公开
证据、串行、最多 3 次构建、单阶段 5400 秒、试写 1800 秒、不上传、不发布。
目标数量指通过全部交付门禁的数量，不是候选数。独立核验使用
`--minimum-approved <N>`；20 是另一个跨领域发布门槛，不限制单篇本地请求。

```bash
uv run scripts/run_paperrecon_domain.py --domain physics \
  --run-root /authorized/papersmith-run \
  --request-json '{"domain":"physics","research_type":"simulation","target_count":1,"delivery_root":"/authorized/papersmith-run","upload_candidate":false,"publish":false}' \
  --describe-request
```

删除 `--describe-request` 才开始发现。runner 输出并保存 `request.json`。JSON 也支持
`topic`、`source_ids`、`source_scope`、`capability`、`difficulty`、`material_policy`、
`timeout_seconds`、`max_turns`、`concurrency`、`trial_timeout_seconds`。未知字段拒绝。
构建时重复使用相同 JSON；命令行的 domain 和 run-root 必须与之相符。

运行根目录必须由操作者在获准位置提供，且不能位于 Git 工作树内。入口不会
越权创建外部工作区、读取凭证或手写批准文件。任何权限拒绝都必须报告为阻塞。
`--auto` 和独立工作目录不是 OS sandbox；不可信构建使用
[Docker 制题环境](papersmith-docker.md)，源码只读挂载，产物写入独立 volume。

## 核验到交付

```bash
uv run scripts/verify_paperrecon_candidates.py --domain physics \
  --candidates /authorized/papersmith-run/candidates.json \
  --run-root /authorized/verification-run --minimum-approved 1

uv run scripts/run_paperrecon_domain.py --domain physics \
  --run-root /authorized/papersmith-run --target-count 1 --research-type simulation \
  --candidates /authorized/papersmith-run/candidates.json \
  --agent-approval /authorized/verification-run/agent-approval.json \
  --promote --build --convert --audit --stage-candidate \
  --trial-model openai/gpt-5.5 --trial-agent codex --trial-agent-version <installed-version>
```

批准与候选文件 SHA 绑定。LifeSci 旧 promotion CLI 也接受 `--agent-approval`，但不能
同时指定 `--human-approval`。新的自然语言流程使用统一 runner，避免重复维护入口。
凭证由已配置的 Harbor/provider 注入，禁止放入请求、任务、命令行或报告。

核心先提取 `original/research_evidence.json`，检查来源与研究类型，再生成 overview
和资源。每个关键事实有原始来源位置、SHA 和公开支持位置；每个结论有支撑事实
ID 和限制。缺失或排除资产须说明原因，必要资产缺失不能通过。公开
`resources/writing_requirements.json` 与私有评价依据同步，不能要求参试者猜隐藏事实。
完整原文复制、私有文件名/路径和符号链接有确定性门禁；科学术语与公式共享本身
不是泄漏。语义泄漏及事实充分性仍需独立材料评审。

## 知识包

`construction/core/knowledge.py` 的版本化接口包含选题政策、schema、材料契约、
执行检查、评审提示、正反例及规范出处。当前支持如下组合，其他组合显式拒绝：

| 学科 | 研究类型 | 实际检查 |
|---|---|---|
| lifesci | experimental | 样本、分组、对照、重复、统计、效应与不确定性；区分重复类型、因果与研究设计 |
| physics | simulation | 系统、方程、单位、边界、参数、近似、收敛和误差；不同细化级别、正容差和有限误差 |
| chemistry | synthesis_characterization | 分子、条件、产率、纯度、表征与方法；百分比范围与表征身份一致 |
| mathematics | theorem_proof | 定义、假设、量词、引理、证明概要和边界；依赖完整且无环、禁止隐式证明发现 |

证明发现与写作重构是不同能力，目前 `proof_discovery` 明确拒绝。新知识包须引用
来源、添加相应正反测试、人工代码评审及提升版本，不能让模型自述覆盖稳定规则。
每次构建保存所用包和版本。结构检查不能替代专家判断。

## 评审与恢复

独立 reviewer 接收完整公开和私有材料副本，包含图片、表格、补充资产及来源映射。
新任务评审缺陷分类为 structure、scientific_fact、material_insufficiency、leakage、
eligibility；每项必须有严重性、来源证据和修复要求。未能检查必要图片时不能猜测。
评审后重新比较输入哈希，阻止使用被修改材料的通过记录。

`build/<paper-id>/stages.json` 原子记录 evidence/build/validate/review/delivery 阶段、
配置、哈希、错误和报告。`--resume` 仅复用配置和输入输出仍一致的通过结果；
`--rerun-stage evidence|build|validate|review` 从指定阶段重新执行并重跑下游门禁。
上游材料、来源、实现或知识包变更使旧结果失效。失败修复复用现有 retry loop。
试写保存在 `trials/<task-id>/<attempt>/`，不会覆盖旧轨迹。

Harbor 试写使用 Docker writer environment，仅含公开材料；不挂载源 corpus。
它记录模型、Agent 版本、任务哈希、知识包、命令、预算、轨迹和 verifier 结果。
环境异常、材料缺陷和无法区分的模型/任务失败分别报告。reward=1 只代表交付与
编译契约，科学质量另列 `not_evaluated`；单次成功不独立证明材料充分。
fidelity、semantic review 和固定 corpus 转换 determinism 仍是独立门禁，
不要求 LLM 两次构建字节一致。

## 发布与结果

`run-summary.json` 列出 target_count、approved_count、failed_count、blocked_count、
unfinished_count，以及任务、私有证据、审计、知识包和试写记录。未完成不报告成功。
本地 source archive 不等于远端候选。`publish_paperrecon_release.py` 默认只验证并
写本地 evidence；`--upload-candidate` 才授权上传，`--publish` 还需显式上传意图。
发布门禁核对实际任务/归档/审计哈希及对应 trial 结果，标签固定到实际远端 SHA。
仅“不发布”绝不隐含上传。跨领域门槛仍为每个新领域至少 20 个通过任务。

重建已发布 LifeSci selection 必须传 `--dataset-revision <40-hex-commit>` 给
`run_lifesci_paperrecon_release_candidate.py`；此值与 converter Git revision 分开记录。

Live 完成状态以 `docs/issue-70-todo.md` 的验证记录为准；未执行的领域 live 验收
不能由单元测试或 hello-world smoke 替代。任何材料质量评审都不是完整论文质量 judge。
