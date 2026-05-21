# EchoMe 项目 - Codex CLI 开发指引

## 项目概述

EchoMe 是一个**跨 AI 的个人上下文同步层**，包含三个核心组件：
1. **Hub** (FastAPI 服务端) — 存储和检索记忆
2. **CLI** (echome 命令行) — 管理本地 vault 并同步到 Hub
3. **MCP Server** — 向 AI CLI 暴露记忆查询/写入能力

## 技术栈

- **语言**: Python 3.11+
- **Hub**: FastAPI + SQLAlchemy 2.0 (async) + Alembic + PostgreSQL 16 + pgvector
- **CLI**: Typer + Rich + httpx
- **MCP**: mcp (官方 Python SDK)
- **包管理**: uv
- **部署**: Docker Compose
- **测试**: pytest + pytest-asyncio + httpx

## 项目结构

```
EchoMe/
├── hub/                    # FastAPI 服务端
│   ├── app/
│   │   ├── main.py         # FastAPI app 入口
│   │   ├── api/            # 路由
│   │   ├── models/         # SQLAlchemy models
│   │   ├── schemas/        # Pydantic schemas
│   │   ├── services/       # 业务逻辑
│   │   └── core/           # 配置、依赖、中间件
│   ├── alembic/            # 数据库迁移
│   ├── tests/
│   └── pyproject.toml
├── cli/                    # CLI 客户端
│   ├── echome/
│   │   ├── __init__.py
│   │   ├── main.py         # Typer app
│   │   ├── commands/       # 子命令
│   │   ├── targets/        # 目标适配器 (claude, codex)
│   │   └── core/           # 配置、同步逻辑
│   ├── tests/
│   └── pyproject.toml
├── mcp_server/             # MCP Server
│   ├── echome_mcp/
│   │   ├── __init__.py
│   │   ├── server.py       # MCP server 入口
│   │   └── tools/          # Tool 实现
│   ├── tests/
│   └── pyproject.toml
├── docs/                   # 文档
├── docker-compose.yaml
├── CLAUDE.md               # Claude Code 入口
├── AGENTS.md               # 本文件
└── README.md
```

## 开发规范

### 代码风格
- 使用 `ruff` 格式化和 lint
- 类型注解必须（mypy strict）
- 异步优先（async/await）
- Pydantic v2 做数据校验

### Git 规范
- Branch: `feat/xxx`, `fix/xxx`, `docs/xxx`
- Commit: Conventional Commits 格式
  - `feat: add memory search API`
  - `fix: handle empty embedding response`
  - `docs: update API spec`
- PR 标题简洁明了

### 测试
- Hub API: pytest + httpx AsyncClient
- CLI: pytest + typer.testing.CliRunner
- MCP: pytest + mock Hub responses

### 安全
- 不在代码中硬编码 token/密码
- 环境变量或 .env 文件管理敏感配置
- .env 文件加入 .gitignore

## 关键文档

- `docs/architecture.md` — 系统架构
- `docs/memory-model.md` — 记忆模型（三轴设计）
- `docs/api-spec.md` — Hub REST API
- `docs/mcp-spec.md` — MCP Server 接口
- `docs/roadmap.md` — 开发路线图
- `discuss.md` — 早期讨论背景

## 当前阶段

Phase 0 — 项目骨架搭建。参考 `docs/roadmap.md` 了解完整计划。

## 常见任务

### 启动 Hub 开发环境
```bash
cd hub
docker compose up -d postgres redis
uv run uvicorn app.main:app --reload
```

### 运行测试
```bash
cd hub && uv run pytest
cd cli && uv run pytest
cd mcp_server && uv run pytest
```

### 数据库迁移
```bash
cd hub
uv run alembic upgrade head        # 应用迁移
uv run alembic revision --autogenerate -m "description"  # 生成迁移
```
