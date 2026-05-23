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
