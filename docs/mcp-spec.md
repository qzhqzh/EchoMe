# EchoMe MCP Server 规范

## 1. 概览

EchoMe MCP Server 是运行在用户本地的进程，向 AI CLI (Claude Code, Codex CLI 等) 暴露用户记忆的查询和写入能力。

**运行方式**：
```bash
echome mcp serve           # stdio 模式（默认，适合 Claude Code）
echome mcp serve --sse     # SSE 模式（适合远程/多客户端）
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
- Transport: stdio (默认) / SSE

## 3. Server Info

```json
{
  "name": "echome",
  "version": "0.1.0",
  "description": "Personal memory and context layer - search and manage your knowledge, preferences, and workflow rules"
}
```

## 4. Tools

### 4.1 echome_search / memory_search

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

### 4.2 echome_get

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

### 4.3 echome_list_by_type

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

### 4.4 echome_remember / memory_remember

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

### 4.5 echome_get_project_context

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
