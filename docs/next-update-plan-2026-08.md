# EchoMe 下一阶段更新计划（2026-08）

> 本文件记录已在 v1.4.0 交付的 Project Context Compiler 实施过程。文中的“待授权”和 Alembic `010` 等内容是发布前历史快照，不代表当前运行状态；后续版本规划见 [next-version-plan-v1.5.md](next-version-plan-v1.5.md)。

## 0. 实施与验收状态

状态日期：2026-08-12。

本计划的 Phase 1-4 已在工作区实现，Phase 0 的代码、迁移和构建基线也已完成。Git commit、push、PR 和生产发布按项目权限规则保持为独立动作，尚未执行；生产数据库仍停留在 Alembic `010`，未被本轮迁移或测试修改。

| 阶段 | 状态 | 主要结果 |
|---|---|---|
| Phase 0 | 代码已验收，发布待授权 | 生产备份副本完成 `010 -> 012 -> 010 -> 012` 演练；主数据行数和内容哈希不变；HTTP/MCP smoke 可复测 |
| Phase 1 | 已完成 | Artifact chunks、BGE embedding、FTS、RRF Context Compiler、token budget、structured MCP、shadow dual-read |
| Phase 2 | 已完成 | Knowledge view 水位与 stale fallback、双时间元数据、约束复核 proposal/apply/version guard |
| Phase 3 | 已完成 | append-only Project Events、事件关系、证据化只读 preflight |
| Phase 4 | 已完成 | 26 条固定质量案例、质量快照、连续三次门禁、dry-run 和 proposal-only 自动化 |

最终隔离环境验收结果：

- Hub：`74 passed, 1 skipped`；根 MCP/项目知识测试：`9 passed`。
- Ruff：Hub 与根目录检查通过；Web：`vue-tsc` 与 Vite production build 通过。
- 质量集连续三次通过：`Recall@10 = 95.12%`、`evidence precision = 100%`、`stale answer rate = 0%`、冲突显式化/拒答/约束遵循/影响覆盖/Preflight precision 与 recall 均为 `100%`。
- 写路径 smoke 仅在生产备份恢复出的隔离数据库执行；自动化开启后只新增 `pending` proposal，约束状态哈希保持不变，未发生自动 apply。
- Hub 的 token counter 已改为真正离线安全：没有本地 `tiktoken` cache 时立即使用估算，不再在启动阶段等待网络下载。

发布前只剩受权限控制的操作：审查并提交当前 diff、迁移生产数据库、回填 chunks、执行只读 smoke，再按需要开启 proposal 自动化 feature flag。具体步骤见 [project-knowledge.md](project-knowledge.md)。

## 1. 结论

EchoMe 已经从“跨 AI 的个人记忆同步层”发展为两个协作但独立的系统：

- **Memory**：保存用户偏好、工作规范、历史背景和可复用经验。
- **Project Knowledge**：保存项目制品、版本化约束、证据和影响关系。

当前不需要替换 PostgreSQL、pgvector、Memory Sleep 或现有数据模型。下一阶段应围绕一个目标推进：

> **把现有记忆和约束图编译成有预算、有证据、有时间可靠性、可被 AI 稳定消费的项目上下文。**

本计划采用增量迁移。现有记忆、制品版本、约束版本和关系边全部保留；新索引和派生视图必须可重建、可关闭、可回滚。

## 2. 制定计划时的基线与实施后状态

基线日期：2026-08-12。

### 2.1 仓库与运行态

- 根包声明版本为 `1.3.0`，`docs/roadmap.md` 已同步本次实施状态。
- Hub、Web、PostgreSQL、Redis、Embedding 容器运行正常。
- 生产数据库 Alembic 版本为 `010 (head)`。
- 隔离数据库已验证 Alembic `012`，生产仍未迁移。
- Hub、根 MCP/项目知识测试、Ruff 和 Web production build 均通过。
- 本地缺失的 `cytoscape` 依赖已按 lockfile 恢复并完成真实构建验证。

### 2.2 生产数据规模

| 数据 | 数量 |
|---|---:|
| Projects | 25 |
| Memories | 440 |
| Memory edges | 182 |
| Sleep sessions | 8 |
| Retrieval logs | 32 |
| Memory feedback | 2 |
| Project artifacts | 174 |
| Project constraints | 11 |
| Constraint edges | 8 |
| Constraint evidence | 24 |

### 2.3 已完成能力

- summary-first 检索、按 UUID 精读和向量/关键词混合搜索。
- Memory Sleep 候选、文本/JSON 预案、服务端校验执行和来源归档。
- Memory 图、来源解释、时间复核、邻居查询和 Web 可视化。
- 检索日志、调试器、两条固定 Memory Quality Eval 样例和使用反馈。
- 项目制品按 SHA-256 增量同步，不可变 revision 和 stale 标记。
- 项目约束版本链、证据关系、影响传播和项目工作台。
- MCP 能力发现、Memory 工具和 Project Knowledge 工具分工。

### 2.4 发布前剩余风险

1. **Git 基线待授权**：实现和测试仍位于未提交工作区；需要单独授权 commit/push/PR。
2. **生产发布待授权**：迁移只在生产备份副本演练；生产 `010` 尚未执行 `011/012`。
3. **首轮回填需要观察资源**：652 个 chunks 的隔离回填已通过，生产回填仍应使用 checkpoint、小批次和监控。
4. **自动化默认关闭**：即使质量门禁通过，`ECHOME_PROJECT_AUTOMATION_ENABLED` 默认仍为 `false`；开启后也只生成 proposal。

## 3. 外部项目的可借鉴机制

调研范围以 2026-08-12 前仍活跃的官方项目、文档和论文为主。GitHub 热度只用于确认社区活跃度，不作为选型依据。

| 项目/机制 | 值得借鉴 | EchoMe 的取舍 |
|---|---|---|
| Hindsight | `retain / recall / reflect` 分层；事实、观察、mental model 三层；派生层暴露 staleness；语义、BM25、图和时间并行检索 | 引入“原始证据 / 派生视图”分层和新鲜度水位；服务端先提供证据包，不强制由服务端 LLM 代替客户端判断 |
| Graphiti | 事实和关系的双时间语义；旧事实失效但不删除；episode 来源；增量图更新 | 为边和证据补充时间与来源，不引入 Neo4j/FalkorDB；继续使用 PostgreSQL |
| Letta | 主 Agent 与 Sleep Agent 分离；后台使用更强模型整理；高价值 memory block 常驻上下文 | 保留“客户端强 AI 生成预案、Hub 校验执行”；不允许 Sleep Agent 静默覆盖核心记忆 |
| MemOS | Memory Cube 隔离和组合；异步 MemScheduler；多模态和工具轨迹作为记忆 | 先强化已有 user/project scope 和后台任务，不新增一套与 Project 重叠的 Cube 主模型 |
| GraphRAG | Local、Global、DRIFT 三类查询；社区摘要；增量输出与上下文 token 预算 | 为项目查询增加 `local / overview / impact` 模式和可重建社区摘要；不运行全仓库高成本 LLM 图抽取 |
| PROJECTMEM | append-only 项目事件；记录失败尝试和修复；行动前 gate；MCP 面向编码 Agent | 新增项目事件流和只读 preflight 提醒；第一阶段只警告，不自动阻断 AI 操作 |
| LongMemEval-V2 / LoCoMo-Plus | 评估动态状态、工作流、环境陷阱、前提意识和隐含约束一致性 | 从“能否命中 UUID”升级为“能否依据记忆做对、更新、拒答并遵守约束” |
| MCP 2025-11-25 | `outputSchema`、`structuredContent`、工具注解和异步 Tasks | 先增加结构化输出和兼容文本；Tasks 仍属实验能力，等内部异步任务稳定后再接入 |

## 4. 目标架构

```text
Authoritative sources
  Memories / Artifact revisions / Project events
                |
                v
Rebuildable indexes
  Embeddings / FTS / Artifact chunks / Graph adjacency
                |
                v
Derived knowledge
  Distilled memories / Constraint views / Project summaries
  每个派生结果记录 source watermark 和 staleness
                |
                v
Context compiler
  local + overview + impact + temporal + feedback
  按 token budget 生成 evidence-first context pack
                |
                v
MCP structured output
  AI 读取事实、约束、冲突、来源、新鲜度和建议动作
```

### 4.1 保持不变的领域边界

- Memory 和 Project Knowledge 不合并表。
- Repository、Issue 系统等外部来源仍是制品的权威来源。
- Sleep 和约束整理继续使用 proposal -> validate -> apply。
- `archived`、`deprecated`、`superseded` 数据继续保留并默认排除于当前上下文。
- 用户反馈和 AI 使用日志只追加信号，不直接改变记忆状态。

## 5. 分阶段实施计划

### Phase 0：建立可恢复发布基线（代码已完成，发布待授权）

目标：先让当前生产能力进入可追踪、可重建的版本。

任务：

1. 审查当前未提交的项目知识 diff，确认只包含已经部署的功能和必要测试。
2. 创建发布分支/提交，更新版本和当前进度文档；commit、push、PR、deploy 分别授权执行。
3. 恢复干净的 Web 依赖安装，验证 `cytoscape` 类型和生产构建。
4. 记录数据库备份、迁移版本、容器镜像和生产 smoke 基线。
5. 为项目知识 HTTP/MCP 主路径增加端到端 smoke，避免只测试内部选择函数。

验收：

- 工作区改动来源明确，生产对应代码能由 Git commit 重建。
- Hub lint/test、根 MCP test、Web build 全部通过。
- `/health`、Memory Search、Sleep Observability、Project Context、Project Impact 可复测。
- 数据表行数和现有 UUID 不发生变化。

### Phase 1：Context Compiler v1（已完成）

目标：让 AI 通过一个稳定入口获得有证据、有预算的任务上下文。

新增可重建数据：

- `artifact_chunks`：关联 immutable `project_artifact_id`，保存 ordinal、locator、content hash、文本、embedding 和 FTS 字段。
- `context_runs`：记录 query、模式、候选来源、融合分数、token 使用和最终选中项；可复用现有 retrieval log 结构，但不改变已有日志语义。

检索流程：

1. 根据任务、项目、changed paths 和可选时间范围生成查询计划。
2. 并行获取 Memory、Constraint、Artifact chunk 候选。
3. 使用 Reciprocal Rank Fusion 融合向量、FTS/BM25 类信号、图距离和路径命中，避免固定 `0.7/0.3` 权重放大单路异常。
4. 应用状态、scope、时间可靠性和来源过滤。
5. 按 token budget 生成 context pack，并保留 selection reasons。

建议输出：

```json
{
  "mode": "local",
  "must_include": [],
  "constraints": [],
  "memories": [],
  "evidence": [],
  "conflicts": [],
  "stale_warnings": [],
  "unknowns": [],
  "token_budget": 6000,
  "retrieval_trace": {}
}
```

兼容方案：

- 保留 `echome_project_context`，内部转到 Context Compiler。
- MCP 同时返回 `structuredContent` 和序列化 TextContent，旧客户端继续工作。
- 新检索先以 feature flag 影子运行，比较结果后再成为默认路径。

验收：

- inactive 记忆和约束不会混入当前事实。
- 每条重要结论能定位到 memory UUID、artifact revision 和 locator。
- 输出严格服从 token budget。
- 建立至少 20 条固定 gold cases，项目上下文 `Recall@10 >= 90%`，并单独报告 evidence precision。

### Phase 2：派生视图新鲜度与证据复核（已完成）

目标：允许系统提前整理项目知识，同时明确告诉 AI 派生内容是否落后于来源。

新增数据：

- `knowledge_views`：版本化项目摘要/mental model，保存 query、content、source watermark、refresh mode 和状态。
- `constraint_revalidation_proposals`：证据 revision 变化、来源冲突或时间到期时生成复核预案。
- 为 constraint edge/evidence 增加 nullable 的 `observed_at`、`valid_from`、`valid_to`、`invalidated_at` 和来源元数据。

行为：

- 新制品 revision 到达后，只把相关派生视图标记为 stale，不修改旧制品和约束。
- 查询命中新鲜视图时可直接使用；视图 stale 时自动回源到 chunk、memory 和 constraint evidence。
- AI 可以生成复核 JSON，Hub 只负责 schema、权限、版本前置条件和引用完整性校验。
- 通过复核后创建约束新版本，旧版本进入 `superseded`；拒绝预案不影响原数据。

验收：

- 派生视图不能在无 warning 的情况下覆盖更新后的原始证据。
- 重复提交、过期版本和跨项目引用均被拒绝。
- 全部派生表可清空重建，主数据结果不变。

### Phase 3：项目事件记忆与行动前检查（已完成）

目标：把“做过什么、为什么失败、怎样修好”转化为下一次开发可用的经验。

新增数据：

- `project_events`：append-only 记录 `issue`、`attempt`、`failure`、`fix`、`decision`、`test_result`、`deploy`、`note`。
- `event_links`：事件与 memory、constraint、artifact revision、其他事件的关系。

新增 MCP 能力：

- `echome_project_event_append`：客户端提交结构化事件，默认不生成 active 约束。
- `echome_project_preflight`：输入任务、changed paths 和计划动作，返回历史失败、脆弱文件、相关约束和验证要求。

约束：

- 第一版 preflight 只读、只警告，不自动阻断文件修改、提交或部署。
- 从事件提炼长期规则仍进入 proposal，不直接写 active constraint。
- 日志、代码和测试结果优先作为证据，AI 总结只作为派生内容。

验收：

- 已记录的失败方案能在相似改动前被召回。
- preflight 每条警告都有事件或制品证据。
- 建立误报率指标；没有足够证据时返回 unknown，而不是编造风险。

### Phase 4：质量闭环与受控自动化（已完成）

目标：在可量化的质量基础上逐步自动化，而不是按时间直接清理记忆。

评估集至少覆盖：

- 单条事实提取。
- 跨记忆/跨会话推理。
- 时间范围和历史状态。
- 新信息替代旧信息。
- 冲突显式化。
- 无证据时拒答。
- 隐含偏好/约束的一致执行。
- 工作流、项目陷阱和失败方案。
- changed paths 的影响完整性。
- 归档/废弃内容的错误召回。

指标：

- Recall@K、MRR、evidence precision。
- stale answer rate、conflict surfacing rate、abstention accuracy。
- constraint adherence、impact coverage、preflight precision。
- p50/p95 latency、token cost、Sleep proposal acceptance rate。

自动化门槛：

- 先支持手动触发和后台 dry-run。
- 连续多个固定快照通过质量阈值后，才允许定期自动生成 Sleep/复核预案。
- 自动任务只生成 proposal；apply 仍使用现有确认和服务端验证机制。

## 6. 数据安全与迁移规则

1. 只新增表、索引和 nullable 字段；不重写现有主键和历史内容。
2. 每次迁移前创建可验证备份，并在副本上执行 upgrade/rollback 演练。
3. backfill 使用批次、checkpoint 和幂等键，可暂停、重试和继续。
4. 新索引先 shadow build，新旧查询 dual-read，对比日志不改变用户结果。
5. 派生数据保存 `schema_version`、`producer`、`source_watermark` 和生成时间。
6. 默认不 hard delete；删除派生索引不能级联删除 Memory、Artifact、Constraint 或 Event。
7. 不在本阶段引入独立图数据库。只有 PostgreSQL 图查询经过真实压测仍无法满足目标时再评估。
8. 不让 LLM 直接执行数据库 mutation；所有写操作经过固定 JSON Schema、权限和版本前置条件校验。

## 7. 推荐执行顺序

| 优先级 | 工作 | 原因 |
|---|---|---|
| P0 | Phase 0 发布基线 | 当前生产功能没有对应 Git 基线，继续开发会放大恢复风险 |
| P1 | Artifact chunks + Context Compiler + MCP 结构化输出 | 直接提升 Codex/Claude/Cursor 使用记忆的稳定性，是当前价值最高的链路 |
| P1 | Eval 扩展到 20+ 固定案例 | 没有质量基线就无法判断新检索是否真的更好 |
| P2 | 派生视图 staleness + constraint revalidation | 解决“曾经正确、现在不确定”和来源更新问题 |
| P2 | Project events + preflight | 让项目经验影响下一次行动，形成约束网络的实际价值 |
| P3 | 社区摘要、DRIFT 式查询、定期自动 proposal | 需要建立在可靠检索和评估之上 |

建议先完成 Phase 0，再以一个小版本只交付 Phase 1，不把时间图、事件流和自动 Sleep 同时塞入一次发布。

## 8. 本阶段明确不做

- 不迁移到 Mem0、Hindsight、Graphiti、MemOS 或其他外部存储。
- 不合并 Memory 与 Project Constraint。
- 不根据“长期未访问”自动判定记忆过时。
- 不静默修改、覆盖或删除原始记忆和项目制品。
- 不把所有仓库文件交给 LLM 做全量实体/关系抽取。
- 不在缺少评估数据时用反馈信号自动升降权重。
- 不让 preflight 第一版变成不可解释的自动拦截器。

## 9. 参考资料

- [Mem0](https://github.com/mem0ai/mem0)
- [Graphiti](https://github.com/getzep/graphiti)
- [Hindsight: Best Practices](https://hindsight.vectorize.io/best-practices)
- [Hindsight: Staleness-Aware Memory](https://hindsight.vectorize.io/blog/2026/06/17/freshness-aware-memory)
- [Letta: Sleep-time Compute](https://www.letta.com/blog/sleep-time-compute/)
- [Letta: Memory Models](https://www.letta.com/blog/towards-agents-that-learn/)
- [MemOS](https://github.com/MemTensor/MemOS)
- [GraphRAG Query Engine](https://microsoft.github.io/graphrag/query/overview/)
- [PROJECTMEM](https://arxiv.org/abs/2606.12329)
- [LongMemEval-V2](https://xiaowu0162.github.io/longmemeval-v2/)
- [LoCoMo-Plus](https://aclanthology.org/2026.acl-long.1150.pdf)
- [MCP Tool Schema](https://modelcontextprotocol.io/specification/2025-11-25/schema)
