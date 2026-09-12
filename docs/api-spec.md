# EchoMe Hub REST API 规范

## 1. 概览

- **Base URL**: `https://<your-domain>/api/v1`
- **认证**: `Authorization: Bearer <token>`
- **内容格式**: JSON (`Content-Type: application/json`)
- **版本**: v1 (URL path versioning)

本文按 2026-09-12 当前源码校准，JSON 响应可省略部分可选字段。完整 schema 见 Hub 的 `/openapi.json` 和 [schemas](../hub/app/schemas/)；路由挂载以 [main.py](../hub/app/main.py) 为准。基础 `/health` 位于 API 前缀之外。

## 2. 认证

当前支持 GitHub OAuth、JWT 与按用户隔离的数据访问：

| Method | Endpoint | 说明 |
|---|---|---|
| GET | `/auth/github` | 返回 GitHub 授权 URL：`{"url": "..."}` |
| GET | `/auth/github/callback?code=...` | 用 OAuth code 换取 EchoMe JWT 和用户信息 |
| GET | `/auth/me` | 用当前 Bearer JWT 获取用户信息 |
| POST | `/auth/refresh` | 刷新当前用户 JWT |

callback / refresh 返回 `access_token`、`token_type`、`expires_in`（秒）和 `user`。`GET /auth/me` 响应示例：

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "github_id": 12345,
  "username": "example-user",
  "email": null,
  "avatar_url": null,
  "role": "user",
  "created_at": "2026-09-01T10:00:00Z",
  "last_login_at": "2026-09-12T10:00:00Z"
}
```

不存在 `POST /auth/token`。旧静态 token 兼容不能代替当前的用户登录与 JWT 流程。

---

## 3. 记忆 CRUD

### GET /memories

列出记忆（支持过滤和分页）。类型使用 [记忆模型](memory-model.md) 中的 10 种规范值。

**Query Parameters**:
| 参数 | 类型 | 必选 | 说明 |
|---|---|---|---|
| type | string | 否 | 按 type 过滤 |
| layer | string | 否 | L0/L1/L2 |
| status | string | 否 | active/ai_review/pending/deprecated/archived；省略时返回 active + ai_review |
| tags | string | 否 | 逗号分隔，AND 匹配 |
| project_id | string | 否 | 过滤 scope 包含该项目的记忆 |
| query | string | 否 | 对标题、正文和标签做轻量词法过滤 |
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
      "content": "所有 PR 的标题必须以 `[JIRA-XXX]` 工单号开头...",
      "type": "method",
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
  "type": "method",
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
  "type": "method",
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

**Request Body**: `title/content/type/layer/priority/tags/status/scope/source` 必填，`visibility` 默认 `private`；以 `MemoryUpdate` schema 为准。

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

语义 + 词法混合搜索，默认检索 active + ai_review；embedding 不可用时可降级为词法召回。`top_k` 默认 5、最大 20，`min_score` 默认 0.3。

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
      "type": "method",
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

批量提交 JSON 记忆到 Hub。REST 接口已实现；文件式 `echome push` 命令仍未实现，不能据此假定本地 vault 会自动上传或具备冲突合并。

**Request Body**:
```json
{
  "memories": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "...",
      "content": "...",
      "type": "method",
      "layer": "L0",
      "priority": 9,
      "tags": ["git"],
      "status": "active",
      "scope": {"global": true, "projects": [], "exclude_projects": []},
      "source": "manual",
      "updated_at": "2026-05-21T10:00:00Z"
    }
  ],
  "client_info": "echome/1.8.0 linux"
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

从 Hub 获取记忆 JSON，支持 `since` 增量过滤；接口本身不写本地文件。文件式 `echome pull` 命令仍未实现。

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
  "memories": [],
  "total": 0,
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
  "kind": "repository",
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

`kind` 可为 `repository`（默认，兼容旧客户端）或 `workspace`。存在 composition
历史的项目不可删除；存在 active relation 时必须先归档 relation，才能更改 kind。

---

## 7. 审核队列（AI 写入）

### GET /review/pending

默认返回 `ai_review`，可传 `status=pending` 查看旧严格审核队列；支持 `offset` 和 `limit`。响应为 `MemoryListResponse`，与 `GET /memories` 的分页结构相同。

条目使用 `layer`、`status`、`source` 和 `scope` 等 Memory 字段；没有独立的 `suggested_layer` 或 `ai_context` 响应字段。`suggested_layer` 是 MCP 写入参数，写入后存为 Memory 的 `layer`。

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

### POST /sync/render

根据目标 CLI 和项目，渲染应该注入的内容。省略 `layer` 时，全局选择全局 L0，带项目时选择全局 L0 + 全局或项目匹配的 L1；有效状态为 active + ai_review。显式 `layer` 会覆盖默认层选择。

正文超出预算时跳过条目，不自动降级 layer。最终 `token_count` 还包含引导和 marker，不能把配置的正文预算当作完整输出硬上限。`output_usage` 给出含正文、引导与 marker 的完整文本 UTF-8 字节 token 上界。项目排除规则与 Context Compiler 一致；全局渲染省略带项目排除的条件规则，workspace 继承仍仅用于 Context Compiler，详见 [记忆模型](memory-model.md)。

**Request Body**:
```json
{
  "target": "claude",
  "project_id": "qzhqzh/EchoMe",
  "layer": null,
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

### GET /health（无 `/api/v1` 前缀）

基础存活检查；不实际探测数据库或 embedding 服务。依赖健康、schema 与 feature flags 使用 `GET /api/v1/context/runtime/health`。

```json
{
  "status": "ok",
  "version": "1.8.0",
  "embedding_model": "BAAI/bge-m3"
}
```

---

## 10. 错误格式

普通 REST 路由主要使用 FastAPI 的 `detail` 格式；例如资源不存在：

```json
{
  "detail": "Memory not found"
}
```

请求 schema 校验失败通常为 `422`，`detail` 是包含字段位置和错误信息的数组。Context Runtime 与 MCP 的结构化错误使用 `echome.error.v1`，不能假定所有历史 REST 路由都已采用该 envelope。

**HTTP Status Codes**:
| Code | 场景 |
|---|---|
| 400 | 无效业务参数或操作 |
| 401 | Token 无效或缺失 |
| 404 | 资源不存在 |
| 409 | 项目身份、来源版本、预览确认或幂等请求冲突 |
| 422 | 请求 schema 校验失败或内容安全校验拒绝 |
| 500 | 服务端错误 |

---

## 11. Rate Limiting

限流按已配置的路由装饰器生效，基于客户端 IP 地址。超限时返回 `429 Too Many Requests`；不能仅凭 `RATE_DEFAULT` 常量认定每个路由都已启用限流。

### 限制规则

| 端点 | 限制 | 说明 |
|------|------|------|
| `GET /auth/github/callback` | 10 次/分钟 | 防止 OAuth code 暴力尝试 |
| `POST /memories` | 30 次/分钟 | 记忆创建写入限制 |
| `POST /memories/search` | 60 次/分钟 | 搜索限制（稍宽松） |
| `POST /sync/push` | 10 次/分钟 | 批量同步不需要太频繁 |
| 使用 `RATE_DEFAULT` 的端点 | 120 次/分钟 | 是否启用以各路由装饰器为准 |

### 响应 Header

当前 limiter 未启用统一的限流响应 header，不能依赖每个响应都有 `X-RateLimit-*` 字段。

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
| `content` | 最长 100,000 字符（按字符计，不是 token） | 记忆正文 |
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
| `POST` | `/api/v1/project-knowledge/views/reflect/prepare` | 只读准备可引用的项目证据及服务端来源指纹 |
| `POST` | `/api/v1/project-knowledge/views/reflect/submit` | 校验来源未变化和逐条 claim 证据后新增派生 view |

`context` 请求支持 `task`、`changed_paths`、`mode`、`token_budget`、`as_of`、`valid_at`、
`record_run` 和 `shadow`。`shadow=true` 返回旧检索结果，只旁路记录编译器差异。

Reflect `prepare` 接受 `project_id`、`query`、可选 `changed_paths`、`limit`、`token_budget`
和 `supersedes_id`，返回 `source_watermark` 与提交契约。`submit` 必须携带同一 watermark、
至少一条带 `memory/constraint/artifact/event` 引用的 claim，以及 `idempotency_key`；成功返回
`201`，来源变化或幂等键复用冲突返回 `409`，敏感内容或无效请求返回 `422`。既有
`POST /project-knowledge/views` 继续接受 `refresh_mode=derived` 以保持 REST v1 兼容，但此类
view 只使用旧的 artifact-ID freshness 契约；新客户端应使用 Reflect 获得逐来源版本校验。

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

`POST /context` 支持 `task`、`project_hint`、`project_hints`、`changed_paths`、`mode`、`token_budget`、
`limit`、`as_of`、`valid_at`、`request_id`、`client`、`client_version` 和 `policy_mode`。`mode=auto`
在有项目提示时解析 canonical project；没有项目提示时走 bounded personal memory route。
当前 personal route 使用共享的有界 Memory 混合召回（向量 + 词法），embedding 不可用时降级为词法；它不等同于项目 Context Compiler 的图/时间多路召回。

`project_hints` 最多接收 10 个额外身份信号。精确解析失败后，Hub 会执行无向量、可解释的候选发现：
唯一高置信候选只用于本次只读 context；歧义或无候选时返回 `scope=project_resolution`、候选及
`next_actions`，而不是终止性 404。该流程不会自动写 alias 或创建项目。
未解析请求没有生成可用 context，因此不返回 `completion_contract`；启用 `record_run` 时会以
`error_code=PROJECT_RESOLUTION_REQUIRED` 记录诊断 run，便于区分身份恢复与 Hub/编译故障。

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
| `POST` | `/api/v1/projects/discover` | 对最多 10 个身份信号做只读候选发现，返回匹配依据、置信度、workspace 父级和安全下一步 |
| `PATCH` | `/api/v1/projects/git-identity` | 预览或应用既有项目的主 Git remote 与 active Git remote aliases |
| `GET` | `/api/v1/projects/aliases` | 查询 proposed/active aliases |
| `POST` | `/api/v1/projects/aliases` | 创建 proposed alias；不能在创建时直接激活 |
| `PUT` | `/api/v1/projects/aliases` | 原子、幂等地确保一个 canonical project 的一组 active aliases |
| `PATCH` | `/api/v1/projects/aliases/{alias_id}` | 显式激活、拒绝或归档 alias |

Alias 不搬迁或覆盖历史数据。读路径可展开 active 的历史 scope；写路径把已知 active alias 统一为
canonical project，无法解析的旧 scope 为兼容历史客户端而原样保留。
`/projects/git-identity` 只接受主 remote 和 Git remote aliases，不覆盖名称、描述、kind 或
`path_patterns`。`confirmed=false` 返回服务端预览与 `confirmation_token` 且不写入；
`confirmed=true` 必须回传该 token 才会原子应用。项目 remote 或 alias 状态在两次调用之间变化时，
旧 token 失效并返回 `409 PROJECT_GIT_IDENTITY_PREVIEW_REQUIRED`。
SCP 风格 SSH、`ssh://` 与 HTTPS 使用同一 `host/owner/repo` 规范化值；等价地址幂等，已属于其他
canonical project 的 identity 返回 `409 PROJECT_GIT_IDENTITY_CONFLICT`。
替换主 remote 不会静默保留旧值；若旧地址仍需识别，调用方必须把它显式放入
`git_remote_aliases`，并由预览展示这项变化。
`PUT /projects/aliases` 不修改项目主 remote，只创建、激活或复用 active aliases；提交前会检查整批
alias 是否已被其他 canonical project 或其主 identity 占用，冲突时整批不写入并返回
`409 PROJECT_ALIAS_CONFLICT`。该接口用于 Agent 在唯一候选恢复时静默固化身份，最多一次确保 10 项。
`/projects/resolve` 的歧义解析返回 `409`，未知项目返回 `404`；`/context` 和
`/projects/discover` 则返回非终止性的结构化恢复结果。跨用户 alias 不可见。

### Composite Project Workspaces

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/projects/relations` | 查询 active workspace/repository 关系，可按 `project_id` 过滤 |
| `POST` | `/api/v1/projects/relations` | 创建 `workspace --contains--> repository` 关系 |
| `PATCH` | `/api/v1/projects/relations/{relation_id}` | 归档或重新激活关系，保留历史 |

Repository context 会组合 global、父 workspace 和当前 repository 的记忆，但不会加载 sibling
repository。Workspace context 默认只加载自身记忆；仅当 `changed_paths` 命中子项目的
`path_patterns` 或 active path alias 时，才加载该子项目记忆。Project Knowledge 的 constraint、
artifact、chunk 和 view 仍保持 exact-project scope。

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

## 14. 完整输出预算与诊断

`POST /api/v1/context` 的默认响应仍为完整模式，新增 `output_usage`。请求可设置 `output_mode="compact"`，用 `max_output_tokens` 指定单份最终 JSON 上限；省略上限时使用 token_budget。正文的 `token_used` 保持原含义，不当作完整响应 token 数。

`output_usage` 使用 `utf8_bytes_upper_bound`，覆盖整个紧凑 JSON，包括统计字段本身。必要规则或 completion 放不下时返回 `echome.error.v1` / `OUTPUT_BUDGET_TOO_SMALL`；该 run 记为 failed，不允许报告成功 outcome。保留字段、裁剪规则与 MCP 双表示口径详见 [MCP 规范](mcp-spec.md)。

`GET /api/v1/context/runs/{run_id}` 返回同一用户的已记录 run、selected IDs 与完整检索 trace；不属于当前用户或不存在的 run 返回 404。未记录的请求没有诊断 URL，可重新请求 full 模式。
