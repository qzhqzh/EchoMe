# EchoMe v1.5 规划：可信记忆运行时与学习闭环

状态日期：2026-08-13。

## 0. 实施进度与验收快照

v1.5.0 已完成实现与发布前验收；生产部署按 `012 -> 015` 的 expand-only 迁移执行。

| 范围 | 状态 | 当前结果 |
|---|---|---|
| 013 Project aliases | 已实现并验收 | canonical/alias 精确解析、用户隔离、历史 scope 只读展开；AI 创建别名只能进入 `proposed` |
| 014 Context runtime | 已实现并验收 | `POST /api/v1/context`、runtime health、request/client/route/fallback/error 元数据、MCP `core/full` profile 和 AES-GCM + TTL last-known-good 只读降级；personal route 当前为 bounded lexical，图/时间扩展待后续评估 |
| Context Runs Web | 已实现并构建 | Logs 菜单可切换 Retrieval / Context Runs，并查看选入数量、trace、fallback、error 与客户端信息 |
| 015 Context outcomes | 基础链路已实现并验收 | append-only 单条/批量 API、幂等提交、completed/non-shadow 前置条件、MCP outcome 工具；暂不影响生产排序 |
| 016 Reliability assessment | 延后 | 按 v1.5.1 单独推进，不与本轮生产迁移捆绑 |
| Scale / replay eval | 后续增强 | 10x 抗噪、真实日志回放和多客户端矩阵继续作为 v1.5.x 质量门禁扩展 |

本轮自动化验收结果：

- Hub：`96 passed, 1 skipped`；根 MCP/CLI：`21 passed`；两处 Ruff 均通过。
- Web：`vue-tsc --noEmit` 与 Vite production build 通过。
- Wheel 构建和 Python 3.13 隔离源码外 smoke 通过；`echome_context`、runtime health 与 context outcome 均出现在安装后的 29 个 tools 中。Python 3.11/3.12 的独立安装矩阵仍属于发布前 CI 门禁。
- 生产数据的隔离副本完成 `012 -> 015 -> 012 -> 015`；最终 revision 为 `015`。
- 迁移前后 461 条 Memory、28 个 Project、174 个 Artifact、11 个 Constraint、6 个 Event 的行数和逐行内容哈希完全一致。
- 013-015 使用 expand-only compatibility downgrade：回退 revision 与旧代码时保留新增表、列和证据；再次 upgrade 幂等复用，避免 alias、personal run 或 outcome 在回滚中丢失。
- 验收过程中主动写入的 alias、`project_id=NULL` personal ContextRun 和 outcome 在 compatibility downgrade 与再升级后均完整保留。
- 临时数据库与 dump 已清理；生产数据库仍为 Alembic `012`，运行中服务未重启。

## 1. 版本判断

EchoMe v1.4 已经完成从“个人记忆库”到“Memory + Project Knowledge”的关键跨越：系统能够保存原始记忆、项目制品、版本化约束和项目事件，并通过 Context Compiler 向 AI 返回带证据、时间信息、冲突和 token budget 的上下文。

v1.5 不应继续横向增加大量记忆类型或替换存储引擎。下一阶段的核心目标是：

> **让 AI 只需一个稳定入口就能获得正确上下文，并能证明这些记忆是否真正改善了任务结果。**

版本主题定义为 **Reliable Recall and Controlled Learning**：先解决运行可靠性、项目身份、工具选择和真实评估，再让反馈、时间复核和 Sleep 进入受控学习闭环。

## 2. v1.4 之后的真实缺口

### 2.1 MCP 已有能力多，但模型选择成本开始上升

- MCP 已暴露 26 个 tools，并通过 capability tool、prompt 和 resource 做能力发现。
- Memory Search、Memory Graph、Project Context、Impact 和 Preflight 的边界对开发者清楚，但不同客户端和模型不一定总能稳定选择正确工具。
- 下一版应提供一个默认的 `echome_context` 入口；现有细粒度工具继续兼容并保留给高级调用。

### 2.2 运行错误缺少可诊断契约

- MCP 当前可能把底层异常压缩成 `EchoMe error: {message}`；异常消息为空时，客户端只能看到空错误。
- Hub client 没有统一的 request id、错误码、retryable 标记、降级状态和建议动作。
- 文档描述了 Hub 不可达时读取本地 vault，但当前 Hub client 主路径尚未形成可验证的 read-only fallback。
- `echome_capabilities` 描述静态能力，但不报告 MCP 包版本、Hub 版本、Alembic revision、feature flags 和兼容性。

### 2.3 项目身份可能分裂上下文

当前实例中同时存在 `EchoMe` 和 `qzhqzh/EchoMe` 等不同项目标识。项目名、Git remote、目录路径和历史 ID 可能指向同一项目，但查询与写入仍可能落入不同 scope。

v1.5 必须先解决项目身份解析，但不直接合并或删除历史项目：

- 增加 canonical project 与 alias 映射。
- 查询时展开别名，写入时落到 canonical project。
- 历史数据重关联必须走 proposal、预览、幂等 apply；默认不移动任何记录。

### 2.4 已有反馈还没有闭合到任务结果

- `memory_feedback` 能记录 helpful、outdated、conflicting 等信号。
- `context_runs` 能记录检索过程。
- `project_events` 能记录测试、失败、修复和部署。
- 这些数据尚未通过同一个 `context_run_id` 形成“给了哪些上下文 -> AI 做了什么 -> 结果如何”的可审计链路。

### 2.5 评估仍偏固定样例

26 条 Project Context 案例建立了很好的发布基线，但还需要补充：

- 真实检索日志回放。
- 随记忆规模增长的抗噪能力。
- 不同 AI 客户端的工具发现和调用路径。
- 相同模型、embedding、token budget 下的单变量对照。
- 任务成功、拒答正确性和约束遵循，而不仅是 UUID 命中。

## 3. 外部机制的取舍

### Hindsight：Recall 与 Reflect 分离

Hindsight 将 retain、recall、reflect 分成不同成本层，并使用 semantic、keyword、graph、temporal 多路召回后融合。EchoMe 已具备类似检索基础，值得借鉴的是 **把低成本上下文获取与高成本整理/反思明确分开**，而不是引入另一套存储。

### Graphiti：时态事实与 episode 来源

Graphiti 为事实维护有效时间窗口，并让派生事实回溯到原始 episode。EchoMe 已有 Memory、Artifact revision、Constraint version 和 Event，因此应继续强化来源、有效期和失效原因，不需要迁移到 Neo4j/FalkorDB。

### Letta：常驻 block 与 Sleep Agent

Letta 的 memory block 说明了少量高价值上下文常驻的价值，Sleep Agent 则说明整理可与主 Agent 分离。EchoMe 继续保留 L0/L1 常驻层和客户端强 AI 生成 Sleep 预案，但服务端只负责校验、模拟和执行已确认方案。

### 2026 评估趋势

- LongMemEval-V2 开始评估 static state、dynamic state、workflow、environment gotchas 和 premise awareness。
- LoCoMo-Plus 强调隐含约束是否被一致执行，而不只是事实回忆。
- scale-conditioned evaluation 关注无关历史增长后，记忆是否仍能在调用次数和 token budget 内被有效使用。
- 这些方向与 EchoMe 的 Project Event、Preflight、Constraint 和 Context Compiler 高度一致，应直接转成项目自己的发布门禁。

## 4. v1.5 目标架构

```text
Codex / Claude / Cursor / other MCP clients
                    |
                    v
          echome_context (single entry)
                    |
        +-----------+-----------+
        |                       |
        v                       v
Personal memory route      Project route
summary + graph + time     preflight + compiler + impact
        |                       |
        +-----------+-----------+
                    v
        Evidence-first context pack
        + answerability / conflicts
        + request_id / context_run_id
        + runtime and fallback metadata
                    |
                    v
       context outcome / explicit feedback
                    |
                    v
    Append-only signals and derived utility views
                    |
         shadow evaluation before ranking use
```

保持不变：

- Memory 与 Project Knowledge 不合并表。
- 原始 Memory、Artifact revision、Constraint version、Event 和关系边不被静默覆盖或删除。
- Sleep、项目重关联和约束复核继续使用 proposal -> validate -> apply。
- 反馈和使用结果先作为 append-only 信号，不直接改变状态或生产排序。
- PostgreSQL + pgvector 继续作为唯一权威数据层。

## 5. 分版本实施

### v1.5.0：Reliable Context Runtime

这是下一版的必须交付范围。

#### A. 项目身份解析

新增可选表 `project_aliases`：

- `canonical_project_id`
- `alias_type`: `legacy_id | name | git_remote | path | client_hint`
- `alias_value_normalized`
- `status`: `proposed | active | rejected | archived`
- `source`、`confidence`、`created_at`

行为：

1. 根据显式 project id、Git remote 和当前目录识别 canonical project。
2. 查询时可以跨 active alias 读取历史 scope。
3. 写入默认使用 canonical project。
4. 历史记录不自动搬迁；后续如需统一，生成可审核的 relink proposal。

#### B. 统一 MCP 入口

新增 `echome_context`，输入保持简单：

```json
{
  "task": "修改登录接口并准备测试",
  "project_hint": "当前目录、project id 或 git remote，可选",
  "changed_paths": ["hub/app/api/auth.py"],
  "mode": "auto",
  "token_budget": 6000
}
```

服务端负责：

- 解析项目身份。
- 判断 personal / project / impact / temporal 路由。
- 项目任务自动组合只读 preflight 与 Context Compiler。
- 低置信度时有界扩展图邻居或 summary 候选，不允许无限检索（尚未进入本轮候选；personal 当前仅 bounded lexical）。
- 返回 conflicts、unknowns、answerability 和 recommended actions。

兼容策略：

- 现有 26 个 tools 不删除、不改名。
- `echome_search_summary`、`echome_project_context`、`echome_project_impact` 等继续作为高级接口。
- MCP 增加 `core` 与 `full` profile。`core` 只暴露 capabilities、context、remember、outcome/feedback；`full` 保持当前完整能力。
- 默认 profile 的切换先在客户端配置中 opt-in，经过兼容测试后再决定是否改默认值。

#### C. 运行契约与降级

所有 MCP/Hub 错误返回统一结构：

```json
{
  "error": {
    "code": "HUB_UNAVAILABLE",
    "message": "EchoMe Hub is unreachable",
    "retryable": true,
    "request_id": "...",
    "degraded": true,
    "suggested_action": "Use cached read-only context or run echome doctor"
  }
}
```

同时完成：

- `echome_capabilities` 返回 MCP/Hub/schema 版本、feature flags、profile 和兼容性。
- 新增 runtime health/doctor API，验证 token、Hub、数据库、embedding、迁移版本和缓存。
- 为只读查询保存加密配置边界内的 last-known-good context cache。
- Hub 不可达时只允许读取缓存；remember、feedback、Sleep apply 等写操作明确失败，绝不离线伪成功。
- Context Run 记录 client、版本、request id、route、fallback 和 error code。

当前限制：Hub 完全不可达时，MCP 返回值会携带本地 fallback/error metadata，但无法同步写入 Hub 的
Context Runs；恢复后的 telemetry 补交不在本轮实现范围。Hub 可达时的编译失败使用独立审计事务记录，
并在项目已解析后保留 canonical `project_id`。

#### D. Eval 与观测基础

- Web Logs 增加 Context Runs 视图：显示路由、选入/排除原因、降级、错误码和 request id。
- 建立 Codex、Claude、Cursor 的工具发现契约测试；不要求每个客户端支持 prompt/resource，但 tools 路径必须工作。
- 从真实 retrieval logs 选择可匿名化样例生成 eval proposal，由人确认 expected evidence 后进入固定集。
- 增加 10x 无关记忆注入的 scale test，检查可靠性和调用预算。

### v1.5.1：Outcome Learning and Temporal Reliability

#### A. Context outcome

新增 append-only `context_outcomes`：

- 关联 `context_run_id`。
- 记录 `success | partial | failed | corrected | no_signal`。
- 可关联 project event、测试结果、用户纠正和使用过的 memory/constraint/evidence IDs。
- 支持客户端批量、幂等提交；未提交 outcome 不推断为失败。

新增派生 `memory_utility_views`：

- helpful / harmful / corrected / unused 计数。
- 样本量、置信区间、最近证据和按任务类型分层结果。
- 第一阶段只显示和 shadow rerank，不影响生产排序。

反馈交互原则：

- 不在每次记忆使用后打断用户。
- 只在用户纠正、任务高影响、检索低置信度或结果明显依赖关键记忆时请求反馈。
- 测试通过、部署成功等机器证据可以作为 outcome，但不能替代用户对偏好类记忆的判断。

#### B. 时间可靠性

为记忆和约束生成可重建的 reliability assessment：

- `invariant`: 安全红线、长期身份事实等稳定信息。
- `durable`: 长期有效但允许明确替代的规范。
- `environment_bound`: 依赖项目、版本、部署或外部环境。
- `volatile`: 价格、接口状态、短期计划等高变化信息。
- `episodic`: 一次事件，只作为历史证据。
- `unknown`: 尚无足够依据。

复核触发使用证据而不是单纯年龄：

- 来源 artifact revision 变化。
- 新记忆或事件形成显式冲突。
- 依赖的软件版本、部署或项目状态变化。
- 曾成功的流程在相同前提下失败。
- 明确 valid_to/expiry 到期。

长期未访问只表示项目可能 dormant，不表示记忆错误。项目状态为 dormant 时冻结普通年龄提醒；项目重新活跃后，再根据来源水位和环境变化生成复核 proposal。

### v1.5.2：Sleep Simulation and Safe Reflection

增强现有 JSON Sleep 预案，不改变 apply 的确认边界。

每个预案增加：

- 模型、prompt 版本和 schema 版本。
- source coverage、保留/归档/新增数量和 token reduction。
- 冲突、时间限定、核心记忆和孤立来源检查。
- 每条 derived memory 到全部来源的 `derived_from` 边。
- 归档来源到新记忆的 `superseded_by` 边。
- before/after 查询回放结果和质量差异。

Sleep apply 前必须通过：

1. JSON Schema 与项目/用户权限校验。
2. 全部来源版本和状态前置条件校验。
3. 来源覆盖与关系完整性校验。
4. 相关 eval 查询的 before/after simulation。
5. 无法证明无回归时只允许保留 proposal，不允许 apply。

定期任务仍只生成 proposal。MCP Tasks 扩展目前仍在演进，v1.5 可以先使用 Hub job + polling；等客户端兼容成熟后再暴露标准 MCP task。

## 6. 数据迁移与兼容策略

建议迁移保持 additive：

- `013_project_aliases`
- `014_context_runtime_contract`
- `015_context_outcomes`
- `016_memory_reliability_assessments`
- Sleep proposal 的模拟结果优先写入现有 JSON metadata；只有查询需求证明必要时再独立建表。

约束：

1. 新字段 nullable，旧客户端和旧记录继续可读。
2. project alias 初始只生成 proposal，不改历史外键。
3. context outcome 是 append-only 原始反馈证据，不可静默删除或重建；utility view 和 reliability assessment 才是可重建派生数据。
4. 新路由先 shadow，与 v1.4 路由 dual-read；production switch 使用 feature flag。
5. 每个迁移在生产备份副本执行 upgrade -> compatibility rollback -> upgrade，并比较权威表行数与内容哈希；compatibility rollback 不删除新增数据结构。

## 7. 发布门禁

### 正确性

- v1.4 固定集指标不得回退超过 2 个百分点；stale answer rate 保持 0%。
- 项目 alias 查询必须覆盖历史 scope，且不能产生跨用户/跨项目串读。
- 错误前提和无证据问题的正确拒答率 >= 95%。
- Sleep simulation 的 source coverage 必须为 100%。

### 可靠性

- 所有 MCP 错误都有非空 code、message 和 request id。
- Hub 故障时，已有缓存的只读 context 能明确降级返回；写操作 100% fail closed。
- 在 10x 无关记忆增长下，budget-compliant reliability 相对下降不超过 5 个百分点。
- `echome_context` 默认流程最多一次初始调用；只有低置信度或冲突时建议后续精读。

### 兼容性

- Codex、Claude、Cursor 至少通过 tools-only 合约测试。
- v1.4 MCP 工具和 REST API 保持可用。
- PyPI wheel 在 Python 3.11、3.12、3.13 做隔离安装 smoke。

### 可观测性

- 100% Context Runs 能关联 route、selection reasons、token budget 和 runtime status。
- outcome 只计算有明确信号的运行，不把缺失反馈当作负面反馈。
- 候选排序变更必须先提供 shadow 对比和真实回放报告。

## 8. 推荐执行顺序

| 优先级 | 工作 | 原因 |
|---|---|---|
| P0 | 修复版本/健康/错误契约和本地安装一致性 | 没有稳定运行时，后续质量数据不可信 |
| P0 | canonical project + aliases | 当前项目身份分裂会直接漏掉正确记忆 |
| P1 | `echome_context` 与 core/full profile | 降低 AI 工具选择负担，直接改善跨客户端使用 |
| P1 | 真实日志回放与 scale eval | 防止只在固定小样例上变好 |
| P1 | context outcome append-only 链路 | 建立“记忆是否有用”的证据基础 |
| P2 | reliability assessment 与 dormant project | 区分稳定事实、环境事实和搁置项目 |
| P2 | Sleep before/after simulation | 让整理从 schema 安全提升到语义安全 |
| P3 | outcome 驱动的 shadow rerank | 必须在样本量和评估足够后启用 |

## 9. 本版本明确不做

- 不迁移到 Mem0、Hindsight、Graphiti、Letta 或独立图数据库。
- 不把外部 LLM 设为 Hub 检索和基础查询的强依赖。
- 不根据最后访问时间自动降权、废弃或归档记忆。
- 不让 outcome、feedback 或模型评分直接修改 active memory/constraint。
- 不静默合并重复项目或批量搬迁历史外键。
- 不一次接入 GitHub、Notion、Google Drive 等全部文档源；连接器留到 context runtime 稳定后。
- 不把 preflight 变成自动阻断代码操作的黑盒审批器。
- 不在 v1.5 核心路径依赖仍处于演进期的 MCP Tasks 扩展。

## 10. 后续空间

v1.5 稳定后，v1.6 可以自然扩展到：

- GitHub Issue/PR/Release、ADR 和测试报告的 source adapters。
- 面向项目中心的约束变更工作区：修改一个约束，生成受影响制品、测试和 Issue 的局部图。
- 团队共享 memory block 与 per-client/per-agent 读写权限。
- 可选的 server-side Reflect provider，但结果始终进入 derived proposal。
- 经过真实规模证明 PostgreSQL 图查询不足后，再评估专用图后端。

## 11. 参考资料

- [Hindsight](https://github.com/vectorize-io/hindsight)
- [Graphiti](https://github.com/getzep/graphiti)
- [Mem0 Graph Memory](https://docs.mem0.ai/open-source/features/graph-memory)
- [Letta Memory Blocks](https://docs.letta.com/guides/core-concepts/memory/memory-blocks)
- [Letta Sleep-time Compute](https://www.letta.com/blog/sleep-time-compute/)
- [LongMemEval-V2](https://xiaowu0162.github.io/longmemeval-v2/)
- [LoCoMo-Plus](https://aclanthology.org/2026.acl-long.1150.pdf)
- [MCP structured tool output](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [MCP Tasks Extension](https://tasks.extensions.modelcontextprotocol.io/seps/2663-tasks-extension)
