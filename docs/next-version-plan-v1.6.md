# EchoMe v1.6 计划：Trusted Context Policy

状态日期：2026-08-23。本计划的实现已作为基线并入
[v1.7 Trusted Context Calibration](next-version-plan-v1.7.md)；v1.6 未单独迁移、部署或公开发布。

## 1. 版本目标

v1.6 不继续扩展新的记忆存储体系，而是在现有 Memory、Project Knowledge、Context Runtime、
Retrieval Logs 和 Memory Sleep 之上建立可信决策层：

> AI 不只拿到相关记忆，还能知道它是否仍受支持、为什么需要警告，以及整理后检索是否退化。

核心边界保持不变：

- Memory 与 Project Knowledge 分开存储。
- 原始 Memory、Artifact、Constraint、Event 和关系边不被策略层覆盖或删除。
- 可靠性评估是可重建快照，不是真相字段。
- Context policy 默认 `shadow`，只观测决策；`enforce` 还需要服务端显式开关。
- Sleep 继续使用 proposal -> validate -> approve -> apply。

## 2. 当前实现进度

| 范围 | 状态 | 结果 |
|---|---|---|
| Reliability assessment | 已实现 | 新增 additive revision `016` 和可重建评估快照；不修改源记录 |
| Context intervention | 已实现 | `inject / inject_with_warning / expand / silent / abstain`；默认 shadow |
| MCP contract | 已实现 | `echome_context`、`echome_project_context` 暴露 `policy_mode`；capabilities v4 |
| Real-log replay | 已实现 | 只读重放已记录 query，比较 expected rank 与 top-k Jaccard |
| Scale-conditioned eval | 已实现 | 按 memory count 统计预算内可靠性和首个退化拐点 |
| Sleep v2 | 已实现 | MCP 默认请求 v2；来源前置条件、终态覆盖、token footprint、before/after replay、apply 前重算；REST 省略版本时保持 v1 |
| Web diagnostics | 已实现 | Eval 显示 reliability/intervention；Logs 可重放 scored logs 并查看 policy trace |
| Production rollout | 未执行 | 生产迁移、部署、MCP 重启和版本发布需单独验收后执行 |

## 3. Reliability Assessment

### 3.1 两个正交维度

`assessment_class` 表达信息通常如何变化：

- `invariant`
- `durable`
- `environment_bound`
- `volatile`
- `episodic`
- `unknown`

`support_state` 表达当前证据是否支持它：

- `current_supported`
- `historical`
- `needs_verification`
- `conflicting`
- `dormant_scope`
- `insufficient_evidence`

长期未访问本身不会判为过时。项目 dormant 由 Project、Project Event 和 Artifact 的最近活动共同判断，
并单独标为 `dormant_scope`。

### 3.2 派生与审计

`reliability_assessments` 保存 producer、schema version、reason codes、evidence refs、source watermark
和 fingerprint。同一来源水位和判断只写一份快照；源 Memory/Constraint 不增加可被静默改写的“最终真相”字段。

只读历史接口：

```text
GET /api/v1/observability/reliability-assessments
```

## 4. Context Policy

请求参数：

```json
{
  "policy_mode": "shadow"
}
```

- `off`：不计算策略。
- `shadow`：返回 reliability/intervention 和 would-exclude，但不改变结果集。
- `enforce`：只有 `ECHOME_CONTEXT_POLICY_ENFORCE_ENABLED=true` 时过滤 `silent/abstain`；否则自动回退 shadow。

每条记忆或约束会附带：

```json
{
  "reliability": {
    "classification": "environment_bound",
    "support_state": "needs_verification",
    "confidence": 0.78,
    "reason_codes": ["volatile_requires_verification"]
  },
  "intervention": {
    "action": "inject_with_warning",
    "include": true
  }
}
```

## 5. 质量评估

### 5.1 真实日志回放

```text
POST /api/v1/retrieval-debug/replay
```

重放 Retrieval Logs 中原始 query 和 scope，不写新日志。对有 expected IDs 的记录比较之前与当前排名，
输出 regressed、improved、unchanged、unscored 和 top-k Jaccard。

### 5.2 规模条件评估

```text
POST /api/v1/project-knowledge/eval/scale
```

按 `memory_count` 汇总 accuracy、预算内可靠性、p90 memory calls、token cost 和 irrelevant count，
并给出 `breakdown_onset`。这能区分“小样例正确”和“大规模仍可靠”。

## 6. Memory Sleep v2

`memory_sleep_plan.v1` 继续兼容。升级后的 MCP 会显式请求 v2；REST 候选接口省略版本时仍返回 v1，v2 增加：

- 每个 input memory 的 `status / sleep_state / updated_at` 前置条件。
- 每个 input 恰好一个终态动作：keep、archive/deprecate 或 needs_human。
- archived 来源必须有 `derived_from` 对应的新记忆。
- 至少一个 replay case。
- 来源覆盖率、token growth、scored replay 数和 replay regression 质量门禁。
- 服务端拥有 `server_simulation`，客户端提交的同名字段会被替换。

proposal 提交时模拟一次；apply 前按最新数据库状态重新模拟。任何门禁失败返回 `409`，不进入写入循环，
也不会 commit。

当前模拟器是 `candidate_local_lexical`，用于确定性预检，不冒充完整向量线上回放。真实检索回归由
Retrieval Log replay 单独覆盖。

## 7. 数据安全与迁移

revision `016` 仅新增 `reliability_assessments` 表和索引：

- 不更新、搬迁或删除现有行。
- 表内数据是派生快照，可忽略或重建。
- compatibility downgrade 保留该表，避免回退旧代码时误删审计数据。
- 生产迁移前必须先备份，并在生产数据副本上执行 `015 -> 016` rehearsal 与行数/哈希核对。

## 8. Rollout

1. 本地完成全量 Hub、CLI/MCP、Web 构建与迁移静态检查。
2. 在生产数据库副本执行 migration rehearsal，核对源表行数和内容哈希。
3. 生产备份后执行 `alembic upgrade 016`。
4. 部署 Hub/Web/MCP，保持 context policy 为 shadow。
5. 收集真实 replay、would-exclude、warning 和用户反馈，不自动改排序。
6. 只有连续质量门禁通过后，才单独评估小流量 enforce；Sleep 自动化仍只生成 proposal。

## 9. 本地验收

```bash
# Hub
cd hub
.venv/bin/ruff check app tests alembic/versions
.venv/bin/pytest tests
.venv/bin/alembic heads

# CLI + MCP
cd ..
.venv/bin/ruff check echome echome_mcp tests
.venv/bin/pytest tests

# Web
cd web
npm ci
npm run build
```

重点人工检查：

- `policy_mode=enforce` 在开关关闭时仍返回 shadow，且 source mutation 为 none。
- Logs 的 Replay scored 能发现 expected rank 退化。
- Sleep v2 修改任一 input 的 status/updated_at 后 apply 被拒绝。
- v1 Sleep 预案仍可按旧契约执行。

## 10. 2026-08-23 验收回执

- Hub：`128 passed, 1 skipped`；Hub Ruff 全部通过。
- CLI/MCP：`28 passed`；根目录 Ruff 全部通过。
- Web：Vue TypeScript 检查和 Vite production build 通过，共转换 84 个模块。
- OpenAPI：可成功生成，包含 76 个 paths 和 92 个 schemas。
- Alembic：只有一个 head，revision 为 `016`。
- 迁移演练：在生产数据库完整副本上完成 `015 -> 016 -> 015 -> 016`；兼容回退和再次升级均保留派生快照。
- 源数据校验：排除 `alembic_version` 和新增派生表后，演练前后 dump 的 SHA-256 均为
  `11ea5c4f11d791cfa9d65c66f98bc8626584a3e332bcd821ff238d1d6ebe33ed`。
- 渲染冒烟：production preview 在 1440x900 和 390x844 下完成页面、交互、空白页、错误覆盖层和控制台检查；
  控制台为 0 errors / 0 warnings。受认证保护的诊断数据页未使用生产凭据做浏览器验收。
- 高风险复审：Standards 与 Spec 两个独立只读审查完成；修复会话竞态、shadow 预算干扰、边方向、
  v1 越界引用和不可比 replay 后，第二轮复审均为 PASS。
- 生产状态：数据库仍为 revision `015`；本轮没有执行生产迁移、服务重启、部署、提交、推送或发布。
