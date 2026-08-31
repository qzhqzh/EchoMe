# EchoMe 系统架构

## 1. 系统定位

EchoMe 是面向 AI Agent 的**个人记忆与项目上下文层**。它保存两类长期知识，并通过统一上下文入口交付给 Codex、Claude Code、Cursor 等客户端：

- **Personal Memory**：个人习惯、偏好、工作方法、跨项目约定和可复用经验。
- **Project Knowledge**：项目制品、约束、关系、事件、验证证据和影响范围。

两类数据共享身份、项目解析和运行时，但保持独立模型与生命周期，避免把项目事实混入个人偏好。

v1.5.0 发布快照：[`echome-architecture-v1.5.html`](echome-architecture-v1.5.html)。该版本化图保留当时拓扑；本页文本描述当前工作树，下一次发布会生成新文件而不覆盖旧图。

## 2. 当前真实拓扑

```text
Codex / Claude Code / Cursor
              |
              | MCP: stdio or local Streamable HTTP
              v
       EchoMe MCP Server -----------------------------+
              |                                       |
              | HTTPS REST                            | encrypted read-only
              v                                       | context cache
        FastAPI Hub <-------- CLI                     +--> ~/.echome/cache/context
          ^      ^
          |      |
          |      +---------- Vue Web Console / Nginx
          |
          +---------- PostgreSQL 16 + pgvector
          |
          +---------- bge-m3 Embedding Service
```

部署边界：

- MCP Server 和 CLI 运行在用户或 Agent 所在环境。
- Hub、Web、PostgreSQL 和 embedding service 由 Docker Compose 部署。
- Hub 只暴露 REST API；MCP 协议由独立 `echome_mcp` 适配层承载。
- PostgreSQL + pgvector 是唯一权威服务端数据层。
- Redis 当前没有代码路径依赖，已从运行拓扑移除。

## 3. 核心组件

### 3.1 Hub

`hub/app` 是 FastAPI 应用，主要边界如下：

| 模块 | 职责 |
|---|---|
| `api/memories.py` | 记忆 CRUD、过滤和共享混合检索入口 |
| `services/memory_retrieval.py` | personal memory 的 vector + lexical 排序与状态过滤 |
| `api/memory_sleep.py` | Sleep candidates、proposal 校验和 apply |
| `api/project_knowledge.py` | 项目制品、约束、关系、事件、Context Runs 和质量评估 |
| `services/context_compiler.py` | 证据优先的项目上下文编译 |
| `api/context_runtime.py` | `personal/project/impact/temporal` 统一路由与错误契约 |
| `api/observability.py` | 记忆图、邻居和 Sleep 观测 |
| `api/retrieval_debug.py` | 检索 trace 与元数据日志，不复制记忆正文 |

Hub 使用请求内异步事务。记忆写入成功后，embedding 通过 FastAPI BackgroundTasks 计算并以定向 `UPDATE` 写回；当前没有独立 worker 或队列。

### 3.2 PostgreSQL + pgvector

权威数据包括：

- memories、projects、memory edges、Sleep sessions 和 feedback；
- project artifacts、artifact versions/chunks、constraints、constraint edges 和 events；
- context runs、context outcomes、retrieval logs 和 quality snapshots；
- 用于语义召回的 pgvector embedding。

Alembic 是唯一 schema 迁移入口。容器启动时执行 `alembic upgrade head`，因此发布前必须先在隔离数据库完成升级、降级和数据保留验证。

### 3.3 MCP Server

`echome_mcp` 是协议适配层，通过 Hub REST API 读写数据，不直接连接数据库。

- 默认 `core` profile：8 个高频工具，包括 capability discovery、统一 context、health、graph explain、remember 和 feedback。
- `ECHOME_MCP_PROFILE=full`：暴露 summary-first、Project Knowledge、Sleep 等专业工具。
- `echome_capabilities` 会根据当前 profile 只推荐实际可调用的工具。
- Hub 暂时不可达时，仅 `echome_context` 可读取本地 AES-256-GCM last-known-good 缓存；缓存不会回写 Hub。

### 3.4 CLI

CLI 负责配置、Hub 操作、规则渲染、MCP 注册、Sleep 和诊断。`echome sync` 从 Hub 获取 L0/L1 内容并只更新受 marker 管理的区域。

文件式 local-vault `push/pull` 尚未实现。这两个命令会明确返回非零退出，不会再把空操作报告为成功。

### 3.5 Web Console

Vue 3 Web Console 通过 Nginx 访问 Hub REST API，提供：

- Memory 与 Project 工作台；
- Memory Graph、Quality Eval 和 Retrieval Logs 组成的 Diagnostics 工作区；
- Sleep proposal、review、设置和管理功能。

Market 路由保留，但主导航默认隐藏；设置 `VITE_ECHOME_MARKET_ENABLED=true` 才显示入口。

## 4. 关键运行链路

### 4.1 统一上下文

```text
Agent -> echome_context -> MCP runtime -> POST /api/v1/context
      -> route personal/project/impact/temporal
      -> retrieve/compile evidence -> answerability + trace -> Agent
```

personal 路径使用与 `/memories/search`、Memory Quality Eval 和 Retrieval Debugger 相同的共享混合检索。默认只查询 `active` 与 `ai_review`；`archived`、`deprecated` 不作为当前事实返回。

### 4.2 Memory Sleep

```text
all eligible candidates -> text + memory_sleep_plan.v1 proposal
                        -> Hub validation -> explicit approval -> atomic apply
                        -> new distilled memories + archived sources + graph edges
```

候选是所有未归档、未 deprecated 且未明确整理完成的记忆，不受普通 `top_k` 限制。apply 不删除源记忆，通过 `derived_from`、`superseded_by` 等关系保留来源。

### 4.3 Project Knowledge

```text
artifact/version/chunk + constraint/version/edge + event
                         -> Context Compiler
                         -> local context / impact / temporal review / preflight
```

项目事件和 AI 推断先作为证据或 proposal 追加，不会静默升级为 active constraint，也不会直接修改 Personal Memory。

### 4.4 Composite Project Workspaces

Project identity 和 project membership 分开建模：alias 负责把 path、remote、旧名称解析到
canonical project；`project_relations` 负责表达 `workspace --contains--> repository`。

```text
repository context = global memory + parent workspace memory + exact repository memory
workspace context  = global memory + workspace memory + changed_paths 命中的 child memory
```

父 workspace 可向 repository 提供共享规范，但 repository 之间不隐式继承。Context Compiler
只扩展 Memory scope；Project Knowledge 的 constraint、artifact、chunk 和 view 继续使用当前
canonical project，避免共享记忆机制扩大权威证据边界。

## 5. 数据安全边界

- 不在普通检索、Sleep、feedback 或日志流程中硬删除权威历史。
- Sleep 和项目约束变更遵循 `proposal -> validate -> apply`。
- `ai_review` 可被普通检索和 Sleep 看到；审核状态本身不等于无效。
- `archived/deprecated` 只在显式历史或图谱查询中作为 provenance 使用。
- Retrieval Logs 只保存结果 ID、标题、分数、原因和 trace，不复制记忆正文。
- Context Outcome 与 Memory Feedback 是 append-only 信号，不能直接静默改写排序或状态。
- 生产数据库迁移、数据回填、日志清理与服务部署是独立动作，必须分别验证和授权。

## 6. 部署与端口

| 服务 | 默认地址 | 数据持久化 |
|---|---|---|
| Hub | `http://localhost:20000` | 无本地状态 |
| Web Console | `http://localhost:20001` | 无本地状态 |
| Embedding | `http://localhost:20002` | `./data/embedding-models` |
| PostgreSQL | Compose 内网 | `./data/postgres` |

```bash
docker compose config --quiet
docker compose up -d --build
```

不要删除 `./data/postgres`，也不要用 `docker compose down -v` 处理升级。

## 7. 兼容与演进原则

1. REST、MCP schema 和 Alembic migration 默认向后兼容。
2. 检索能力集中到共享 service，评估、调试和 Agent 路径不得出现不同答案。
3. 高级能力放入 `full` profile，默认核心工具面保持小而可发现。
4. 原始数据与运行遥测分层管理；未来清理只针对有保留策略的 telemetry。
5. 大模块按业务边界逐步拆分，不在数据迁移或发布窗口顺手重构。
