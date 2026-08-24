# EchoMe Memory Sleep 设计

## 目标

Memory Sleep 是 EchoMe 的记忆治理机制，用于定期或手动整理持续增长的记忆。

它解决的问题不是“搜索不到”，而是：

- 记忆越来越多，旧结论、临时 workaround、重复经验会污染后续检索。
- 用户很难长期人工跟踪哪些记忆已过时、被更新、互相冲突。
- AI 需要从大量浅层记忆中提炼更稳定的深度记忆。
- 旧记忆不能直接删除，需要保留来源和关系，便于回溯和可视化。

Memory Sleep 的第一版必须是手动触发、生成预案、用户确认后执行；成熟后再考虑定期自动整理。

## 核心原则

- **强 AI 负责整理质量**：整理预案可以由服务端模型生成，也可以由客户端更强 AI 生成。
- **服务端负责校验和执行**：数据库状态变更必须由 Hub 根据固定 JSON 预案执行。
- **AI 不静默大量改库**：Sleep 只生成 proposal；用户确认后才 apply。
- **旧记忆不删除**：被归纳的旧记忆进入 `archived` 或 `deprecated`，并记录关系。
- **默认整理候选包含有效待整理记忆**：Sleep 默认候选包括 `active`、`ai_review`、`pending`，不包括 `deprecated` 和 `archived`。
- **核心记忆严格保护**：用户标记或多次确认的 core memory 默认不参与归纳。
- **文本预案给人看，JSON 预案给机器执行**：两者必须表达同一组动作。

## 记忆层次

### 浅层记忆

浅层记忆是最近产生、上下文依赖强、细节多的记忆。

典型例子：

- 某次 bug 修复经验
- 某次临时部署 workaround
- 某个分支的当前状态
- 某次用户纠正

浅层记忆通常在 `L2`，可搜索，但不应无限期影响默认行为。

### 深度记忆

深度记忆是从多条浅层记忆中提炼出的稳定规则。

典型例子：

- 某项目遇到线上异常时应先查真实链路，而不是猜框架问题。
- EchoMe 宽泛项目查询应先返回 route/index memory，再按需精读细节。
- 临时 workaround 必须带有效期或 stale 条件。

深度记忆可以进入 `L1`，必要时进入 `L0`。它必须短、结构化、带适用范围。

### 路由记忆

路由记忆用于告诉 AI 某个项目或主题的记忆入口。

它不替代具体记忆，而是帮助 AI 先定位：

- 当前项目有哪些重要记忆分区
- 哪些记忆是当前入口
- 哪些旧记忆可能已过时
- 应该继续查询哪些关键词或 tag

## 架构

```text
CLI / MCP / Web
  -> request candidate memories
  -> generate or display proposal
  -> user review and approve
        |
        v
Hub Sleep API
  -> validate JSON proposal
  -> apply approved actions in one transaction
  -> write memory edges and audit log
        |
        v
Memory Store
  -> create distilled memories
  -> archive or deprecate old memories
  -> keep derived_from / superseded_by relations
```

## 两种预案生成方式

### 方式一：服务端生成预案

适合普通用户和 Web Console。

```text
client -> Hub: create sleep session
Hub -> select candidates
Hub -> call configured AI model
Hub -> store text proposal + JSON proposal
client -> user review
client -> Hub: apply approved proposal
```

优点：

- 体验简单
- 服务端可统一控制模型、提示词、候选范围和审计
- 适合后续定期任务

缺点：

- 整理质量受服务端模型限制
- 私有部署需要配置模型能力

### 方式二：客户端生成预案

适合 Codex、Claude Code、桌面客户端等拥有更强 AI 的场景。

```text
client -> Hub: request sleep candidates
Hub -> return candidate memories + constraints + JSON schema
client AI -> generate text proposal + JSON proposal
user -> review and edit
client -> Hub: submit approved JSON proposal
Hub -> validate and apply
```

优点：

- 可以利用客户端更强的 AI 能力
- 用户能在本地对 proposal 充分讨论和修改
- 服务端不需要承担所有智能整理能力

缺点：

- 必须严格校验 JSON proposal
- 服务端不能信任客户端生成的动作

## Sleep Session 生命周期

```text
draft
  -> proposed
  -> approved
  -> applied

draft/proposed
  -> rejected

approved/applied
  -> cannot edit
```

说明：

- `draft`：已创建 session，候选记忆已确定或正在补充。
- `proposed`：已有文本预案和 JSON 预案。
- `approved`：用户确认可以执行。
- `applied`：服务端已完成数据库更新。
- `rejected`：用户拒绝本次整理。

## 候选记忆选择

服务端负责提供所有可能参与整理的候选记忆。

Sleep 候选选择不能沿用普通检索的 `top_k` 语义。普通检索可以返回 top-k；记忆整理必须让客户端拿到当前范围内的全部可整理记忆。

如果记忆数量很多，服务端可以分页或游标返回，但不能因为默认 `top_k=5` 只给前几条。客户端生成预案前必须能确认：

- 已读取当前 project/scope 下全部 eligible memories。
- 已读取被严格保护而不参与整理的 protected/core memories。
- 已读取与候选记忆直接相关的关系边。
- 是否还有下一页候选未拉取。

候选来源：

- 同一 project / type / tag 下语义相似度高的 active 记忆。
- 多次被检索但内容重叠的记忆。
- 长时间没有访问的记忆。
- 包含时间敏感词的记忆，例如“临时”、“当前”、“旧版本”、“workaround”、“已恢复”。
- 用户手动选择的记忆集合。
- 与 route memory、summary-first、项目状态等高层主题相关的记忆集合。

严格排除：

- `is_core = true` 的记忆。
- 用户近期刚确认过的核心规则。
- 明确已经被 Sleep 整理过的记忆。
- 高优先级 `L0/L1`，除非用户显式选择或存在明确冲突证据。
- 已经是 `archived` 或 `deprecated` 的记忆；历史仍可审计和查询，但不能重新进入 Sleep 候选。

“明确已经被 Sleep 整理过”必须有强证据，避免误排除：

- `sleep_state` 是 `distilled` 或 `reviewed`。
- 或存在当前记忆参与过的 applied `sleep_session`。
- 或存在 `memory_edges` 关系表明它已经被其他记忆 `derived_from` / `supersedes` / `superseded_by` 处理过。

如果只有普通 `updated_at` 或 tag 变化，不算已经整理过。

候选接口应返回：

- memory metadata
- content
- status
- layer
- priority
- tags
- access_count
- last_accessed_at
- existing relation edges
- core/protection reason
- pagination cursor
- `has_more`

客户端 AI 必须在 `has_more = false` 后才能生成最终 JSON 预案。否则只能生成草稿或要求继续拉取。

## 文本预案

文本预案用于给用户审核。

示例：

```text
Sleep Proposal: EchoMe memory retrieval

Input memories: 10
- keep: 2
- archive/supersede: 8
- create: 3
- needs human: 1

Create memory: EchoMe broad project query uses route memory first
- derived from: memory-a, memory-c, memory-f
- action: create new L1 project memory
- old memories: archive memory-a, memory-c, memory-f

Keep memory: EchoMe MCP supports streamable HTTP transport
- reason: current, specific, not duplicated

Needs human:
- memory-x says HTTP transport unsupported
- memory-y says streamable-http supported
- suggested resolution: verify current code before applying
```

## JSON 预案

JSON 预案用于服务端稳定执行。服务端必须先校验，再在事务中 apply。

### 顶层结构

```json
{
  "schema_version": "memory_sleep_plan.v1",
  "session_id": "uuid",
  "project_id": "qzhqzh/EchoMe",
  "mode": "client_generated",
  "input_memory_ids": ["uuid-a", "uuid-b"],
  "summary": "Consolidate EchoMe memory retrieval decisions.",
  "actions": [],
  "created_by": {
    "actor": "client_ai",
    "model": "unknown",
    "client": "codex"
  }
}
```

### Action: create_memory

```json
{
  "op": "create_memory",
  "client_ref": "new-route-memory",
  "memory": {
    "title": "EchoMe broad project queries use route memory first",
    "content": "**EchoMe broad project queries should start from a route/index memory.**\n\n## Why\nOlder detailed memories can dominate search results.\n\n## How to apply\nReturn the route memory first, then drill into selected details.",
    "type": "project",
    "layer": "L1",
    "priority": 8,
    "tags": ["echome", "memory-retrieval", "route-memory"],
    "scope": {
      "global": false,
      "projects": ["qzhqzh/EchoMe"],
      "exclude_projects": []
    },
    "status": "active",
    "source": "sleep"
  },
  "derived_from": ["uuid-a", "uuid-b"]
}
```

### Action: update_memory_status

```json
{
  "op": "update_memory_status",
  "memory_id": "uuid-a",
  "from_status": "active",
  "to_status": "archived",
  "reason": "Consolidated into new-route-memory.",
  "superseded_by_ref": "new-route-memory"
}
```

### Action: create_edge

```json
{
  "op": "create_edge",
  "from": {
    "kind": "memory",
    "id": "uuid-a"
  },
  "to": {
    "kind": "client_ref",
    "id": "new-route-memory"
  },
  "relation": "superseded_by",
  "reason": "The new memory distills the stable rule from the old memory."
}
```

### Action: keep_memory

```json
{
  "op": "keep_memory",
  "memory_id": "uuid-c",
  "reason": "Current, specific, and not duplicated."
}
```

### Action: needs_human

```json
{
  "op": "needs_human",
  "memory_ids": ["uuid-d", "uuid-e"],
  "reason": "The memories conflict about current transport support.",
  "question": "Should the current code be treated as authoritative?"
}
```

## Memory Sleep v2

`memory_sleep_plan.v1` 保持兼容；REST 调用省略 `plan_schema_version` 时仍使用 v1，升级后的 MCP
客户端会显式请求 `memory_sleep_plan.v2`。v2 在原动作列表之外要求：

```json
{
  "schema_version": "memory_sleep_plan.v2",
  "preconditions": [
    {
      "memory_id": "uuid-a",
      "status": "active",
      "sleep_state": "fresh",
      "updated_at": "2026-08-23T12:00:00+00:00"
    }
  ],
  "replay_cases": [
    {
      "case_id": "git-workflow",
      "query": "Git 提交流程按什么规则？",
      "expected_memory_ids": ["uuid-a"],
      "top_k": 10
    }
  ],
  "quality_gates": {
    "min_source_coverage": 1.0,
    "max_replay_regressions": 0,
    "max_token_growth_ratio": 0.1,
    "min_scored_replay_cases": 1
  }
}
```

Hub 在 proposal 提交时生成 `server_simulation`，并在 apply 前基于最新数据重新生成。客户端提供的
`server_simulation` 不受信任。前置条件变化、来源未覆盖、token 超门禁或 replay 退化都会阻止 apply，
源记忆保持不变。

当前 before/after 模拟使用与线上一致的词法评分做 candidate-local 确定性预检；完整线上回归由
`POST /api/v1/retrieval-debug/replay` 负责。

## 服务端校验规则

服务端不能信任客户端 JSON 预案，必须校验：

- `schema_version` 支持。
- `session_id` 存在且未 applied。
- `input_memory_ids` 与 session 候选集合一致，或是其子集。
- 每个 `update_memory_status.from_status` 与数据库当前状态一致。
- 不允许修改 `is_core = true` 的记忆，除非 session 显式包含 `allow_core_changes = true` 且用户二次确认。
- 不允许删除记忆，只允许 `archived` / `deprecated`。
- `create_memory.status` 只能是 `active` 或 `ai_review`。
- `create_memory.source` 必须是 `sleep`。
- `derived_from` 只能引用本 session 的候选记忆。
- `superseded_by_ref` 必须能解析到本 plan 创建的新记忆。
- `needs_human` 不能在 apply 时自动执行状态变更。
- 整个 apply 必须在一个数据库事务里完成。

## 数据模型建议

### memories 新字段

```sql
ALTER TABLE memories ADD COLUMN is_core BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE memories ADD COLUMN sleep_state VARCHAR(16) NOT NULL DEFAULT 'fresh';
ALTER TABLE memories ADD COLUMN last_accessed_at TIMESTAMPTZ;
ALTER TABLE memories ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE memories ADD COLUMN superseded_by UUID REFERENCES memories(id);
ALTER TABLE memories ADD COLUMN derived_from JSONB NOT NULL DEFAULT '[]';
```

`sleep_state` 可选值：

- `fresh`
- `reviewed`
- `distilled`
- `superseded`

### memory_edges

更推荐新增关系表，便于后续网络图展示。

```sql
CREATE TABLE memory_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(64) NOT NULL,
    source_memory_id UUID NOT NULL REFERENCES memories(id),
    target_memory_id UUID NOT NULL REFERENCES memories(id),
    relation VARCHAR(32) NOT NULL,
    reason TEXT,
    sleep_session_id UUID,
    created_by VARCHAR(32) NOT NULL DEFAULT 'sleep',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

`relation` 可选值：

- `derived_from`
- `supersedes`
- `superseded_by`
- `duplicates`
- `conflicts_with`
- `specializes`
- `related_to`

### sleep_sessions

```sql
CREATE TABLE sleep_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(128),
    status VARCHAR(16) NOT NULL,
    mode VARCHAR(32) NOT NULL,
    candidate_memory_ids JSONB NOT NULL DEFAULT '[]',
    text_proposal TEXT,
    json_proposal JSONB,
    created_by JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    applied_at TIMESTAMPTZ
);
```

## API 草案

### Create server-generated plan

```text
POST /api/v1/memory-sleep/sessions
```

Request:

```json
{
  "project_id": "qzhqzh/EchoMe",
  "mode": "server_generated",
  "limit": 20,
  "include_archived": false
}
```

Response:

```json
{
  "session_id": "uuid",
  "status": "proposed",
  "text_proposal": "...",
  "json_proposal": {}
}
```

### Get candidates for client-generated plan

```text
POST /api/v1/memory-sleep/candidates
```

Request:

```json
{
  "project_id": "qzhqzh/EchoMe",
  "session_id": null,
  "scope": "project",
  "status": ["active", "ai_review", "pending"],
  "page_size": 100,
  "cursor": null,
  "include_protected": true,
  "plan_schema_version": "memory_sleep_plan.v2"
}
```

Response:

```json
{
  "session_id": "uuid",
  "project_id": "qzhqzh/EchoMe",
  "schema_version": "memory_sleep_plan.v2",
  "supported_schema_versions": ["memory_sleep_plan.v1", "memory_sleep_plan.v2"],
  "candidates": [],
  "protected_memories": [],
  "relation_edges": [],
  "json_schema": {},
  "next_cursor": null,
  "has_more": false
}
```

### Submit client-generated plan

```text
POST /api/v1/memory-sleep/sessions/{session_id}/proposal
```

Request:

```json
{
  "text_proposal": "...",
  "json_proposal": {}
}
```

### Apply approved plan

```text
POST /api/v1/memory-sleep/sessions/{session_id}/apply
```

Request:

```json
{
  "approved": true
}
```

## CLI / MCP 草案

CLI:

```bash
echome sleep candidates --project qzhqzh/EchoMe --limit 20
echome sleep plan --project qzhqzh/EchoMe
echome sleep submit <session-id> --file sleep-plan.json
echome sleep apply <session-id>
echome sleep reject <session-id>
```

MCP tools:

- `echome_sleep_candidates`
- `echome_sleep_plan`
- `echome_sleep_submit_proposal`
- `echome_sleep_apply`
- `echome_sleep_reject`

MCP 不直接改库，只调用 Hub API。

## Web Console: Observability

Hub Web Console 应新增一级菜单：`Observability`。

这个页面用于观察记忆系统如何变化、Sleep 如何整理记忆、以及检索为什么命中某些记忆。它不是纯 Admin 页面，而是用户日常调试和建立信任的入口。

### 子页面

建议拆成三个视图：

1. `Memory Changes`
2. `Sleep Sessions`
3. `Memory Graph`
4. `Search Debug`

### Memory Changes

展示所有记忆变更时间线。

每条事件包括：

- 时间
- actor：user / client_ai / server_ai / system
- source：manual / mcp / cli / web / sleep
- action：create / update / archive / deprecate / restore / apply_sleep
- memory id / title
- before / after 摘要
- sleep_session_id

用途：

- 用户能看到最近哪些记忆被新增、归档、废弃。
- 排查某条记忆为什么消失在默认搜索里。
- 回溯某次 Sleep apply 到底改了什么。

### Sleep Sessions

展示所有 Sleep 整理会话。

列表字段：

- session id
- project
- mode：server_generated / client_generated
- status：draft / proposed / approved / applied / rejected
- candidates count
- created memories count
- archived/deprecated count
- needs_human count
- created_at / applied_at

详情页展示：

- 候选记忆列表
- protected/core memories 列表
- 文本预案
- JSON 预案
- apply 结果
- 每条 action 的执行状态
- 错误和校验失败原因

详情页应支持：

- 查看新旧记忆 diff
- 查看 `derived_from` / `superseded_by`
- 拒绝 proposal
- 接受 proposal
- 下载 JSON proposal
- 上传客户端生成的 JSON proposal

### Memory Graph

展示记忆关系图。

节点：

- active memory
- archived memory
- deprecated memory
- sleep session

边：

- `derived_from`
- `supersedes`
- `superseded_by`
- `duplicates`
- `conflicts_with`
- `specializes`
- `related_to`

默认只显示当前 project 的 active 记忆和直接相关的 archived/deprecated 记忆。

用途：

- 看某条深度记忆来自哪些浅层记忆。
- 看旧记忆被哪条新记忆替代。
- 看冲突记忆是否仍未处理。
- 后续支持网络图可视化。

### Search Debug

用于调试检索质量。

输入：

- query
- project
- type
- include_archived
- include_deprecated

输出：

- candidate memories
- score breakdown：semantic / keyword / priority / recency
- status filter result
- scope filter result
- final ranking

用途：

- 解释为什么某条记忆被命中。
- 解释为什么归档记忆没有进入默认结果。
- 验证 Sleep 后检索是否变干净。

### Web API 补充

Observability 可以复用 Sleep API，同时新增轻量查询接口：

```text
GET /api/v1/observability/memory-events
GET /api/v1/observability/sleep-sessions
GET /api/v1/observability/sleep-sessions/{session_id}
GET /api/v1/observability/memory-graph
POST /api/v1/observability/search-debug
```

第一版可以先不做实时图，只做列表、详情、JSON diff 和基础关系展示。

## 查询规则

普通检索默认：

```text
status IN (active, ai_review)
scope matches current project
```

只有显式开启时才包含历史记忆：

```text
include_deprecated = true
include_archived = true
```

网络图、审计、历史回溯可以读取所有状态，但回答用户当前任务时不能默认使用 `archived` / `deprecated`。

Memory Sleep 候选只取 `active`、`ai_review`、`pending`。客户端生成预案时应能看到这些记忆的状态，并由用户审核最终 JSON 预案。`deprecated` 和 `archived` 不参与重新整理；它们只在历史审计和图谱查询中作为 provenance 使用。

## MVP 推进顺序

1. 新增数据库字段和 `memory_edges` / `sleep_sessions`。
2. Hub 实现候选选择 API，只返回候选，不生成预案。
3. 定义并校验 `memory_sleep_plan.v1` JSON schema。
4. 实现客户端生成预案提交和 apply。
5. CLI 增加 `echome sleep candidates/submit/apply`。
6. MCP 增加 sleep tools，供强 AI 生成 text/json proposal。
7. 再实现服务端生成预案。
8. 最后考虑定期自动 sleep。

第一版验收标准：

- 用户可以手动拉取当前 scope 下全部 eligible memories；如果数量多，可以分页，但最终必须 `has_more=false`。
- 客户端 AI 生成文本预案和 JSON 预案。
- 用户确认后提交 JSON 预案。
- 服务端校验并执行：
  - 新增 1-3 条深度记忆。
  - 旧记忆进入 `archived` 或 `deprecated`。
  - 写入 `derived_from` / `superseded_by` 关系。
- 普通检索不再返回归档记忆。
