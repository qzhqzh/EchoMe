# EchoMe 系统架构

## 1. 总体定位

EchoMe 是一个 **跨 AI 的个人上下文同步层**，让用户的习惯、偏好、工作流规范和知识在不同 AI CLI/IDE 之间自然延续。

核心理念：**Switch AI, not yourself.**

## 2. 系统架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户终端环境                                  │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐            │
│  │ Claude Code  │   │  Codex CLI   │   │ Cursor/Kiro  │  ...       │
│  │              │   │              │   │              │            │
│  │ 读 CLAUDE.md │   │ 读 AGENTS.md │   │ 读 rules     │            │
│  │ 调 MCP tools │   │ 调 MCP tools │   │ 调 MCP tools │            │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘            │
│         │                  │                  │                     │
│         └──────────────────┼──────────────────┘                     │
│                            │ MCP Protocol (stdio / SSE)             │
│                            ▼                                        │
│  ┌─────────────────────────────────────────────┐                    │
│  │           EchoMe MCP Server (本地)           │                    │
│  │  - 转发查询到 Hub                            │                    │
│  │  - 缓存热点记忆                              │                    │
│  │  - 离线时降级到本地 vault                     │                    │
│  └─────────────────────┬───────────────────────┘                    │
│                        │                                            │
│  ┌─────────────────────┴───────────────────────┐                    │
│  │           EchoMe CLI (echome)                │                    │
│  │  - init / edit / list / sync / push / pull   │                    │
│  │  - 管理 ~/.echome/ 本地 vault                 │                    │
│  │  - 渲染 L0/L1 到目标文件                      │                    │
│  └─────────────────────┬───────────────────────┘                    │
│                        │                                            │
│         ~/.echome/     │  (本地 vault，Hub 的离线缓存)                │
└────────────────────────┼────────────────────────────────────────────┘
                         │
                         │ HTTPS (REST API + MCP over SSE)
                         │ Auth: Bearer Token
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      EchoMe Hub (你的服务器)                          │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                     FastAPI Application                       │   │
│  │                                                              │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────────────────┐ │   │
│  │  │ REST API   │  │ MCP SSE    │  │ Background Workers     │ │   │
│  │  │ /api/v1/*  │  │ /mcp/*     │  │ (embedding, cleanup)   │ │   │
│  │  └────────────┘  └────────────┘  └────────────────────────┘ │   │
│  │                                                              │   │
│  │  ┌────────────────────────────────────────────────────────┐  │   │
│  │  │                 Business Logic                          │  │   │
│  │  │  Memory CRUD · Search (keyword + vector) · Sync        │  │   │
│  │  │  Layer Resolution · Scope Matching · AI Write Review   │  │   │
│  │  └────────────────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                     Data Layer                                │   │
│  │                                                              │   │
│  │  PostgreSQL 16 + pgvector                                    │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────────────────┐ │   │
│  │  │ memories   │  │ projects   │  │ sync_log               │ │   │
│  │  │ (+ vector) │  │            │  │                        │ │   │
│  │  └────────────┘  └────────────┘  └────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  Redis (可选，缓存 + 后台任务队列)                                    │
└─────────────────────────────────────────────────────────────────────┘
```

## 3. 核心组件职责

### 3.1 EchoMe Hub（服务端）

| 模块 | 职责 |
|---|---|
| REST API | CLI 同步、CRUD、批量操作 |
| MCP SSE Endpoint | 供 AI CLI 直接查询/写入记忆 |
| Search Engine | 关键词 + 向量混合检索，按 scope/layer/type 过滤 |
| Background Workers | embedding 计算、过期记忆清理、审核队列 |
| Auth | 单租户 Bearer Token（预留多租户 user_id 字段） |

**技术栈**：
- **框架**：FastAPI（异步友好，MCP SSE 需要长连接）
- **ORM**：SQLAlchemy 2.0 + Alembic 迁移
- **数据库**：PostgreSQL 16 + pgvector 扩展
- **Embedding**：OpenAI text-embedding-3-small 或本地 sentence-transformers
- **缓存/队列**：Redis + ARQ（轻量异步任务）
- **部署**：Docker Compose（Postgres + Redis + App）

### 3.2 EchoMe CLI（客户端命令行工具）

| 命令 | 作用 |
|---|---|
| `echome init` | 初始化 ~/.echome/ 并连接 Hub |
| `echome login` | 验证 token，保存到 ~/.echome/config.yaml |
| `echome list` | 列出记忆（支持 --type --layer --tag 过滤） |
| `echome edit <id>` | 编辑记忆（调起 $EDITOR） |
| `echome add` | 交互式新建记忆 |
| `echome search <query>` | 向 Hub 发起语义搜索 |
| `echome sync` | 渲染 L0/L1 记忆到当前项目的 AI CLI 文件 |
| `echome push` | 本地 vault → Hub |
| `echome pull` | Hub → 本地 vault |
| `echome status` | 显示当前项目加载了哪些记忆 |
| `echome detect` | 检测当前目录属于哪个 AI CLI |
| `echome eject` | 移除 EchoMe 注入的内容，恢复原状 |

**技术栈**：
- Python 3.11+ / Typer + Rich（美观 CLI 输出）
- httpx（异步 HTTP 调 Hub API）
- PyPI 发布为 `echome-cli`

### 3.3 EchoMe MCP Server（本地 MCP 进程）

以 **stdio** 或 **SSE** 模式运行，注册在 AI CLI 的 MCP 配置中。

暴露给 AI 的能力：

| Tool 名 | 描述 |
|---|---|
| `echome_search` | 按关键词/语义搜索用户记忆 |
| `echome_get` | 按 id 获取单条记忆全文 |
| `echome_list_by_type` | 按 type 列出记忆标题 |
| `echome_remember` | AI 主动写入新记忆（进审核队列） |
| `echome_get_project_context` | 获取当前项目的上下文 |

**运行方式**：
- 作为 `echome mcp serve` 子命令启动
- Claude Code 配置：`~/.claude/mcp.json` 中注册
- Codex CLI 配置：`~/.codex/mcp.json` 中注册

## 4. 数据流

### 4.1 用户手动维护记忆

```
用户 → echome edit → 本地 vault 更新 → echome push → Hub 入库 + 算 embedding
```

### 4.2 AI 查询记忆（MCP）

```
AI 判断需要上下文 → 调 echome_search tool → MCP Server → Hub /api/v1/search → 返回 top-K 记忆
```

### 4.3 AI 主动写记忆

```
对话中用户说"以后都这样" → AI 调 echome_remember → Hub 写入 status=pending → 用户 echome review 确认
```

### 4.4 渲染到 AI CLI 文件

```
echome sync → 检测目标 CLI → 从 Hub 拉取 (layer=L0, scope=global) + (layer=L1, scope=当前项目) → 渲染到 ~/.claude/CLAUDE.md 和/或 ./CLAUDE.md
```

## 5. 三层注入策略

| Layer | 何时被 AI 看到 | 注入方式 | Token 限制 |
|---|---|---|---|
| **L0** | 每次对话必定生效 | 写入 `~/.claude/CLAUDE.md` / `~/.codex/AGENTS.md` | ≤ 1500 tokens |
| **L1** | 进入特定项目才生效 | 写入项目级文件（marker 区或旁路文件） | ≤ 2000 tokens |
| **L2** | AI 主动调 MCP 时 | 不写文件，按需查询 | 无限制 |

### L0 Preamble 必须包含的内容

```markdown
## EchoMe Context (auto-managed, do not edit this block)

我是 [用户名]，[一句话身份描述]。

### 工作流硬规矩
- PR 标题必须带 [JIRA-XXX] 工单号
- 合并前需 1 个 reviewer + CI 通过
- 不允许 force push / reset --hard

### 沟通偏好
- 中文回答
- 先结论后分析
- 有疑问先反问

### 如何获取更多上下文
当你需要查询我的过往决策、项目背景、技术偏好或其他记忆时，
请调用 MCP tool `echome_search` 进行检索。
```

最后一段是 **MCP-aware preamble**，确保 AI 知道何时该调 MCP。

## 6. 冲突处理策略

### 全局文件 (~/.claude/CLAUDE.md)

- EchoMe 管理的内容用 marker 包裹：
  ```
  <!-- echome:begin -->
  ...
  <!-- echome:end -->
  ```
- marker 之外的内容 EchoMe 不触碰
- `echome sync` 只替换 marker 区内容

### 项目文件已有 CLAUDE.md

- **默认不修改**项目原有的 CLAUDE.md
- 如需项目级注入，使用旁路方式：
  ```
  project/
  ├── CLAUDE.md              ← 原有，不动
  └── .echome/
      └── project-rules.md   ← EchoMe 管理
  ```
- 在全局 CLAUDE.md 的 EchoMe 区加一句引导：
  > 如果当前项目存在 `.echome/` 目录，请读取其中的规则文件。

## 7. 安全与隐私

- 所有通信 HTTPS
- Token 存储在 `~/.echome/config.yaml`，权限 600
- Hub 单租户模式，无需复杂权限
- AI 写入的记忆默认 `status: pending`，需用户确认才变为 `active`
- 敏感字段（secrets、passwords）不入库，CLI 层过滤

## 8. 多租户预留

当前单租户实现，但数据模型已预留：
- `memories` 表有 `user_id` 字段（当前写死为 default）
- API 路由结构 `/api/v1/` 可扩展为 `/api/v1/users/{user_id}/`
- Auth 中间件预留 JWT decode 位置

## 9. 部署拓扑（单租户）

```
你的服务器 (1 台即可)
├── docker-compose.yaml
│   ├── echome-hub (FastAPI, port 8000)
│   ├── postgres (port 5432, with pgvector)
│   └── redis (port 6379)
└── nginx / caddy (反向代理 + TLS)
```

## 10. 技术选型总结

| 组件 | 选型 | 理由 |
|---|---|---|
| Hub 框架 | FastAPI | 异步原生、SSE 友好、类型安全 |
| ORM | SQLAlchemy 2.0 | 成熟、Alembic 迁移、async 支持 |
| 数据库 | PostgreSQL 16 + pgvector | 关系 + 向量一体，减少依赖 |
| 缓存/队列 | Redis + ARQ | 轻量级异步任务 |
| CLI | Typer + Rich | 开发快、输出美观 |
| MCP SDK | mcp-python (official) | Anthropic 官方 MCP SDK |
| Embedding | OpenAI text-embedding-3-small | 成本低、效果好；可换本地模型 |
| 部署 | Docker Compose | 一键启动，适合单机 |
| 包管理 | uv / pip | 现代 Python 工作流 |
