# EchoMe v1.7 计划：Trusted Context Calibration

状态日期：2026-08-24。当前处于 release candidate 最终验收阶段；生产数据库仍为 `015`，
尚未执行迁移、部署、合并或 PyPI 发布。

## 1. 版本判断

v1.6 Trusted Context Policy 已在工作区完成，但从未提交、迁移或公开发布。v1.7 将这批已验收能力作为
基线，再补齐策略效果校准闭环后一次发布，避免制造一个只有过渡意义的 v1.6 生产版本。

v1.7 的目标不是让策略更激进，而是回答一个更严格的问题：

> shadow policy 是否已有足够、明确、低风险的真实证据，可以进入一个单独批准且可回退的小流量 canary？

## 2. 外部方案带来的取舍

- [LangGraph Memory](https://docs.langchain.com/oss/python/concepts/memory) 区分 semantic、episodic、
  procedural memory，并把 hot-path 写入与 background consolidation 作为不同策略。EchoMe 继续保持
  Memory、Project Event/Outcome 和规则/约束的职责分离。
- [Mem0](https://arxiv.org/abs/2504.19413) 强调抽取、归纳、检索和 graph memory 的组合收益；
  EchoMe 已有 Sleep、typed edge 和混合检索，当前瓶颈是上线前证据，而不是再换一套存储。
- [Zep/Graphiti](https://arxiv.org/abs/2501.13956) 证明时间关系对跨会话检索重要；EchoMe 继续保留
  valid-time、supersession、historical 和 dormant scope，不用“很久没访问”直接判错。
- [Letta Memory Blocks](https://docs.letta.com/tutorials/attaching-detaching-blocks/) 展示了按 agent 动态挂载
  共享上下文的价值；EchoMe 通过 scope、project alias、context budget 和 MCP profile 保持类似边界，
  暂不引入新的 block 存储模型。

因此 v1.7 选择“校准现有策略”，不迁移 Mem0/Graphiti/Letta，也不增加另一套权威数据源。

## 3. 交付范围

### 3.1 v1.6 基线纳入 v1.7

- additive `016` reliability assessments；源 Memory/Constraint 不增加可被静默改写的真相字段。
- `off / shadow / enforce` Context Policy；默认 shadow，enforce 仍需服务端显式开关。
- 真实 Retrieval Log replay、scale-conditioned eval、Sleep v2 simulation 与 apply 前重算。
- Web reliability/intervention trace，MCP capabilities v4 基线。

### 3.2 显式 Policy Effect

`ContextOutcome` 新增可空字段：

```text
policy_effect = helpful | neutral | harmful | uncertain | null
```

- 字段是 append-only outcome evidence，不修改原记忆、约束、关系边或 Context Run。
- 只有包含 policy trace 且未关闭策略的 completed、non-shadow run 可以提交。
- `harmful` 必须附 note；同一 run 出现 helpful 与 harmful 时，门禁按冲突处理。
- 未提交或 `uncertain` 不进入正负样本分母，不能被推断为失败。

### 3.3 Readiness Gate

```text
GET /api/v1/observability/context-policy/readiness
```

门禁只读取指定时间窗口内 effective shadow runs 与显式 outcomes，报告：

- shadow、outcome、evaluated intervention 和 intervention 样本数；
- intervention evaluation coverage、helpful rate、harmful rate；普通 inject feedback 不进入门禁分母；
- would-exclude 数量、冲突信号和 source mutation 违规；
- `insufficient_data / hold / eligible_for_canary`。

默认阈值：20 个 shadow runs、10 个 evaluated intervention runs、10 个 intervention runs、
50% intervention evaluation coverage、
helpful rate 至少 20%、harmful rate 至多 5%，且不能有 effect 冲突或 source mutation。

查询使用有界最近窗口；若命中数量超过 `max_runs`，报告 `evidence_truncated=true` 并进入 hold，
不能用缩小样本窗口绕过历史负面证据。

只有字段完整的 v1 shadow policy trace 才进入样本分母；畸形 trace 会被剔除、单独计数并强制 hold。
outcome 查询只投影门禁字段并按 `(run, outcome, policy_effect)` 去重，避免重复幂等信号放大读取结果。
所有阈值使用未舍入比例判断，四舍五入只用于响应展示。

`eligible_for_canary` 固定伴随 `auto_enforce=false`。它不能修改配置，也不代表全量 enforce 已获批准。

### 3.4 客户端与界面

- MCP capabilities 升级为 `echome.capabilities.v5`。
- core profile 保持 8 个工具；`echome_runtime_health(include_policy_readiness=true)` 返回门禁，避免增加
  默认工具选择负担。
- `echome_context_outcome` 可提交 `policy_effect`。
- Web Logs / Context Runs 上方展示总体 readiness、覆盖率、helpful/harmful 和阻塞原因。

## 4. 数据安全

revision `017` 只为 `context_outcomes` 新增 nullable `policy_effect`、在线验证的 CHECK constraint，并为
policy effect 与 bounded Context Run 查询新增并发索引：

- 不回填、不更新、不移动、不删除任何历史行。
- 旧客户端不传字段时行为不变。
- compatibility downgrade 保留新增列和 outcome evidence，旧代码可忽略额外列。
- concurrent index 会检查 `pg_index.indisvalid`；失败遗留的同名 invalid index 会被并发删除并重建。
- 生产前必须在完整数据副本演练 `015 -> 017 -> 015 -> 017`，并比较所有权威源表内容哈希。

## 5. 发布门禁

1. Hub、CLI/MCP 全量 pytest 和 Ruff 通过，Web production build 通过。
2. OpenAPI 可生成且只有一个 Alembic head `017`。
3. v1 Sleep 契约、v2 simulation、默认 shadow 和 enforce feature flag 回退全部保持兼容。
4. Readiness 的空样本、达标、harmful、冲突、source mutation 和 enforce 排除路径均有测试。
5. 在生产数据副本完成迁移往返与哈希核对；生产库在正式部署前保持 `015`。
6. 独立审查数据兼容、门禁统计、MCP 契约和 UI，不允许 readiness 自动开启 enforce。

## 6. 发布与回退

1. 合并 v1.7 PR 后，发布工作流用显式 `target_version=1.7.0` 构建、安装 smoke、打 tag 并发布 PyPI。
2. 生产备份后执行 `alembic upgrade 017`，部署 Hub/Web，并保持
   `ECHOME_CONTEXT_POLICY_ENFORCE_ENABLED=false`。
3. 重启本地 MCP，核对 package、MCP、Hub 和 schema version，再调用 readiness 端到端冒烟。
4. 代码回退到旧版本时不删除 `016/017` 数据结构；旧代码会忽略派生快照和新 outcome 字段。

## 7. 明确不做

- 不自动启用 enforce，不做全局排序切换。
- 不根据缺失 outcome、访问时间或项目搁置自动降权/归档。
- 不让 readiness 或 AI 直接修改 Memory、Constraint、Edge、Artifact 或 Sleep proposal。
- 不替换 PostgreSQL/pgvector，不引入新的图数据库或外部 LLM 强依赖。
- 不在本版扩展默认 MCP core tool 数量。

## 8. 当前验收进度

- v1.6 基线：Hub `128 passed, 1 skipped`，CLI/MCP `28 passed`，Web build 通过；生产副本
  `015 -> 016 -> 015 -> 016` 哈希一致。
- v1.7 全量回归：Hub `147 passed, 1 skipped`，CLI/MCP `30 passed`，两个 Ruff 均通过；四个新增/高风险
  Hub service 的 strict mypy 通过。
- Web：Vue TypeScript 与 Vite production build 通过，共转换 84 个模块。
- OpenAPI：77 个 paths、92 个 schemas；Alembic 只有一个 head `017`。
- 迁移演练：在完整生产副本完成 `015 -> 017 -> 015 -> 017`；compatibility rollback 保留
  `policy_effect` 和 reliability table。所有权威表在迁移、回退重入和故障恢复后的 manifest SHA-256 均为
  `ae94532df1e197497ee176d4424b7bb48446b3d414ecacc8c74e507ffc9a9f35`。CHECK 为 validated；两个新增
  索引均为 valid/ready。
- 故障注入：在副本故意制造 `CREATE UNIQUE INDEX CONCURRENTLY` 失败留下的 `false/false` invalid index；
  `017` 重跑后自动恢复为正确的 `true/true` btree，权威表哈希不变。
- 数据状态：临时数据库和含生产数据的 `/tmp` dump 已清理；生产 revision 再次确认为 `015`。
- UI：Playwright 在 1440x900、390x844 验证 Context Runs -> Policy Readiness、Refresh、显式 API 错误态、
  无横向溢出，console errors 与 page errors 均为 0。Browser plugin 不可用，因此按前端测试契约使用本机
  Playwright。
- 独立审查发现的截断优先级、畸形 trace、阈值舍入、发布输入注入、在线索引恢复和错误态问题均已修复，
  并由针对性测试或真实 PostgreSQL 故障注入覆盖。
- 待完成：PR/合并、正式发布、生产迁移和 MCP 重启。
