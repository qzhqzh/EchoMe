# EchoMe 开发路线图

## 总体目标

用最短路径实现：**一台新机器上，一条命令恢复"我的 AI 协作现场"**。

---

## Phase 0 — 技术选型 & 项目骨架（0.5 天）

### 目标
搭建可运行的空项目结构，CI 跑通。

### 产出
- [x] 仓库结构确定
- [ ] Hub: FastAPI + SQLAlchemy + Alembic + Docker Compose
- [ ] CLI: Typer + httpx + Rich
- [ ] MCP Server: mcp-python SDK 集成
- [ ] pyproject.toml / uv 工作流
- [ ] GitHub Actions: lint + type check

### 技术决策
| 决策 | 选型 | 备选 |
|---|---|---|
| Hub 框架 | FastAPI | Django (太重) |
| ORM | SQLAlchemy 2.0 async | Tortoise ORM |
| 数据库 | PostgreSQL 16 + pgvector | - |
| CLI 框架 | Typer | Click (Typer 基于它) |
| MCP SDK | mcp (官方 Python) | 自己实现协议 |
| 包管理 | uv | poetry |
| 部署 | Docker Compose | K8s (过重) |

---

## Phase 1 — Hub 核心（3 天）

### 目标
Hub 能跑，记忆能 CRUD，搜索能用。

### 任务
- [ ] 数据库 schema + Alembic 迁移
- [ ] memories CRUD API (POST/GET/PUT/PATCH/DELETE)
- [ ] projects CRUD API
- [ ] POST /memories/search (关键词搜索，先不做向量)
- [ ] Bearer Token 认证中间件
- [ ] POST /sync/push + /sync/pull
- [ ] POST /render (按 target + layer 渲染)
- [ ] Docker Compose (app + postgres + redis)
- [ ] 基础测试 (pytest + httpx async client)

### 验收标准
- `curl` 能完成记忆的创建、查询、搜索
- Docker Compose 一键启动

---

## Phase 2 — CLI 核心（2 天）

### 目标
本地可用，能同步到 Hub，能渲染到 Claude Code / Codex。

### 任务
- [ ] `echome init` — 创建 ~/.echome/ + 配置 Hub URL + Token
- [ ] `echome login` — 验证连接
- [ ] `echome add` — 交互式创建记忆
- [ ] `echome list` — 列出记忆 (--type --layer --tag)
- [ ] `echome edit <id>` — 调起 $EDITOR 修改
- [ ] `echome search <query>` — 调 Hub 搜索
- [ ] `echome push` / `echome pull` — 同步
- [ ] `echome detect` — 检测当前目录的 AI CLI 类型
- [ ] `echome sync` — 渲染 L0/L1 到目标文件
- [ ] `echome status` — 显示注入状态
- [ ] `echome eject` — 移除注入
- [ ] Target adapter: ClaudeCodeTarget (CLAUDE.md marker 注入)
- [ ] Target adapter: CodexTarget (AGENTS.md marker 注入)

### 验收标准
- 在一个新目录下 `echome sync`，能看到 CLAUDE.md 被正确渲染
- `echome push` + 另一台机器 `echome pull` + `echome sync` = 完整恢复

---

## Phase 3 — MCP Server（2 天）

### 目标
AI CLI 能通过 MCP 协议查询和写入记忆。

### 任务
- [ ] `echome mcp serve` — stdio 模式 MCP server
- [ ] Tool: echome_search
- [ ] Tool: echome_get
- [ ] Tool: echome_list_by_type
- [ ] Tool: echome_remember (写入 pending)
- [ ] Tool: echome_get_project_context
- [ ] Hub 不可达时降级到本地 vault
- [ ] Claude Code mcp.json 自动配置命令
- [ ] 端到端测试：Claude Code 中实际调用

### 验收标准
- 在 Claude Code 中输入"我提 PR 有什么规范"，AI 自动调 echome_search 并给出答案
- 说"以后 commit 都用 conventional commits"，AI 调 echome_remember，`echome review` 能看到

---

## Phase 4 — 向量搜索 + 审核流程（2 天）

### 目标
搜索质量提升，AI 写入有完整审核链。

### 任务
- [ ] Hub: embedding 计算（创建/更新记忆时异步算）
- [ ] Hub: 混合搜索（向量 + 关键词 + tag）
- [ ] Hub: 审核 API (GET /review/pending, POST /review/{id}/approve|reject)
- [ ] CLI: `echome review` — 交互式审核待确认记忆
- [ ] CLI: `echome review --approve-all` / `--reject-all`
- [ ] Token 计算 + L0/L1 自动降级

### 验收标准
- 语义搜索"代码格式化用什么工具"能匹配到"Python 用 ruff"
- AI 写入 → pending → 用户 approve → 下次 sync 生效

---

## Phase 5 — 体验打磨（2 天）

### 目标
日常使用无摩擦。

### 任务
- [ ] `echome install --from <hub-url>` — 新机器一键恢复
- [ ] `echome doctor` — 环境自检
- [ ] `echome import --from claude.md` — 从已有文件导入
- [ ] `echome export --format markdown` — 导出全部记忆
- [ ] 旁路文件模式：`.echome/project-rules.md`
- [ ] `echome project link <id>` — 绑定当前目录到项目
- [ ] 配置文件支持 token 限制自定义
- [ ] CLI 补全 (bash/zsh/fish)
- [ ] PyPI 发布 `echome-cli`

### 验收标准
- 新机器：`pip install echome-cli && echome install --from https://hub.example.com` → 3 分钟内完全恢复
- 每天正常使用无 bug

---

## Phase 6+ — 远期方向（按需）

| 方向 | 说明 | 优先级 |
|---|---|---|
| SSE MCP 模式 | 远程 MCP，不需要本地进程 | P1 |
| 更多 Target | Cursor (.cursor/rules/)、Kiro (.kiro/steering/)、Aider | P1 |
| Web Console | 浏览器查看/编辑记忆 | P2 |
| 自动学习 | 从对话分析中提取偏好 | P2 |
| 多租户 | 用户注册、JWT、数据隔离 | P2 |
| 团队空间 | 共享 workflow 记忆 | P3 |
| 浏览器插件 | 回到 discuss.md 的原路线 | P3 |
| 知识图谱 | 记忆之间关联 | P3 |
| Mobile App | 随时查看/编辑记忆 | P4 |

---

## 时间线总览

```
Week 1:  Phase 0 + Phase 1 (骨架 + Hub 核心)
Week 2:  Phase 2 + Phase 3 (CLI + MCP Server)
Week 3:  Phase 4 + Phase 5 (向量搜索 + 打磨)
Week 4+: Phase 6 (按需迭代)
```

预计 **3 周**达到日常可用状态。

---

## 成功指标

| 指标 | 目标 |
|---|---|
| 新机器恢复时间 | < 5 分钟 |
| 每天手动干预次数 | 0（sync 后无需再贴规范） |
| MCP 搜索命中率 | > 80%（用户需要的记忆能被找到） |
| AI 误写率 | < 10%（pending 中被 reject 的比例） |
| 记忆总量增长 | 每周 +3~5 条（自然增长，不是负担） |
