# EchoMe 项目 - Claude Code 开发指引

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
├── CLAUDE.md               # 本文件
├── AGENTS.md               # Codex CLI 入口
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

## ⚠️ Git 工作流 SOP（必须遵守）

### 数据安全原则（最高优先级）

**改动是第一优先级，其他规范都能补救，改动丢了很难找。**

操作前检查：
```bash
git status && git diff && git diff --cached
git log origin/main..HEAD --oneline
git stash list
```

安全操作原则：
1. 优先 commit 而非 stash（commit 比 stash 更安全）
2. stash 前必须确认内容（防止同名 stash 覆盖）
3. 禁止 `git push --force`，必须用 `--force-with-lease`
4. 重要操作前打标签备份：`git tag backup-$(date +%Y%m%d-%H%M%S)`

### Step 1: 检查改动 + 提 Issue

```bash
git status
git diff
git diff --cached
git log origin/main..HEAD --oneline
git stash list
```

- 分析所有未提交改动和未推送 commit，理解功能意图
- **不要丢弃任何改动**
- 如果多个功能混在一起，按功能拆分创建多个 Issue

### Step 2: 移动改动到 feature 分支 + 提交

**千万不可丢弃未提交的改动！**

**方案 A：使用 stash（少量改动）**
```bash
git stash save "临时保存所有改动"
git checkout -b feat/<功能名>
git stash pop
git add .
git commit -m "feat(<scope>): <描述>"
git push -u origin feat/<功能名>
```

**方案 B：先 commit 再调整（大量改动，更安全）**
```bash
git add .
git commit -m "wip: 临时保存改动"
git checkout -b feat/<功能名>
git cherry-pick <临时commit的hash>
```

### Step 3: 提 PR + 评审 + 合并

**3.1 同步最新代码**
```bash
git tag backup-before-rebase-$(date +%Y%m%d-%H%M%S)
git fetch origin
git rebase origin/main
# 如果冲突：git add . && git rebase --continue
git push origin feat/<功能名> --force-with-lease
```

**3.2 创建 PR**
```bash
gh pr create --title "feat: <功能描述>" --body "Closes #<issue_id>" --base main
```

**3.3 评审 + 合并**
```bash
# Solo 项目（无法 self-approve）：自检后直接合并
gh pr merge <number> --merge
```

### Step 4: 同步本地 + 清理

```bash
git checkout main
git pull origin main
git branch -d feat/<功能名>
git push origin --delete feat/<功能名>
```

### PR 评审修复 / 同功能改动

在原 feature 分支上开发，push 后 PR 自动更新：
```bash
git checkout feat/<功能名>
git fetch origin && git rebase origin/main
git add . && git commit -m "fix(<scope>): 根据评审意见修改"
git push origin feat/<功能名> --force-with-lease
```

### 热修复 (hotfix)

紧急修复，无需评审：
```bash
git checkout main && git pull origin main
git checkout -b hotfix/<修复名>
git add . && git commit -m "fix: <修复描述>"
git push -u origin hotfix/<修复名>
gh pr create --title "hotfix: <修复描述>" --body "紧急修复" --base main
gh pr merge <number> --merge
```

## 关键文档

- `docs/architecture.md` — 系统架构
- `docs/memory-model.md` — 记忆模型（三轴设计）
- `docs/memory-sleep.md` — Memory Sleep 设计
- `docs/api-spec.md` — Hub REST API
- `docs/mcp-spec.md` — MCP Server 接口
- `docs/roadmap.md` — 开发路线图
- `discuss.md` — 早期讨论背景

## 当前阶段

Phase 1 — Memory Sleep + Observability 已完成。参考 `docs/roadmap.md` 了解完整计划。

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
