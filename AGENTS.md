# EchoMe 项目 - Codex CLI 开发指引

## 项目概述

EchoMe 是面向 AI Agent 的**个人记忆与项目上下文层**，当前主要组件为：
1. **Hub** (FastAPI) — 记忆与项目知识存储、混合检索、Context Compiler、证据与反馈
2. **CLI** (`echome`) — 连接 Hub、管理记忆、将 L0/L1 渲染到 AI 客户端配置
3. **MCP Server** — 以 `echome_context` 为默认入口，提供上下文、记忆写入和运行诊断
4. **Web Console** (Vue 3) — 记忆/项目工作台、审核、Sleep、Diagnostics 与质量评估
5. **Embedding** — BGE-M3 向量服务，供 Hub 检索使用

Hub 是当前权威存储；本地文件式 vault `push/pull` 尚未实现，不能视为双向同步能力。

## 技术栈

- **语言**: Python 3.11+
- **Hub**: FastAPI + SQLAlchemy 2.0 (async) + Alembic + PostgreSQL 16 + pgvector
- **CLI**: Typer + Rich + httpx
- **MCP**: mcp (官方 Python SDK)，支持 stdio / Streamable HTTP
- **Web**: Vue 3 + TypeScript + Vite + Tailwind CSS
- **Embedding**: BGE-M3，1024 维
- **包管理**: uv
- **部署**: Docker Compose
- **测试**: pytest + pytest-asyncio + httpx

## 项目结构

```
EchoMe/
├── echome/                 # CLI：main.py、commands/、core/、targets/
├── echome_mcp/             # MCP：server.py、tools/、Hub client 与上下文缓存
├── tests/                  # CLI/MCP 测试
├── hub/
│   ├── app/                # api/、models/、schemas/、services/、core/
│   ├── alembic/            # 数据库迁移
│   ├── tests/              # Hub API 与服务测试
│   └── pyproject.toml      # Hub 依赖
├── web/                    # Vue 3 + TypeScript Web Console
├── embedding/              # BGE-M3 服务
├── scripts/                # 项目真相检查等脚本
├── docs/                   # 当前说明及历史计划
├── pyproject.toml          # CLI + MCP 统一 Python 包
├── uv.lock
├── docker-compose.yaml
├── CLAUDE.md               # Claude Code 开发入口
├── AGENTS.md               # Codex 开发入口
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

当前稳定版本为 **v1.8.0**，当前源码 Alembic head 为 `018`、MCP capabilities 为 `echome.capabilities.v9`，新安装使用 10 工具的 `core` profile。主线包含发布后的项目身份恢复改进，不能仅凭包版本判断某个部署已具备全部源码能力。

当前能力与边界见 `docs/roadmap.md`、`docs/architecture.md`；旧版 Phase 0-6 和版本计划属于历史记录。版本与契约以源码及 `scripts/check_project_truth.py` 为准，实际部署以 runtime health / capabilities 返回值为准。

## 常见任务

### 安装开发依赖
```bash
# 仓库根目录：CLI + MCP
uv sync --locked --extra dev
# Hub 使用独立项目环境
uv sync --project hub --locked --extra dev
```

### 启动 Hub 开发环境
先按 `docs/deployment.md` 配置 `hub/.env`，再从仓库根目录运行：

```bash
docker compose up -d --build
```

服务与端口以 `docker-compose.yaml` 为准；前端单独开发见 `web/README.md`。

### 运行测试
```bash
# 均从仓库根目录运行
uv run pytest tests
uv run --directory hub pytest tests
uv run python scripts/check_project_truth.py
```

### 数据库迁移
```bash
cd hub
uv run alembic upgrade head        # 应用迁移
uv run alembic revision --autogenerate -m "description"  # 生成迁移
```
