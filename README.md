# EchoMe

> 让每个 AI，都能接住你的过去。
>
> Switch AI, not yourself.

[![PyPI](https://img.shields.io/pypi/v/echome.svg)](https://pypi.org/project/echome/)
[![Python](https://img.shields.io/pypi/pyversions/echome.svg)](https://pypi.org/project/echome/)
[![CI](https://github.com/qzhqzh/EchoMe/actions/workflows/ci.yml/badge.svg)](https://github.com/qzhqzh/EchoMe/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/qzhqzh/EchoMe.svg)](LICENSE)

EchoMe 是一个面向 AI Agent 的**个人记忆与项目上下文层**。它统一保存工作习惯、技术偏好、项目文档、约束关系、历史决策和验证证据，让 Codex、Claude Code、Cursor 等客户端通过 MCP 获得一致、可追溯、可演进的上下文。

当前稳定版本为 **v1.7.1**，包含 Trusted Context Policy、Sleep v2 和策略校准门禁；
生产策略默认仍保持 shadow，不会由 readiness 自动开启 enforce。

## 核心架构

<a href="https://qzhqzh.github.io/EchoMe/?theme=dark&amp;present=1">
  <img src="docs/echome-architecture-v1.5.github-dark-present.png" alt="EchoMe v1.5 系统架构图（Dark + Presentation）" width="100%">
</a>

> 点击架构图进入[交互式版本](https://qzhqzh.github.io/EchoMe/?theme=dark&present=1)。默认使用 **Dark + Presentation Stage**，支持节点搜索、关系追踪、缩放、主题切换和图片导出。

> 该图是 v1.5.0 发布快照。本工作树的后续收敛（包括移除未接入的 Redis）以[当前架构文档](docs/architecture.md)为准，下一次发布时再生成新的版本化图，不覆盖该快照。

发布快照由 [Archify 规格](docs/echome-architecture-v1.5.archify.json) 生成，独立 HTML 保存在 [docs/echome-architecture-v1.5.html](docs/echome-architecture-v1.5.html)。

## 核心能力

### 统一上下文入口

AI 默认调用 `echome_context`，由运行时自动完成：

- personal / project / impact / temporal 路由选择
- canonical project 与 alias 解析
- 记忆、约束、制品、事件和图关系召回
- 冲突、未知项、时效性和 answerability 判断
- token budget 控制与检索 trace 记录
- Hub 不可达时的加密、只读 last-known-good 降级

模型不需要先猜测应该使用记忆搜索、图查询还是项目上下文工具。

### 个人记忆

- 三轴模型：`Type × Scope × Layer`
- `L0` 全局加载、`L1` 项目加载、`L2` MCP 按需检索
- keyword、vector、graph、temporal 多种检索证据
- `active / ai_review / pending / deprecated / archived` 状态管理
- `derived_from`、`superseded_by` 等可追溯关系
- feedback、temporal review 和检索质量评估

### Project Knowledge

- 项目制品版本与 chunk 索引
- 版本化约束、关系边和来源证据
- Project Events 记录 issue、failure、fix、test、decision 和 deploy
- Context Compiler 按任务与改动路径生成证据优先的上下文包
- Impact 与 Preflight 在修改、测试、提交和部署前提供历史约束
- Evidence-backed Reflect 允许强客户端 AI 生成带逐条证据和来源指纹的派生视图
- canonical project aliases 避免目录名、Git remote 和历史 ID 分裂上下文

### Memory Sleep

Memory Sleep 用于整理不断增长的记忆，但不会静默覆盖历史：

1. Hub 返回所有符合条件的非归档、非 deprecated 候选。
2. 服务端或能力更强的客户端 AI 生成文本预案和 JSON；新版 MCP 默认请求带来源前置条件与 replay cases 的 v2，REST v1 继续兼容。
3. Hub 校验并运行整理前后 simulation，展示来源覆盖、token footprint 和检索回归。
4. 确认后 Hub 按最新数据重新验证，再新增归纳记忆、归档来源并保留派生和替代关系。

### 质量与可观测性

Web Console 提供：

- Memory 与 Project 工作台
- 可交互记忆关系图和节点邻居
- Retrieval Debugger 与检索日志
- Context Runs、fallback、错误与选入证据
- Reliability/intervention shadow trace 与真实 Retrieval Log replay
- Policy Readiness 汇总显式 policy effect，并且只授予 canary 评估资格，不自动开启 enforce
- Memory Quality Eval 与五能力 Project Context Eval
- Sleep session 和变更审计

Context Outcome 与 Memory Feedback 均为 append-only 信号，不会直接、静默地改变生产排序。

## AI 应该如何使用 EchoMe

推荐工作流：

1. 首次接触时调用 `echome_capabilities` 发现能力。
2. 普通任务优先调用 `echome_context`。
3. 关键历史决策调用 `echome_memory_explain` 检查来源、替代关系和时效性。
4. 任务结束后，为已记录的 context run 追加一次 outcome；有明确证据时记录
   `success / partial / failed / corrected`，无法判断时记录 `no_signal`，不打断用户。
5. 在 `full` profile 中，宽泛问题可使用 summary-first，项目修改可使用 preflight/impact 专业工具。
6. 需要形成长期项目 mental model 时，先调用 `echome_reflect_prepare`，再以原始 watermark 和逐条证据调用 `echome_reflect_submit`。

EchoMe MCP 提供 `core` 和 `full` 两种 profile。新执行 `echome init` / `echome mcp install` 的配置会显式使用 `core`，暴露 8 个高频入口；设置 `ECHOME_MCP_PROFILE=full` 并重启客户端后，可启用 summary-first、Project Knowledge 和 Sleep 等专业工具。为避免升级破坏，历史配置若没有 profile 字段会继续使用 `full`。

## 系统组件

| 组件 | 技术 | 作用 |
|---|---|---|
| Hub | FastAPI + SQLAlchemy 2.0 + Alembic | 权威 API、身份解析、上下文编译与审计 |
| PostgreSQL | PostgreSQL 16 + pgvector | 记忆、项目知识、向量、关系和运行证据 |
| Embedding | BAAI/bge-m3 | 语义向量生成与召回 |
| Web Console | Vue 3 + Nginx | 管理、观测、图分析和质量评估 |
| CLI | Typer + Rich + httpx | 初始化、同步、审核、Sleep 与环境诊断 |
| MCP Server | 官方 Python MCP SDK | 默认 8 个核心工具，可切换完整专业工具集 |

默认 Docker Compose 端口：

| 服务 | 地址 |
|---|---|
| Hub | `http://localhost:20000` |
| Web Console | `http://localhost:20001` |
| Embedding | `http://localhost:20002` |

## 安装

要求 Python 3.11 或更高版本。

```bash
pip install --upgrade echome
echome version
```

也可以直接从 GitHub 安装：

```bash
pip install "echome @ git+https://github.com/qzhqzh/EchoMe.git"
```

## 快速开始

### 1. 部署 Hub

```bash
git clone https://github.com/qzhqzh/EchoMe.git
cd EchoMe
cp hub/.env.example hub/.env
docker compose up -d
```

启动后访问 `http://localhost:20001` 使用 Web Console。

### 2. 初始化 CLI 与 MCP

```bash
echome init
echome doctor
```

`echome init` 会创建本地配置、连接 Hub，并注册可识别的 AI 客户端。也可以单独执行：

```bash
echome mcp install
```

MCP Server 默认使用 stdio：

```bash
echome mcp serve
```

需要本地 Streamable HTTP 时：

```bash
echome mcp serve --http --host 127.0.0.1 --port 20003
```

### 3. 添加和同步记忆

```bash
echome add
echome list
echome search "Git 提交流程"
echome sync
```

### 4. 整理记忆

```bash
echome sleep candidates
```

Sleep apply 需要先提交并确认合法 JSON 预案，不会直接批量重写原始记忆。

## 常用命令

| 命令 | 说明 |
|---|---|
| `echome init` | 初始化 vault、Hub 和 MCP |
| `echome add` | 添加记忆 |
| `echome list` | 查看记忆 |
| `echome search` | 搜索记忆 |
| `echome sync` | 渲染并注入 L0/L1 记忆 |
| `echome review` | 审核 AI 写入的 `ai_review` 记忆 |
| `echome sleep` | 生成、提交和执行 Memory Sleep 预案 |
| `echome doctor` | 检查版本、配置、Hub 与 MCP |
| `echome status` | 查看运行和同步状态 |
| `echome mcp install` | 注册 MCP Server |

`echome push` / `echome pull` 保留为未来的文件式 local-vault 接口，当前会明确返回“未实现”，不会执行空同步并伪报成功。

## 数据安全原则

- PostgreSQL + pgvector 是唯一权威服务端数据层。
- 数据库迁移采用 Alembic；当前生产 schema revision 为 `017`，后续迁移继续保持 additive-only。
- archived 和 deprecated 记忆不会作为当前有效事实参与默认检索。
- Sleep、项目重关联和约束复核采用 `proposal → validate → apply`。
- 原始记忆、制品版本、约束版本、事件和关系证据不被静默删除。
- 运行反馈先追加记录，经过离线评估后才考虑影响排序。
- Retrieval Logs 仅保存 ID、标题、分数和 trace，不复制记忆正文。
- 本地 last-known-good 缓存使用 AES-256-GCM 加密，并受账号、请求键和 TTL 约束。

## 开发与验证

```bash
# CLI + MCP
uv sync --extra dev
uv run pytest
uv run ruff check echome echome_mcp tests

# Hub
cd hub
uv sync --extra dev
uv run pytest
uv run ruff check app tests alembic/versions

# Web
cd ../web
npm ci
npm run build
```

CI 对 CLI/MCP、Hub 和 Web 分别执行 lockfile 安装、Ruff、pytest 与 production build；发布构建还会在干净虚拟环境中安装 wheel 并运行命令入口。

## 文档

- [系统架构](docs/architecture.md)
- [v1.5 规划与验收](docs/next-version-plan-v1.5.md)
- [v1.6 Trusted Context Policy 历史基线](docs/next-version-plan-v1.6.md)
- [v1.7 Trusted Context Calibration 计划](docs/next-version-plan-v1.7.md)
- [v1.8 可信记忆闭环候选计划](docs/next-version-plan-v1.8.md)
- [记忆模型](docs/memory-model.md)
- [记忆检索设计](docs/memory-retrieval.md)
- [Memory Sleep](docs/memory-sleep.md)
- [Hub API 规范](docs/api-spec.md)
- [MCP Server 规范](docs/mcp-spec.md)
- [数据生命周期](docs/data-lifecycle.md)
- [开发路线图](docs/roadmap.md)
- [用户指南](docs/user-guide.md)

## License

[MIT](LICENSE)
