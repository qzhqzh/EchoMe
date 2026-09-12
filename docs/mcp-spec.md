# EchoMe MCP Server 规范

## 1. 概览

EchoMe MCP Server 向 AI 客户端暴露个人记忆、项目上下文、证据查询和受控写入能力，通常作为本地 stdio 进程运行，也支持 Streamable HTTP。

本文按 2026-09-12 当前源码校准；完整工具 schema 以 [server.py](../echome_mcp/server.py) 和客户端实际的 `tools/list` 为准。包版本、capabilities 版本和 MCP 协议版本是三个不同概念，部署可能尚未加载主线能力。

**运行方式**：
```bash
echome mcp serve           # stdio 模式（默认，适合 Claude Code）
echome mcp serve --http --host 127.0.0.1 --port 20003
                           # 本地 Streamable HTTP 模式
```

**注册方式（Claude Code）**：

`echome mcp install` 优先通过 `claude mcp add --scope user` 注册；文件回退位置为 `~/.claude.json` 的 `mcpServers`：
```json
{
  "mcpServers": {
    "echome": {
      "command": "echome",
      "args": ["mcp", "serve"],
      "env": {"ECHOME_MCP_PROFILE": "core"}
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
env = { ECHOME_MCP_PROFILE = "core" }
enabled = true
```

EchoMe 仍会兼容写入 `~/.codex/mcp.json`，但 Codex 是否读取它取决于客户端版本。

## 2. MCP 协议版本

- Protocol: 由当前安装的 MCP SDK 与客户端在 `initialize` 时协商，不固定为早期的 `2024-11-05`
- Transport: stdio (默认) / Streamable HTTP

## 3. Server Info

```json
{
  "name": "echome",
  "version": "1.9.0"
}
```

## 4. Tools

### 4.0 当前源码的默认入口与运行契约

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

当前 `echome_context` 与 `echome_project_context` 支持 `policy_mode`：

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

下列 4.1-4.5、4.7 是 `full` profile 的专业/兼容工具；4.6 的 `echome_remember` 同时在 `core` 中提供。默认任务查询使用 `echome_context`，不要在 core 客户端里要求调用未暴露的工具。

### 完整输出预算

`token_budget/token_used` 保持既有内容选择口径。`echome_context` 新增 `output_mode="compact"` 与 `max_output_tokens`（256–200000，省略时沿用 token_budget）；默认 `full` 保留既有字段。

<!-- echome-contract: mcp echome_context -->
```json
{
  "task": "检查当前项目的兼容性约束",
  "project_hint": "qzhqzh/EchoMe",
  "output_mode": "compact",
  "max_output_tokens": 6000
}
```

compact 省略重复诊断，必要时整条移除可选内容，并通过 `omitted_counts`、unknowns 与 answerability 显示不足。保留 guardrails、constraints、冲突、preflight 的风险/要求、来源 ID、策略干预和 completion contract；必要结构仍放不下时返回 `OUTPUT_BUDGET_TOO_SMALL` 和最低需求，不提供残缺规则。已记录 run 的完整检索诊断可从 `diagnostics.href` 读取，需同一用户认证；用 `output_mode="full"` 可重新获取完整上下文。

`output_usage.tokens_upper_bound` 计量**单份紧凑 JSON 的全部 UTF-8 字节**，包含该统计字段；它是字节型 tokenizer 的保守 token 上界，不是模型精确计费值。英文通常会低于可容纳的实际 token 容量，换取离线、跨客户端的一致上界。MCP text 和 structuredContent 各含一份相同对象：调用方只注入其中一份；若两份都注入，应分别计量，并另计 MCP/消息包装。缓存降级后重新统计；旧 Hub 忽略 compact 参数时客户端也不会静默交付超限结果。静态 sync 的 `output_usage` 另统计完整渲染文本，不对正文外引导强加截断。

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
      "enum": ["identity", "guardrail", "reasoning", "method", "stack", "style", "decision", "context", "template", "project"],
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
  "type": "method"
}
```

**示例输出**:
```
找到 2 条相关记忆：

## 1. PR 必须带工单号 (score: 0.94)
类型: method | 标签: git, pr, ticket

所有 PR 的标题必须以 `[JIRA-XXX]` 工单号开头。
如果当前 branch 名包含工单号，默认从 branch 提取；否则需要先问用户。

## 2. PR 合并要求 (score: 0.87)
类型: method | 标签: git, pr, review

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
      "enum": ["identity", "guardrail", "reasoning", "method", "stack", "style", "decision", "context", "template", "project"],
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
      "enum": ["identity", "guardrail", "reasoning", "method", "stack", "style", "decision", "context", "template", "project"],
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
    "project": {
      "type": "string",
      "description": "所有类型均可传已存在的 canonical project 或 active alias；type=project 必填"
    }
  },
  "required": ["title", "content", "type", "tags"]
}
```

**Output**:
```
✓ 记忆已保存（ai_review）

标题: 用户偏好 ruff 作为 Python linter
类型: stack
状态: ai_review（AI 可立即检索；用户可通过 `echome review` 提升或归档）
```

**重要约束**:
- 可以主动写入 ai_review 记忆，但必须是可复用、稳定、高置信度的信息
- 用户明确表达"记住/以后/总是/永远"等意图时必须调用
- 不要写入密码/密钥/隐私敏感内容、一次性临时事实、低置信度猜测
- 默认写入 ai_review，会立即参与后续 AI 检索；用户通过 `echome review` 做事后清理或提升为 active
- 项目参数名是 `project`，不是搜索接口使用的 `project_id`；所有类型均可绑定已有项目，active alias 会解析到 canonical ID；type=project 仍要求项目，remember 不创建项目
- 项目记忆通常建议 `L1`；需要创建项目范围的 `decision/method/guardrail` 等其他类型时，使用 Web 或 REST 设置 scope，不能把数据模型的三轴正交理解为此 MCP 写入入口已完整支持

---

### 4.7 echome_get_project_context

**描述**: 兼容的项目 Memory 列表入口，不是结构化 Project Context Compiler。需要自动项目身份解析、workspace 继承或证据编译时使用 `echome_context`。

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "project_id": {
      "type": "string",
      "description": "项目 ID，如 'qzhqzh/EchoMe'。此兼容工具不自动推断，缺省时仅返回提示"
    }
  },
  "required": []
}
```

**Output**: 按类型汇总该项目的有效 Memory（active + ai_review），当前最多读取前 50 条；不返回完整 Artifact/Constraint/Event 上下文。

---

## 5. Resources

当前实现提供一个 resource：

| URI | 描述 |
|---|---|
| `echome://capabilities` | JSON 能力目录、工具分组、推荐工作流和使用规则 |

`echome://profile`、`echome://projects` 和 `echome://project/{id}` 是早期设想，目前未注册。

## 6. Prompts

当前提供 `echome_retrieval_workflow`，接受可选的 `project_id`，返回可复用的能力发现、上下文检索、图解释和记忆写入指引。

客户端是否将 MCP prompt 展示为 slash command，由客户端决定。服务端没有注册早期文档中的 `/echome-load` 或 `/echome-status` 命令。

## 7. AI 何时调用 MCP

这是 EchoMe 设计中最关键的问题。AI 不会自动加载 MCP 内容，需要通过以下机制引导：

### 7.1 L0 Preamble 引导（写在 CLAUDE.md 中）

```markdown
### 如何获取更多上下文
1. 首次使用或不确定工具时，先调用 echome_capabilities。
2. 首条任务消息后调用 echome_context，传入任务、已知 project hint 和 changed paths。
3. 命中规范时只复述与任务有关的关键点；后续按需查询，无命中就停止扩展。
4. 使用可能过时的项目决策、版本或环境信息前，调用 echome_memory_explain 检查来源。
5. 用户要求记住，或发现稳定且可复用的信息时，调用 echome_remember 写入 ai_review。
6. 明确有用、过时或冲突的记忆可提交 memory feedback；任务结束按 completion contract 提交 context outcome。
```

这是简化示例；实际同步引导由 [renderer.py](../hub/app/services/renderer.py) 生成。

### 7.2 触发时机总结

| 场景 | 触发的 Tool |
|---|---|
| 首次能力发现 | `echome_capabilities` |
| 开始任务、PR 规范、历史决策或不确定项目约定 | `echome_context` |
| 关键记忆可能过时或存在替代关系 | `echome_memory_explain` |
| 用户说“记住/以后”或观察到稳定约定 | `echome_remember` |
| 需要额外浏览候选/精读，且已启用 full | `echome_search_summary` → `echome_get_memories` |
| 记忆有效性已有明确结果 | `echome_memory_feedback` |
| 已记录的 Context Run 完成 | `echome_context_outcome` |

### 7.3 不应调用的场景

- 纯知识性问答（AI 自己能回答的）
- 用户明确说"不用查了"
- 简单代码修改（无工作流约束涉及时）

## 8. 错误处理

结构化工具的错误使用 `echome.error.v1`。以下是错误 payload 示例；MCP 响应还包含 `isError` 和可读的 content，部分 legacy 工具仍保留文本输出：

```json
{
  "schema_version": "echome.error.v1",
  "error": {
    "code": "HUB_UNAVAILABLE",
    "message": "EchoMe Hub is unavailable",
    "retryable": true,
    "request_id": "example-request-id",
    "degraded": true,
    "suggested_action": "Check Hub connectivity and retry."
  }
}
```

**降级策略**：

- `echome_context` 遇到可降级故障时，只能复用相同请求键的加密只读缓存，并标明 degraded 和数据来源。
- 没有可用缓存时返回错误或缺失上下文提示，不能把无数据解释为“没有相关记忆”。
- 本地 vault 不是当前 fallback；写入失败直接报告，不使用离线队列或假成功响应。
- `scope=project_resolution` 是需要恢复项目身份的正常结构化结果，不等于传输错误。

## 9. 安全考虑

- MCP Server 以用户身份运行，继承用户文件权限
- 不暴露 Hub token 给 AI（MCP Server 内部使用）
- echome_remember 写入的内容默认 ai_review，允许 AI 自主学习，同时保留人工事后纠偏
- 没有通用物理删除 Memory 的 MCP 工具；Sleep apply 可以在已确认的 proposal 范围内归档来源，不能把它理解成纯只读工具
- 客户端应避免提交密码/密钥等敏感内容；Hub 对写入和 embedding 外发执行最终内容校验，不能只依赖 CLI 过滤
