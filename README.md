# EchoMe

> 让每个 AI，都能接住你的过去。
>
> Switch AI, not yourself.

## 是什么

EchoMe 是一个**跨 AI 的个人上下文同步层**。它把你的工作流规范、技术偏好、项目背景和协作习惯统一管理，让你在 Claude Code、Codex CLI、Cursor、Kiro 等任何 AI 工具之间切换时，不需要重复介绍自己。

## 核心架构

```
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│  Claude Code   │     │   Codex CLI    │     │  Cursor/Kiro   │
│  (MCP Client)  │     │  (MCP Client)  │     │  (MCP Client)  │
└───────┬────────┘     └───────┬────────┘     └───────┬────────┘
        │                      │                      │
        └──────────────────────┼──────────────────────┘
                               │ MCP Protocol
                               ▼
        ┌──────────────────────────────────────────────┐
        │          EchoMe MCP Server (本地)             │
        └──────────────────────┬───────────────────────┘
                               │ HTTPS
                               ▼
        ┌──────────────────────────────────────────────┐
        │            EchoMe Hub (你的服务器)             │
        │     FastAPI + PostgreSQL + pgvector           │
        └──────────────────────────────────────────────┘
```

## 三层注入策略

| Layer | 何时生效 | 方式 | 限制 |
|---|---|---|---|
| **L0** | 每次对话 | 写入 ~/.claude/CLAUDE.md | ≤ 1500 tokens |
| **L1** | 进入项目 | 项目级文件 | ≤ 2000 tokens |
| **L2** | AI 按需查 | MCP search | 无限制 |

## 组件

| 组件 | 说明 | 位置 |
|---|---|---|
| **Hub** | FastAPI 服务端，存储和检索记忆 | `hub/` |
| **CLI** | `echome` 命令行工具，管理和同步 | `echome/` |
| **MCP Server** | 向 AI 暴露查询/写入能力 | `echome_mcp/` |

## 快速开始

### 1. 部署 Hub

```bash
cd hub
cp .env.example .env       # 配置数据库和 token
docker compose up -d       # 启动 Postgres + Redis + App
```

### 2. 安装 CLI + MCP（一条命令）

```bash
# 完整安装（CLI + MCP Server）
pip install echome[mcp]

# 或仅安装 CLI（不需要 MCP）
pip install echome

# 初始化：连接 Hub + 注册 MCP（交互式）
echome init
```

### 3. 添加记忆

```bash
echome add                  # 交互式添加
echome list                 # 查看所有记忆
echome search "PR 规范"     # 搜索
```

### 4. 注入到 AI CLI

```bash
cd your-project
echome sync                 # 自动检测 + 渲染到 CLAUDE.md / AGENTS.md
```

### 5. 更新

```bash
echome update               # 自更新到最新版本
```

之后 AI 就能通过 MCP 随时查询你的记忆了。

## 记忆模型

每条记忆有三个核心维度：

- **Type**：persona / workflow / tech / constraint / snippet / decision / knowledge / interaction / project
- **Scope**：global（跟人走）或 project-specific（跟项目走）
- **Layer**：L0（必须加载）/ L1（项目级加载）/ L2（按需搜索）

详见 [docs/memory-model.md](docs/memory-model.md)

## 文档

- [系统架构](docs/architecture.md)
- [记忆模型](docs/memory-model.md)
- [Hub API 规范](docs/api-spec.md)
- [MCP Server 规范](docs/mcp-spec.md)
- [开发路线图](docs/roadmap.md)
- [早期讨论](discuss.md)

## 技术栈

- Python 3.11+ / FastAPI / SQLAlchemy 2.0 / Alembic
- PostgreSQL 16 + pgvector
- Typer + Rich (CLI)
- mcp (official Python SDK)
- Docker Compose
- uv (包管理)

## License

MIT
