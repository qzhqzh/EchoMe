# EchoMe 用户指南

> 从安装到日常使用的完整教程，让你在 5 分钟内跑通 EchoMe。

---

## 目录

1. [安装](#1-安装)
2. [初始化](#2-初始化)
3. [添加记忆](#3-添加记忆)
4. [同步记忆到 AI CLI](#4-同步记忆到-ai-cli)
5. [项目级记忆管理](#5-项目级记忆管理)
6. [配置 MCP Server](#6-配置-mcp-server)
7. [在 Claude Code 中测试 MCP](#7-在-claude-code-中测试-mcp)
8. [更新与清理](#8-更新与清理)
9. [日常工作流](#9-日常工作流)
10. [常见问题](#10-常见问题)
11. [命令速查表](#11-命令速查表)

---

## 1. 安装

### 前提条件

- Python 3.11+
- EchoMe Hub 已在服务器上运行（`docker compose up -d`）

### 安装 CLI + MCP（推荐）

```bash
cd ~/path/to/EchoMe
pip install -e ".[mcp]"
```

### 仅安装 CLI（不需要 MCP）

```bash
pip install -e .
```

### 验证安装

```bash
echome          # 显示欢迎界面 + 状态
echome --help   # 查看所有命令
```

> **注意**：`eme` 是 `echome` 的短别名，两者完全等价。

---

## 2. 初始化

```bash
echome init
```

交互过程：

```
━━━ EchoMe Init ━━━

1. Hub Connection
   Hub URL (http://localhost:20000): http://你的服务器:20000
   Auth Token: ********
   Testing connection... ✓ Connected (Hub v0.1.0)
   ✓ Vault created at ~/.echome/

2. MCP Server (让 AI 可以查询你的记忆)
   Register MCP server to Claude Code / Codex CLI? [Y/n]: y
    ✓ Claude Code (~/.claude/mcp.json)
    ✓ Codex CLI (~/.codex/mcp.json)
   ✓ MCP registered. Restart AI CLI to activate.

━━━ 初始化完成 ━━━
```

非交互模式：

```bash
echome init --hub-url http://你的服务器:20000 --token YOUR_TOKEN
```

跳过 MCP 注册：

```bash
echome init --skip-mcp
```

---

## 3. 添加记忆

### 三种方式

```bash
# 方式 1：快速模式（全部用参数）
echome add "PR必须带工单号" \
  -c "所有 PR 标题必须以 [JIRA-XXX] 开头" \
  -t workflow --layer L0 -p 9 --tags "git,pr"

# 方式 2：半交互（给标题，其余交互）
echome add "开发环境用 docker-compose"

# 方式 3：全交互
echome add
```

### 参数说明

| 参数 | 说明 | 示例 |
|---|---|---|
| 第一个参数 | 标题 | `"PR必须带工单号"` |
| `-c` / `--content` | 详细内容 | `"标题以[JIRA-XXX]开头"` |
| `-t` / `--type` | 类型 | `workflow` / `tech` / `constraint` / ... |
| `--layer` / `-l` | 层级 | `L0` / `L1` / `L2` |
| `-p` / `--priority` | 优先级(1-10) | `9` |
| `--tags` | 标签(逗号分隔) | `"git,pr,ticket"` |

### Layer 选择标准

| Layer | 写入位置 | 适合放什么 | 限制 |
|---|---|---|---|
| **L0** | 全局 `~/.claude/CLAUDE.md` | 每次对话都必须知道的硬规矩 | ≤ 20 条 / 1500 tokens |
| **L1** | 项目 `./CLAUDE.md` | 特定项目才需要的规则 | ≤ 30 条 / 2000 tokens |
| **L2** | 不写文件，MCP 按需查 | 偶尔需要查的知识 | 无限制 |

### 记忆类型

| Type | 说明 | 示例 |
|---|---|---|
| `persona` | 身份与风格 | 语言偏好、回答风格 |
| `workflow` | 工作流规范 | PR 规范、review 要求 |
| `tech` | 技术偏好 | 用什么 linter、框架选型 |
| `constraint` | 红线禁忌 | 禁止 force push |
| `snippet` | 可复用片段 | Docker 模板 |
| `decision` | 设计决策 | 为什么选 FastAPI |
| `knowledge` | 领域知识 | 业务术语 |
| `interaction` | 对话偏好 | 中文回答、先结论后分析 |
| `project` | 项目上下文 | 项目目标、技术栈 |

### 记忆示例

```bash
# 工作流
echome add "PR必须带工单号" \
  -c "所有 PR 标题必须以 [JIRA-XXX] 工单号开头。如果 branch 名包含工单号（如 feat/JIRA-123-add-login），从 branch 提取；否则必须先问用户。" \
  -t workflow --layer L0 -p 9 --tags "git,pr,ticket"

# 技术偏好
echome add "Python 用 ruff 格式化" \
  -c "所有 Python 项目统一使用 ruff 做 lint 和格式化，不用 black/flake8/isort" \
  -t tech --layer L0 -p 7 --tags "python,lint"

# 约束红线
echome add "禁止 force push" \
  -c "不允许 git push --force 到 main/master。个人分支用 --force-with-lease" \
  -t constraint --layer L0 -p 10 --tags "git,safety"

# 沟通偏好
echome add "中文回答，先结论后分析" \
  -c "回答用中文。先给结论，再展开分析。有疑问先反问确认。" \
  -t interaction --layer L0 -p 8 --tags "style"
```

### 查看记忆

```bash
echome list                    # 列出所有
echome list --type workflow    # 按类型
echome list --layer L0         # 按层级
echome list --status pending   # 按状态
echome search "PR 规范"        # 搜索
```

---

## 4. 同步记忆到 AI CLI

### 全局同步（L0 → ~/.claude/CLAUDE.md）

```bash
echome sync
```

执行后 `~/.claude/CLAUDE.md` 会被写入：

```markdown
你原有的内容（不动）

<!-- echome:begin -->
## EchoMe Context (auto-managed, do not edit this block)

### Workflow Rules
- **PR必须带工单号**: 所有 PR 标题必须以 [JIRA-XXX] 工单号开头...

### Technical Preferences
- **Python 用 ruff 格式化**: 所有 Python 项目统一使用 ruff...

### EchoMe Memory System (MANDATORY)
在每次对话开始时，你必须先调用 `echome_search` 查询与当前任务相关的记忆。
...
<!-- echome:end -->

你原有的内容（不动）
```

**关键点**：
- 只有 `layer = L0` 的记忆会写入全局文件
- 只修改 `<!-- echome:begin -->` 和 `<!-- echome:end -->` 之间的内容
- marker 之外的原有内容**绝不触碰**
- 每次 sync 是**整体替换** marker 区（增删都干净，不会有残留）

### 查看同步状态

```bash
echome status
```

输出：

```
EchoMe Status v0.1.0
Project: /home/user/projects/my-app

  Hub:       ✓ Connected (http://localhost:20000)
  Memories:  12 active (5 L0, 3 L1, 4 L2)
  MCP:       ✓ Registered (Claude Code)
  MCP Proc:  not running (starts on-demand by AI CLI)
  Last sync: 3m ago

Injection Status:
  ✓ Claude Code global: ~/.claude/CLAUDE.md
  ✗ Claude Code project: not injected
  ✓ Codex CLI global: ~/.codex/AGENTS.md
  ✗ Codex CLI project: not injected
```

---

## 5. 项目级记忆管理

### 添加项目记忆

在 Web 页面或 CLI 创建记忆时，设置：
- `layer`: **L1**
- `scope.projects`: 填写项目 ID（如 `qzhqzh/EchoMe`）

### 同步项目记忆到当前项目

```bash
cd ~/projects/EchoMe
echome sync --project qzhqzh/EchoMe
```

这会在**当前目录的 `CLAUDE.md`** 文件中写入 marker 区：

```markdown
项目原有内容（不动）

<!-- echome:begin -->
## [EchoMe] Project Context

### Project Details
- **EchoMe 技术栈**: FastAPI + SQLAlchemy + Vue 3...
<!-- echome:end -->

项目原有内容（不动）
```

### 与全局的区别

| | 全局 (L0) | 项目 (L1) |
|---|---|---|
| 文件 | `~/.claude/CLAUDE.md` | `./CLAUDE.md`（项目根目录） |
| 可见范围 | 所有对话 | 只有在该项目目录下的对话 |
| 适合放 | 硬规矩、通用偏好 | 项目专属技术栈、架构约定 |

### 更新项目记忆

在 Web 页面修改 L1 记忆后，需要重新 sync：

```bash
cd ~/projects/EchoMe
echome sync --project qzhqzh/EchoMe
```

**sync 每次都是从 Hub 拉取最新数据，全量替换 marker 区**，所以 Hub 上改了什么，sync 后就能看到。

### 移除项目记忆

```bash
echome eject --scope project    # 只清当前项目
echome eject --scope global     # 只清全局
echome eject --scope all        # 全部清除
```

---

## 6. 配置 MCP Server

### 自动配置（推荐）

`echome init` 时如果安装了 MCP 会自动注册。手动补装：

```bash
echome mcp install
```

### MCP 注册后的配置文件

`~/.claude/mcp.json`：

```json
{
  "mcpServers": {
    "echome": {
      "command": "echome",
      "args": ["mcp", "serve"]
    }
  }
}
```

### 验证 MCP 能启动

```bash
echome mcp serve
# 会输出 MCP 协议握手信息
# Ctrl+C 退出
```

### 重启 AI CLI

配置 MCP 后**必须重启** Claude Code 才能生效。

---

## 7. 在 Claude Code 中测试 MCP

重启 Claude Code 后，EchoMe MCP 自动注册为可用 tool。

### 测试场景

**场景 1：查询工作流规范**

```
你：我提 PR 有什么规范？
```

预期：Claude 会显示 `🔧 Using tool: echome_search` 然后返回你的 PR 规范。

**场景 2：AI 写入新规则或主动提出候选记忆**

```
你：以后所有 Python 项目都用 pytest，记住这个。
```

预期：Claude 调用 `🔧 Using tool: echome_remember`，保存为 ai_review 记忆。即使你没有明确说"记住"，当它观察到稳定偏好、项目决策或工作流约定时，也可以主动写入 ai_review。ai_review 会立即参与后续检索；你可以用 `echome review` 做事后清理或提升为 active。

**场景 3：强制触发**

```
你：请调用 echome_search 搜索我的记忆，关键词："git"
```

预期：Claude 直接调用 tool 并返回结果。

### 能直观看到 MCP 调用吗？

**能！** Claude Code 每次调用 MCP tool 时会显示展开块：

```
🔧 Using tool: echome_search
   Input: {"query": "PR 规范"}
   Output: 找到 2 条相关记忆...
```

### 如果 MCP 没被调用

1. 确认 `~/.claude/mcp.json` 正确
2. **重启 Claude Code**
3. 确认 `echome mcp serve` 能启动
4. 确认 `~/.claude/CLAUDE.md` 有 "EchoMe Memory System (MANDATORY)" 引导段

---

## 8. 更新与清理

### 更新 EchoMe CLI

```bash
# 自动检测安装方式并更新
echome update

# 如果是 editable 安装（开发模式），等同于：
cd ~/path/to/EchoMe && git pull && pip install -e ".[mcp]"
```

更新后记得重新 sync：

```bash
echome sync
```

### 更新 Hub 服务

```bash
cd ~/path/to/EchoMe
git pull origin main
docker compose up -d --build hub
```

### 清理/重置

```bash
# 只清除全局 CLAUDE.md 中的 EchoMe 区块
echome clean --scope global

# 只清除当前项目的注入
echome clean --scope project

# 全部清除
echome clean

# 核弹级：清除所有 + 删除 Hub 上全部记忆（会二次确认）
echome clean --delete-hub-data
```

### eject vs clean

| 命令 | 作用 |
|---|---|
| `echome eject` | 只移除文件注入（不删 Hub 数据） |
| `echome clean` | 同上 + 可选 `--delete-hub-data` |

---

## 9. 日常工作流

### 日常使用（什么都不用做）

L0 已在 CLAUDE.md 里，MCP 按需自动查询。正常和 AI 对话即可。

### 添加新规范

```bash
echome add "新规则" -c "描述" -t workflow --layer L0
echome sync    # 刷新 CLAUDE.md
```

### AI 建议了新记忆

```bash
echome review              # 逐条审核
echome review --approve-all   # 全部通过
echome review --reject-all    # 全部拒绝
```

### 切换项目

```bash
cd ~/work/another-project
echome sync --project user/another-project
```

### 新机器/新环境恢复

```bash
pip install -e ".[mcp]"
echome init --hub-url http://你的服务器:20000 --token YOUR_TOKEN
echome sync
# 完成！记忆自动从 Hub 恢复
```

### 记忆更新后的同步

| 你改了什么 | 需要做什么 |
|---|---|
| 在 Web 页面改了 L0 记忆 | 运行 `echome sync` |
| 在 Web 页面改了 L1 记忆 | 运行 `echome sync --project xxx` |
| 在 Web 页面改了 L2 记忆 | 不需要做任何事（MCP 实时从 Hub 查） |
| AI 通过 MCP 写了记忆 | 不需要做任何事（已存到 Hub） |
| 删除了某条记忆 | 运行 `echome sync`（marker 区会全量替换） |

---

## 10. 常见问题

### Q: 添加了记忆但 CLAUDE.md 没变？

只有 **L0** 层会同步到全局文件。检查：
```bash
echome list --layer L0
```
如果记忆是 L2，改为 L0 后运行 `echome sync`。

### Q: MCP 配了但 Claude 不调用？

1. 确认 `~/.claude/mcp.json` 有 echome 配置
2. **重启 Claude Code**
3. 确认 `~/.claude/CLAUDE.md` 有 MANDATORY 引导段
4. 用明确指令测试：`"请调用 echome_search 搜索 git"`

### Q: `echome add "xxx"` 报错？

确保用最新代码：
```bash
git pull origin main && pip install -e ".[mcp]"
```

### Q: 怎么删除一条记忆？

- Web 页面操作（推荐）
- 或 API：`curl -X DELETE http://hub:20000/api/v1/memories/UUID -H "Authorization: Bearer TOKEN"`

### Q: 项目记忆怎么更新到本地？

在 Hub/Web 改了项目记忆后：
```bash
cd ~/your-project
echome sync --project your/project-id
```

### Q: sync 会覆盖 CLAUDE.md 的其他内容吗？

**不会。** 只修改 `<!-- echome:begin -->` 到 `<!-- echome:end -->` 之间的部分。marker 之外的内容原封不动。

### Q: L0 记忆超过 20 条会怎样？

超出的记忆不会写入 CLAUDE.md，`echome sync` 时会显示 warning。建议把不常用的降级为 L2。

### Q: `echome` 命令被其他程序占了？

用别名 `eme`（完全相同的功能）：
```bash
eme sync
eme status
eme add "xxx"
```

---

## 11. 命令速查表

| 命令 | 作用 |
|---|---|
| `echome` | 显示欢迎界面 + 状态 |
| `echome init` | 初始化 + 连接 Hub + 注册 MCP |
| `echome add` | 添加记忆（交互/快速） |
| `echome list` | 列出记忆 |
| `echome search "xxx"` | 搜索记忆 |
| `echome sync` | 同步 L0 到全局 CLAUDE.md |
| `echome sync --project ID` | 同步 L1 到项目 CLAUDE.md |
| `echome status` | 详细状态（Hub/MCP/同步/注入） |
| `echome review` | 审核 AI 建议的记忆 |
| `echome update` | 更新到最新版 |
| `echome clean` | 清除注入（可选删 Hub 数据） |
| `echome eject` | 同 clean 但不删 Hub 数据 |
| `echome mcp install` | 注册 MCP 到 Claude/Codex |
| `echome mcp serve` | 手动启动 MCP server |
| `echome detect` | 检测当前目录的 AI CLI |
| `echome --help` | 所有命令帮助 |
