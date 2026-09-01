# EchoMe MCP Server 规范

## 1. 概览

EchoMe MCP Server 是运行在用户本地的进程，向 AI CLI (Claude Code, Codex CLI 等) 暴露用户记忆的查询和写入能力。

**运行方式**：
```bash
echome mcp serve           # stdio 模式（默认，适合 Claude Code）
echome mcp serve --http --host 127.0.0.1 --port 20003
                           # 本地 Streamable HTTP 模式
```

**注册方式（Claude Code）**：

`~/.claude/mcp.json`:
```json
{
  "mcpServers": {
    "echome": {
      "command": "echome",
      "args": ["mcp", "serve"],
      "env": {}
    }
  }
}
```

**注册方式（Codex CLI）**：

现代 Codex CLI 使用 `~/.codex/config.toml`：

```toml
[mcp_servers.echome]
command = "echome"
args = ["mcp", "serve"]
enabled = true
```

EchoMe 仍会兼容写入 `~/.codex/mcp.json`，但 Codex 是否读取它取决于客户端版本。

## 2. MCP 协议版本

- Protocol: MCP 2024-11-05
- Transport: stdio (默认) / Streamable HTTP

## 3. Server Info

```json
{
  "name": "echome",
  "version": "0.1.0",
  "description": "Personal memory and context layer - search and manage your knowledge, preferences, and workflow rules"
}
```

## 4. Tools

### 4.0 v1.8 默认入口与运行契约

- `echome_context`：任务默认入口；可同时推断当前 Git remote 与 repository root，解析 canonical project，并返回统一 context envelope。
- `echome_runtime_health`：检查 MCP/Hub/schema 版本、profile、数据库、embedding、feature flags 和缓存边界；传
  `include_policy_readiness=true` 时返回只读策略门禁。
- `echome_context_outcome`：对 completed、non-shadow Context Run 追加幂等结果信号；可附带显式
  `policy_effect`，缺失信号不等于失败。
- `echome_update_project_git_identity`：为已确认的既有项目生成服务端变更预览；用户确认后必须把预览返回的
  `confirmation_token` 原样回传，才能补录主 Git remote 或 active Git remote aliases。状态变化会使旧 token 失效。
  替换主 remote 时不会自动保留旧地址；仍需兼容时应在同一预览中显式提交旧地址 alias。
- `echome_create_project`：项目发现为 `not_found` 时直接静默创建；只有一个可复用候选时不创建重复项目，
  而是原子补录 active aliases。`confirmed_new_project` 仅为旧客户端保留，不再作为创建门禁；多个冲突候选仍停止。
- 新安装配置默认显式使用 `core`：暴露 capability、context、health、graph explain、remember、outcome、memory feedback、安全项目创建与 Git identity 维护等 10 个高频入口。
- `ECHOME_MCP_PROFILE=full`：显式启用 summary-first、Project Knowledge、Sleep 等完整专业工具集。
- 为保持升级兼容，未配置 `ECHOME_MCP_PROFILE` 的历史客户端继续使用 `full`。

`echome_context` Hub 不可达时，只能返回完全相同请求键的 last-known-good 只读缓存，并显式设置
`runtime.degraded=true` 和 `fallback=last_known_good`。缓存目录权限为 `0700`，文件为 `0600`；
缓存正文使用独立生成的本机随机密钥执行 AES-256-GCM 加密，认证 token 只参与 Hub/账号 namespace，
默认最多保留 7 天；没有 token 时不写缓存。写操作不进入离线队列，也不会伪成功。

MCP-facing 错误使用 `echome.error.v1`，至少包含 `code`、非空 `message`、`retryable`、
`request_id`、`degraded` 和 `suggested_action`。

项目身份恢复使用 `echome.project-resolution.v1`：

- `resolved`：精确匹配，或唯一且高置信的确定性候选；候选可用于本次 context。
- 单一 `needs_confirmation`：优先返回 `create_or_attach_project`，Agent 可直接调用 `echome_create_project`
  静默补 active aliases，无须询问用户；多个候选的 `ambiguous` 仍必须继续选择或询问。
- `not_found`：返回 `echome_create_project` 参数预案，Agent 直接静默创建，无须用户显式确认。
- 已 `resolved` 的单一候选由 Git remote 线索恢复、但项目尚未登记主 identity 时，会返回
  `confirm_then_update_project_git_identity`；Agent 必须先以 `confirmed=false` 展示服务端预览。
- `scope=project_resolution` 是正常 MCP 结果，不设置 protocol error，也不进入 last-known-good 缓存。
- 因为尚未生成可使用的 context，该结果不返回 completion contract；Hub 可将诊断 run 记为
  `failed/PROJECT_RESOLUTION_REQUIRED`，与传输或编译错误分开统计。

v1.7 延续 `echome_context` 与 `echome_project_context` 的 `policy_mode`：

- 默认 `shadow`，返回 reliability、intervention 和 policy trace，但不改变选入结果。
- `off` 跳过策略计算。
- `enforce` 还需要 Hub 的 `ECHOME_CONTEXT_POLICY_ENFORCE_ENABLED` 显式开启，否则回退 shadow。

`echome_capabilities` 当前契约版本为 `echome.capabilities.v9`。core profile 包含 10 个工具；AI 可通过
`echome_runtime_health(include_policy_readiness=true)` 读取校准门禁。
`echome_sleep_candidates` 默认返回
`memory_sleep_plan.v2`，也可显式请求 v1；v2 proposal 由 Hub 生成 server-owned simulation，并在
apply 前重新验证。

full profile 还提供 evidence-backed Reflect：

- `echome_reflect_prepare` 只读返回完整来源集合、相关事件、当前视图和服务端 freshness fingerprint。
- `echome_reflect_submit` 要求每条 claim 引用 prepare 返回的来源 ID，并提供幂等键；来源变化或越界引用会被 Hub 拒绝。
- Hub 只从已验证 claims 渲染派生正文，并由服务端写入 producer；客户端不能提交独立的无证据正文。
- submit 只新增派生 `knowledge_view`，不会修改 Memory、Constraint、Artifact 或 Event。

readiness 的 `eligible_for_canary` 只表示样本门槛满足。客户端不得把它解释为已经开启 enforce，
也不得自动修改 Hub feature flag。

### 4.1 echome_search_summary

**描述**: 返回紧凑的记忆摘要索引，用于先浏览候选记忆，再按 UUID 精读。适合项目记忆较多、问题范围较宽、或语义搜索 top-k 可能遗漏相关记忆的场景。

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string", "description": "可选，按标题/内容/tag 做轻量过滤"},
    "type": {"type": "string", "description": "可选，按记忆类型过滤"},
    "status": {"type": "string", "default": "active", "description": "记忆状态过滤"},
    "project_id": {"type": "string", "description": "可选，按项目过滤"},
    "limit": {"type": "integer", "default": 30},
    "offset": {"type": "integer", "default": 0}
  }
}
```

**Output**: 返回编号、UUID、title、type、layer、priority、tags、updated_at 和简短摘要。AI 应从摘要中选择相关 UUID，再调用 `echome_get_memories` 获取全文。

---

### 4.2 echome_get_memories

**描述**: 按 UUID 列表批量获取多条记忆全文。用于 `echome_search_summary` 之后的精读阶段。

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "memory_ids": {
      "type": "array",
      "items": {"type": "string"},
      "description": "从 echome_search_summary 中选择的记忆 UUID"
    }
  },
  "required": ["memory_ids"]
}
```

**Output**: 返回选中记忆的完整内容。

---

### 4.3 echome_search / memory_search

**描述**: 搜索用户的记忆和知识。当需要了解用户的工作流规范、技术偏好、项目背景、过往决策时调用此工具。

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "搜索关键词或自然语言问题，如 'PR 提交规范' 或 '为什么选择 FastAPI'"
    },
    "type": {
      "type": "string",
      "enum": ["persona", "workflow", "tech", "constraint", "snippet", "decision", "knowledge", "interaction", "project"],
      "description": "可选，按记忆类型过滤"
    },
    "project_id": {
      "type": "string",
      "description": "可选，按项目过滤。如 'qzhqzh/EchoMe'"
    },
    "top_k": {
      "type": "integer",
      "default": 5,
      "description": "返回结果数量，默认 5"
    }
  },
  "required": ["query"]
}
```

**Output**: 返回匹配的记忆列表，每条包含 title、content、type、tags、score。

**示例调用**:
```json
{
  "query": "提交 PR 有什么要求",
  "type": "workflow"
}
```

**示例输出**:
```
找到 2 条相关记忆：

## 1. PR 必须带工单号 (score: 0.94)
类型: workflow | 标签: git, pr, ticket

所有 PR 的标题必须以 `[JIRA-XXX]` 工单号开头。
如果当前 branch 名包含工单号，默认从 branch 提取；否则需要先问用户。

## 2. PR 合并要求 (score: 0.87)
类型: workflow | 标签: git, pr, review

合并 PR 前必须满足：
- 至少 1 个 reviewer approve
- CI 全部通过
- 无 unresolved comments
```

---

### 4.4 echome_get

**描述**: 按 ID 获取单条记忆的完整内容。

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "memory_id": {
      "type": "string",
      "description": "记忆的 UUID"
    }
  },
  "required": ["memory_id"]
}
```

---

### 4.5 echome_list_by_type

**描述**: 列出指定类型的所有记忆标题。用于浏览用户有哪些记忆。

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "type": {
      "type": "string",
      "enum": ["persona", "workflow", "tech", "constraint", "snippet", "decision", "knowledge", "interaction", "project"],
      "description": "记忆类型"
    },
    "status": {
      "type": "string",
      "enum": ["active", "ai_review", "pending", "deprecated"],
      "default": "active"
    }
  },
  "required": ["type"]
}
```

---

### 4.6 echome_remember / memory_remember

**描述**: 将新知识作为 ai_review 记忆写入用户的记忆库。Agent 可以在用户明确要求时调用，也可以在观察到稳定偏好、项目决策、工作流约定、反复纠正或可复用上下文时主动调用。ai_review 记忆会立即参与后续检索；用户之后可用 `echome review` 将其提升为 active 或归档。

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "title": {
      "type": "string",
      "description": "记忆标题，简明扼要"
    },
    "content": {
      "type": "string",
      "description": "记忆内容，详细描述规则/知识/偏好"
    },
    "type": {
      "type": "string",
      "enum": ["persona", "workflow", "tech", "constraint", "snippet", "decision", "knowledge", "interaction", "project"],
      "description": "记忆类型"
    },
    "tags": {
      "type": "array",
      "items": {"type": "string"},
      "description": "标签列表"
    },
    "suggested_layer": {
      "type": "string",
      "enum": ["L0", "L1", "L2"],
      "default": "L2",
      "description": "建议的加载层级"
    },
    "project_id": {
      "type": "string",
      "description": "如果是项目专属记忆，指定项目 ID"
    }
  },
  "required": ["title", "content", "type", "tags"]
}
```

**Output**:
```
✓ 记忆已保存（ai_review）

标题: 用户偏好 ruff 作为 Python linter
类型: tech
状态: ai_review（AI 可立即检索；用户可通过 `echome review` 提升或归档）
```

**重要约束**:
- 可以主动写入 ai_review 记忆，但必须是可复用、稳定、高置信度的信息
- 用户明确表达"记住/以后/总是/永远"等意图时必须调用
- 不要写入密码/密钥/隐私敏感内容、一次性临时事实、低置信度猜测
- 默认写入 ai_review，会立即参与后续 AI 检索；用户通过 `echome review` 做事后清理或提升为 active

---

### 4.7 echome_get_project_context

**描述**: 获取当前项目的完整上下文，包括项目描述、技术栈、注意事项等。

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "project_id": {
      "type": "string",
      "description": "项目 ID，如 'qzhqzh/EchoMe'。如果不提供，尝试从当前 git remote 推断"
    }
  },
  "required": []
}
```

**Output**: 返回项目相关的所有 active 记忆汇总。

---

## 5. Resources（可选，远期）

| URI | 描述 |
|---|---|
| `echome://profile` | 用户个人画像 |
| `echome://projects` | 项目列表 |
| `echome://project/{id}` | 单个项目上下文 |

> MVP 阶段以 Tools 为主，Resources 后续按需添加。

## 6. Prompts（Slash Commands）

### /echome-load

**描述**: 手动触发加载当前项目的完整上下文到对话中。

**Arguments**:
```json
{
  "project_id": {
    "type": "string",
    "description": "项目 ID（可选，默认当前项目）"
  }
}
```

**行为**: 调用 echome_search + echome_get_project_context，把 L1 + L2 层相关记忆全部拉入。

---

### /echome-status

**描述**: 显示当前对话中已加载的 EchoMe 上下文状态。

---

## 7. AI 何时调用 MCP

这是 EchoMe 设计中最关键的问题。AI 不会自动加载 MCP 内容，需要通过以下机制引导：

### 7.1 L0 Preamble 引导（写在 CLAUDE.md 中）

```markdown
### 如何获取更多上下文
当你遇到以下情况时，必须先调用 EchoMe MCP 工具搜索：
1. 用户询问工作流规范（如何提 PR、如何写 commit）
2. 需要了解项目背景或历史决策
3. 用户提到"之前讨论过"、"按照惯例"等暗示已有上下文
4. 开始一个新任务前，查询是否有相关约束或偏好
5. 用户说"记住这个"、"以后都这样"时，调用 echome_remember
6. 观察到稳定偏好、项目决策、工作流约定、反复纠正或可复用上下文时，可以主动调用 echome_remember 写入 ai_review 记忆
```

### 7.2 触发时机总结

| 场景 | 触发的 Tool |
|---|---|
| 写 PR / commit | echome_search "PR 规范" |
| 开始新任务 | echome_get_project_context |
| 用户说"按老规矩" | echome_search + 相关上下文 |
| 用户说"记住/以后" | echome_remember |
| 观察到稳定偏好/决策/约定 | echome_remember（ai_review） |
| 技术选型问题 | echome_search "技术偏好" |
| 不确定项目约定 | echome_search |

### 7.3 不应调用的场景

- 纯知识性问答（AI 自己能回答的）
- 用户明确说"不用查了"
- 简单代码修改（无工作流约束涉及时）

## 8. 错误处理

MCP Tool 调用失败时返回：

```json
{
  "isError": true,
  "content": [
    {
      "type": "text",
      "text": "EchoMe Hub 连接失败，请检查网络或运行 `echome status`"
    }
  ]
}
```

**降级策略**：
- Hub 不可达 → 读取本地 ~/.echome/vault/ 缓存
- 本地缓存也没有 → 返回提示，不阻断对话

## 9. 安全考虑

- MCP Server 以用户身份运行，继承用户文件权限
- 不暴露 Hub token 给 AI（MCP Server 内部使用）
- echome_remember 写入的内容默认 ai_review，允许 AI 自主学习，同时保留人工事后纠偏
- 不支持删除操作（AI 不能删用户记忆）
- 内容不包含密码/密钥等敏感信息（CLI 层过滤）
