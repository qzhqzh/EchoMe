# EchoMe Hub REST API 规范

## 1. 概览

- **Base URL**: `https://<your-domain>/api/v1`
- **认证**: `Authorization: Bearer <token>`
- **内容格式**: JSON (`Content-Type: application/json`)
- **版本**: v1 (URL path versioning)

## 2. 认证

### POST /auth/token

验证 token 有效性并返回用户信息。

```http
POST /api/v1/auth/token
Authorization: Bearer <token>
```

**Response 200**:
```json
{
  "user_id": "default",
  "valid": true,
  "expires_at": null
}
```

> 单租户模式下 token 在服务端配置文件中定义，不提供注册/登录接口。

---

## 3. 记忆 CRUD

### GET /memories

列出记忆（支持过滤和分页）。

**Query Parameters**:
| 参数 | 类型 | 必选 | 说明 |
|---|---|---|---|
| type | string | 否 | 按 type 过滤 |
| layer | string | 否 | L0/L1/L2 |
| status | string | 否 | active/ai_review/pending/deprecated/archived，默认 active |
| tags | string | 否 | 逗号分隔，AND 匹配 |
| project_id | string | 否 | 过滤 scope 包含该项目的记忆 |
| offset | int | 否 | 分页偏移，默认 0 |
| limit | int | 否 | 每页数量，默认 50，最大 200 |

**Response 200**:
```json
{
  "total": 42,
  "offset": 0,
  "limit": 50,
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "PR 必须带工单号",
      "type": "workflow",
      "layer": "L0",
      "priority": 9,
      "tags": ["git", "pr", "ticket"],
      "status": "active",
      "scope": {
        "global": true,
        "projects": [],
        "exclude_projects": []
      },
      "source": "manual",
      "token_count": 85,
      "created_at": "2026-05-21T10:00:00Z",
      "updated_at": "2026-05-21T10:00:00Z"
    }
  ]
}
```

---

### GET /memories/{id}

获取单条记忆完整内容。

**Response 200**:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "PR 必须带工单号",
  "content": "所有 PR 的标题必须以 `[JIRA-XXX]` 工单号开头...",
  "type": "workflow",
  "layer": "L0",
  "priority": 9,
  "tags": ["git", "pr", "ticket"],
  "status": "active",
  "scope": {
    "global": true,
    "projects": [],
    "exclude_projects": []
  },
  "source": "manual",
  "token_count": 85,
  "created_at": "2026-05-21T10:00:00Z",
  "updated_at": "2026-05-21T10:00:00Z"
}
```

---

### POST /memories

创建新记忆。

**Request Body**:
```json
{
  "title": "PR 必须带工单号",
  "content": "所有 PR 的标题必须以 `[JIRA-XXX]` 工单号开头...",
  "type": "workflow",
  "layer": "L0",
  "priority": 9,
  "tags": ["git", "pr", "ticket"],
  "status": "active",
  "scope": {
    "global": true,
    "projects": [],
    "exclude_projects": []
  },
  "source": "manual"
}
```

**Response 201**:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "PR 必须带工单号",
  "token_count": 85,
  "created_at": "2026-05-21T10:00:00Z"
}
```

> Hub 在创建后异步计算 embedding。

---

### PUT /memories/{id}

更新记忆（全量替换）。

**Request Body**: 同 POST，所有字段必填。

**Response 200**: 返回更新后的完整记忆。

---

### PATCH /memories/{id}

部分更新记忆。

**Request Body**（只传需要修改的字段）:
```json
{
  "layer": "L1",
  "priority": 7
}
```

**Response 200**: 返回更新后的完整记忆。

---

### DELETE /memories/{id}

删除记忆（软删除，status → archived）。

**Response 204**: No Content

**Query Parameters**:
| 参数 | 类型 | 说明 |
|---|---|---|
| hard | bool | 如果 true，物理删除 |

---

## 4. 搜索

### POST /memories/search

语义 + 关键词混合搜索。

**Request Body**:
```json
{
  "query": "PR 提交时有什么规范",
  "type": null,
  "layer": null,
  "tags": [],
  "project_id": null,
  "top_k": 5,
  "min_score": 0.5
}
```

**Response 200**:
```json
{
  "results": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "PR 必须带工单号",
      "content": "所有 PR 的标题必须以...",
      "type": "workflow",
      "layer": "L0",
      "score": 0.92,
      "tags": ["git", "pr", "ticket"]
    }
  ],
  "total_searched": 42
}
```

---

## 5. 同步

### POST /sync/push

CLI 批量上传本地 vault 到 Hub。

**Request Body**:
```json
{
  "memories": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "...",
      "content": "...",
      "type": "workflow",
      "layer": "L0",
      "priority": 9,
      "tags": ["git"],
      "status": "active",
      "scope": {"global": true, "projects": [], "exclude_projects": []},
      "source": "manual",
      "updated_at": "2026-05-21T10:00:00Z"
    }
  ],
  "client_info": "echome/0.1.0 linux"
}
```

**Response 200**:
```json
{
  "created": 3,
  "updated": 2,
  "unchanged": 10,
  "conflicts": []
}
```

---

### POST /sync/pull

从 Hub 拉取最新记忆到本地。

**Request Body**:
```json
{
  "since": "2026-05-20T00:00:00Z",
  "include_pending": true
}
```

**Response 200**:
```json
{
  "memories": [...],
  "total": 15,
  "server_time": "2026-05-21T12:00:00Z"
}
```

---

## 6. 项目管理

### GET /projects

列出所有项目。

### POST /projects

创建项目。

**Request Body**:
```json
{
  "id": "qzhqzh/EchoMe",
  "name": "EchoMe",
  "description": "跨 AI 个人上下文同步层",
  "git_remote": "git@github.com:qzhqzh/EchoMe.git",
  "path_patterns": ["~/projects/EchoMe", "~/work/echome*"]
}
```

### GET /projects/{id}

获取项目详情。

### PUT /projects/{id}

更新项目。

### DELETE /projects/{id}

删除项目。

---

## 7. 审核队列（AI 写入）

### GET /review/pending

获取待审核记忆列表。

**Response 200**:
```json
{
  "items": [
    {
      "id": "...",
      "title": "用户偏好 ruff 作为 Python linter",
      "content": "...",
      "type": "tech",
      "suggested_layer": "L0",
      "source": "ai_suggested",
      "ai_context": "用户在对话中说：'以后所有 Python 项目都用 ruff'",
      "created_at": "2026-05-21T11:00:00Z"
    }
  ]
}
```

### POST /review/{id}/approve

确认记忆，status → active。

**Request Body**（可选修改）:
```json
{
  "layer": "L0",
  "priority": 8
}
```

### POST /review/{id}/reject

拒绝记忆，status → archived。

---

## 8. 渲染

### POST /render

根据目标 CLI 和项目，渲染应该注入的内容。

**Request Body**:
```json
{
  "target": "claude",
  "project_id": "qzhqzh/EchoMe",
  "layer": "L0",
  "format": "markdown"
}
```

**Response 200**:
```json
{
  "content": "<!-- echome:begin -->\n## EchoMe Context...\n<!-- echome:end -->",
  "token_count": 420,
  "memories_included": 8,
  "memories_truncated": 2
}
```

---

## 9. 健康检查

### GET /health

```json
{
  "status": "ok",
  "version": "0.1.0",
  "db": "connected",
  "embedding_model": "text-embedding-3-small"
}
```

---

## 10. 错误格式

所有错误返回统一格式：

```json
{
  "error": {
    "code": "MEMORY_NOT_FOUND",
    "message": "Memory with id xxx not found",
    "details": null
  }
}
```

**HTTP Status Codes**:
| Code | 场景 |
|---|---|
| 400 | 请求体校验失败 |
| 401 | Token 无效或缺失 |
| 404 | 资源不存在 |
| 409 | 冲突（如 push 时版本冲突） |
| 422 | 业务逻辑错误 |
| 500 | 服务端错误 |

---

## 11. Rate Limiting

所有 API 均有请求频率限制，基于客户端 IP 地址。超限时返回 `429 Too Many Requests`。

### 限制规则

| 端点 | 限制 | 说明 |
|------|------|------|
| `GET /auth/github/callback` | 10 次/分钟 | 防止 OAuth code 暴力尝试 |
| `POST /memories` | 30 次/分钟 | 记忆创建写入限制 |
| `POST /memories/search` | 60 次/分钟 | 搜索限制（稍宽松） |
| `POST /sync/push` | 10 次/分钟 | 批量同步不需要太频繁 |
| 其他所有端点 | 120 次/分钟 | 通用默认限制 |

### 响应 Header

每个响应都包含以下 header：

```
X-RateLimit-Limit: 30
X-RateLimit-Remaining: 29
X-RateLimit-Reset: 1716300060
```

### 超限响应

```json
{
  "error": "Rate limit exceeded: 30 per 1 minute"
}
```

HTTP Status: `429 Too Many Requests`

### 内容大小限制

| 字段 | 限制 | 说明 |
|------|------|------|
| `title` | 最长 256 字符 | 记忆标题 |
| `content` | 最长 100,000 字符 (~25,000 汉字) | 记忆正文 |
| `tags` | 最多 20 个 | 标签数量 |

---

## 12. Project Knowledge API

Project Knowledge 与个人 Memory 独立存储，并通过 Project Context Compiler 在查询时组合。
完整的数据模型、状态语义和工作流见 `docs/project-knowledge.md`。

### Project Context

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/project-knowledge/context` | 按任务编译约束、制品证据和项目记忆；默认记录一次 `ContextRun` |
| `POST` | `/api/v1/project-knowledge/impact` | 沿约束图分析变更影响 |
| `POST` | `/api/v1/project-knowledge/preflight` | 编辑、测试、提交或部署前的只读证据检查 |
| `GET` | `/api/v1/project-knowledge/context-runs` | 查询检索运行与选择轨迹 |

`context` 请求支持 `task`、`changed_paths`、`mode`、`token_budget`、`as_of`、`valid_at`、
`record_run` 和 `shadow`。`shadow=true` 返回旧检索结果，只旁路记录编译器差异。

### Artifacts And Constraints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/project-knowledge/artifacts/sync/check` | 比较 SHA-256 manifest，返回需要上传的制品 |
| `POST` | `/api/v1/project-knowledge/artifacts/sync/apply` | 增量写入不可变制品 revision |
| `POST` | `/api/v1/project-knowledge/artifacts/chunks/rebuild` | 幂等重建可派生的分块及向量索引 |
| `GET` | `/api/v1/project-knowledge/artifacts/chunks` | 分页读取分块与向量状态 |
| `POST` | `/api/v1/project-knowledge/constraints` | 新增 proposed constraint |
| `PATCH` | `/api/v1/project-knowledge/constraints/{id}` | 更新元数据；事实字段变化时创建新版本并保留旧版本 |
| `POST` | `/api/v1/project-knowledge/edges` | 新增约束关系 |
| `POST` | `/api/v1/project-knowledge/evidence` | 关联约束与制品证据 |

### Events, Quality And Automation

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/project-knowledge/events` | 追加项目事件；提供 `idempotency_key` 时可安全重试 |
| `GET` | `/api/v1/project-knowledge/events` | 查询 append-only 项目事件 |
| `GET` | `/api/v1/project-knowledge/eval/cases` | 读取固定 Project Context 质量用例 |
| `POST` | `/api/v1/project-knowledge/eval/evaluate` | 调试客户端提交的固定用例结果；不进入自动化门禁 |
| `POST` | `/api/v1/project-knowledge/eval/snapshots` | Hub 在服务端运行完整固定用例并保存可信质量快照 |
| `GET` | `/api/v1/project-knowledge/eval/snapshots` | 查询质量快照和连续门禁状态 |
| `POST` | `/api/v1/project-knowledge/eval/scale` | 按记忆规模评估预算内可靠性与退化拐点 |
| `GET` | `/api/v1/project-knowledge/automation/gate` | 查看连续质量门禁与功能开关状态 |
| `POST` | `/api/v1/project-knowledge/automation/proposals/run` | 门禁通过后生成 proposal；不会自动 apply |

自动化由 `ECHOME_PROJECT_AUTOMATION_ENABLED` 控制，默认 `false`。即使开启且质量门禁通过，
也只允许生成 pending proposal，不会覆盖或删除 Memory、Artifact revision 或 Constraint version。
客户端不能向质量快照端点提交检索结果；连续门禁只接受 Hub 自己执行并记录的快照。

---

## 13. Reliable Context Runtime

### Unified Context And Health

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/context` | 单入口获取 personal 或 canonical project context；返回 evidence、conflicts、unknowns、answerability 与 runtime metadata |
| `GET` | `/api/v1/context/runtime/health` | 检查认证、Hub、数据库、Alembic revision、embedding 与 feature flags |

`POST /context` 支持 `task`、`project_hint`、`changed_paths`、`mode`、`token_budget`、
`limit`、`as_of`、`valid_at`、`request_id`、`client`、`client_version` 和 `policy_mode`。`mode=auto`
在有项目提示时解析 canonical project；没有项目提示时走 bounded personal memory route。
当前 personal route 使用有界词法召回；图与时间多路召回尚未进入本轮发布候选。

`policy_mode` 默认为 `shadow`，会返回 reliability/intervention 与 would-exclude trace，但不改变结果。
`enforce` 只有在服务端 feature flag 开启时生效，否则回退 shadow。

### Reliability And Replay

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/observability/reliability-assessments` | 查询可重建可靠性快照，不返回记忆正文 |
| `GET` | `/api/v1/observability/context-policy/readiness` | 从 shadow runs 与显式 policy effects 派生只读 canary readiness；不会开启 enforce |
| `POST` | `/api/v1/retrieval-debug/replay` | 只读重放真实 Retrieval Logs 并报告 expected-rank 回归 |

### Canonical Project Aliases

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/projects/resolve` | 按 ID、name、Git remote、path 或 client hint 精确解析 canonical project |
| `GET` | `/api/v1/projects/aliases` | 查询 proposed/active aliases |
| `POST` | `/api/v1/projects/aliases` | 创建 proposed alias；不能在创建时直接激活 |
| `PATCH` | `/api/v1/projects/aliases/{alias_id}` | 显式激活、拒绝或归档 alias |

Alias 不搬迁或覆盖历史数据。读路径可展开 active 的历史 scope；写路径把已知 active alias 统一为
canonical project，无法解析的旧 scope 为兼容历史客户端而原样保留。
歧义解析返回 `409`，未知项目返回 `404`，跨用户 alias 不可见。

### Context Outcomes

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/context-outcomes` | 为 completed、non-shadow Context Run 追加一个显式结果信号 |
| `POST` | `/api/v1/context-outcomes/batch` | 最多批量追加 50 个幂等结果信号 |
| `GET` | `/api/v1/context-outcomes?context_run_id=...` | 读取某次 Context Run 的 append-only outcomes |

Outcome 可为 `success | partial | failed | corrected | no_signal`，并可选附带
`policy_effect=helpful | neutral | harmful | uncertain`。`corrected` 和 `harmful` 必须带 note；
policy effect 只接受带有 Context Policy trace 的运行。
system/CI 信号必须关联属于同一用户和项目的 Project Event。未提交 outcome 表示 unknown，不能推断为失败。

Readiness 只统计指定窗口内 completed、effective shadow 且 trace schema 完整的 Context Runs；enforce、off
和无 policy trace 运行不会进入分母。畸形 policy trace 会计入 `invalid_policy_trace_runs` 并强制进入 hold。
helpful/harmful 与 coverage 只统计实际 intervention runs；截断证据窗口进入 hold。所有阈值使用未舍入比例
判定，响应中的展示精度不会放宽门禁。
结果只有 `insufficient_data | hold | eligible_for_canary`，并固定返回
`auto_enforce=false`。它是发布证据，不是策略开关。
