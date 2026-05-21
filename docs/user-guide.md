# EchoMe 用户指南

> 从安装到日常使用的完整教程，让你在 5 分钟内跑通 EchoMe。

---

## 目录

1. [安装](#1-安装)
2. [初始化](#2-初始化)
3. [添加记忆](#3-添加记忆)
4. [同步到 CLAUDE.md](#4-同步到-claudemd)
5. [配置 MCP Server](#5-配置-mcp-server)
6. [在 Claude Code 中测试 MCP](#6-在-claude-code-中测试-mcp)
7. [日常工作流](#7-日常工作流)
8. [更新 EchoMe](#8-更新-echome)
9. [常见问题](#9-常见问题)

---

## 1. 安装

### 前提条件

- Python 3.11+
- EchoMe Hub 已在服务器上运行（`docker compose up -d`）

### 安装 CLI + MCP

```bash
cd ~/path/to/EchoMe
pip install -e ".[mcp]"
```

验证安装：

```bash
echome --help
```

---

## 2. 初始化

```bash
echome init
```

交互过程：

```
━━━ EchoMe Init ━━━

1. Hub Connection
   Hub URL (http://localhost:20000): http://你的服务器IP:20000
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

也可以非交互模式：

```bash
echome init --hub-url http://你的服务器:20000 --token YOUR_TOKEN
```

---

## 3. 添加记忆

### 三种添加方式

```bash
# 方式 1：快速模式（全部用参数）
echome add "PR必须带工单号" \
  -c "所有 PR 标题必须以 [JIRA-XXX] 开头，从 branch 名提取" \
  -t workflow \
  --layer L0 \
  -p 9 \
  --tags "git,pr,ticket"

# 方式 2：半交互（给标题，其余交互提问）
echome add "开发环境用 docker-compose"

# 方式 3：全交互
echome add
```

### 记忆示例

以下是一些常见的记忆类型供参考：

#### 工作流规范（workflow）

```bash
echome add "PR必须带工单号" \
  -c "所有 PR 标题必须以 [JIRA-XXX] 工单号开头。如果 branch 名包含工单号（如 feat/JIRA-123-add-login），从 branch 提取；否则必须先问用户，不要自己编造。" \
  -t workflow --layer L0 -p 9 --tags "git,pr,ticket"

echome add "合并PR需要review" \
  -c "PR 合并前必须满足：1) 至少 1 个 reviewer approve 2) CI 全部通过 3) 无 unresolved comments" \
  -t workflow --layer L0 -p 9 --tags "git,pr,review"

echome add "Commit 使用 Conventional Commits" \
  -c "Git commit message 格式：feat/fix/docs/refactor/test: 简短描述。示例：feat: add user login API" \
  -t workflow --layer L0 -p 8 --tags "git,commit"
```

#### 技术偏好（tech）

```bash
echome add "Python 用 ruff 格式化" \
  -c "所有 Python 项目统一使用 ruff 做 lint 和格式化，不用 black/flake8/isort" \
  -t tech --layer L0 -p 7 --tags "python,lint,ruff"

echome add "开发环境用 docker-compose" \
  -c "本地开发统一使用 docker-compose 管理所有服务依赖（数据库、Redis 等），不在宿主机直接装" \
  -t tech --layer L0 -p 6 --tags "docker,dev"
```

#### 约束红线（constraint）

```bash
echome add "禁止 force push" \
  -c "任何情况下不允许 git push --force 到 main/master 分支。个人分支也尽量用 --force-with-lease" \
  -t constraint --layer L0 -p 10 --tags "git,safety"

echome add "不要直接操作生产数据库" \
  -c "禁止在没有明确确认的情况下执行 DELETE/UPDATE/DROP 等生产数据库操作" \
  -t constraint --layer L0 -p 10 --tags "database,safety"
```

#### 沟通偏好（interaction）

```bash
echome add "中文回答，先结论后分析" \
  -c "回答用中文。先给结论或方案，再展开分析。有疑问先反问确认，不要擅自假设关键信息。" \
  -t interaction --layer L0 -p 8 --tags "style,language"
```

### 查看已添加的记忆

```bash
echome list                    # 列出所有
echome list --type workflow    # 按类型过滤
echome list --layer L0         # 只看 L0 层
echome search "PR"             # 搜索
```

---

## 4. 同步到 CLAUDE.md

### 全局同步（L0 层 → ~/.claude/CLAUDE.md）

```bash
echome sync
```

执行后查看效果：

```bash
cat ~/.claude/CLAUDE.md
```

你会看到 EchoMe 在 marker 区域内注入了你的规范：

```markdown
<!-- echome:begin -->
## EchoMe Context (auto-managed, do not edit this block)

### Workflow Rules
- **PR必须带工单号**: 所有 PR 标题必须以 [JIRA-XXX] 工单号开头...
- **合并PR需要review**: PR 合并前必须满足...

### Technical Preferences
- **Python 用 ruff 格式化**: 所有 Python 项目统一使用 ruff...

### Constraints & Boundaries
- **禁止 force push**: 任何情况下不允许 git push --force...

### Communication Preferences
- **中文回答，先结论后分析**: 回答用中文...

### How to get more context
When you need my past decisions, project background, or preferences,
call the MCP tool `echome_search` to retrieve relevant memories.
<!-- echome:end -->
```

**重要**：只有 `layer = L0` 的记忆会被同步到全局文件。L1 是项目级，L2 只通过 MCP 查询。

### 项目级同步（L1 层 → 项目目录）

如果你有项目专属的规则，先添加一条 L1 记忆并指定项目：

```bash
# 在 Web 页面编辑记忆，设置：
# - layer: L1
# - scope.projects: ["qzhqzh/EchoMe"]
```

然后在项目目录中执行：

```bash
cd ~/projects/EchoMe
echome sync --project qzhqzh/EchoMe
```

这会在项目中创建 `.echome/echome-rules.md`，不会修改项目原有的 `CLAUDE.md`。

### 查看同步状态

```bash
echome status
```

输出：

```
EchoMe Status — /home/user/projects/EchoMe

  ✓ Claude Code global: ~/.claude/CLAUDE.md
  ✗ Claude Code project: not injected
  ✓ Codex CLI global: ~/.codex/AGENTS.md
  ✗ Codex CLI project: not injected
```

---

## 5. 配置 MCP Server

### 自动配置（推荐）

如果你在 `echome init` 时选择了注册 MCP，已经配置好了。手动补装：

```bash
echome mcp install
```

### 手动配置 Claude Code

编辑 `~/.claude/mcp.json`：

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

### 手动配置 Codex CLI

编辑 `~/.codex/mcp.json`：

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

### 验证 MCP Server 能启动

```bash
echome mcp serve
# 会输出 MCP 协议的 JSON 握手信息
# Ctrl+C 退出
```

如果报错 "MCP 未安装"，说明没装 `[mcp]` 依赖：

```bash
pip install -e ".[mcp]"
```

### 重启 AI CLI

配置 MCP 后**必须重启** Claude Code / Codex CLI 才能生效。

---

## 6. 在 Claude Code 中测试 MCP

重启 Claude Code 后，EchoMe MCP 会自动注册为可用的 tool。

### 测试 1：查询工作流规范

对 Claude Code 说：

```
我提 PR 有什么规范？
```

预期行为：Claude 会调用 `echome_search` 工具，搜索你的记忆库，返回结果类似：

```
我帮你查询了你的工作流规范：

1. **PR必须带工单号** — 所有 PR 标题必须以 [JIRA-XXX] 工单号开头。
   如果 branch 名包含工单号，从 branch 提取；否则需要先问你。

2. **合并PR需要review** — PR 合并前需要至少 1 个 reviewer approve + CI 通过。
```

### 测试 2：让 AI 记住新规则

对 Claude Code 说：

```
以后所有 Python 项目的测试都用 pytest，不要用 unittest，记住这个。
```

预期行为：Claude 会调用 `echome_remember` 工具，写入一条 pending 记忆。你会在终端看到：

```
已保存记忆（待确认）。你可以运行 `echome review` 来审核。
```

然后：

```bash
echome review
# 会显示 AI 建议的记忆，你选择 approve 或 reject
```

### 测试 3：查询技术偏好

```
我们项目用什么 linter？
```

Claude 应该调用 `echome_search` 并回答 "ruff"。

### 测试 4：项目上下文

```
帮我看看这个项目的背景
```

Claude 应该调用 `echome_get_project_context` 返回项目相关的所有记忆。

### 如果 MCP 没被调用？

确认以下几点：

1. `~/.claude/CLAUDE.md` 中有 EchoMe 区块（特别是最后那段 "How to get more context"）
2. `~/.claude/mcp.json` 中有 echome 配置
3. Claude Code 重启过了
4. 你的提问涉及到工作流/偏好/项目背景（纯代码问题 AI 不会调 MCP）

---

## 7. 日常工作流

### 每天正常使用

```bash
# 什么都不用做！
# L0 已经在 CLAUDE.md 里了，MCP 按需自动查询
```

### 添加新规范时

```bash
echome add "新规则标题" -c "详细描述" -t workflow --layer L0
echome sync    # 刷新 CLAUDE.md
```

### AI 建议了新记忆时

```bash
echome review              # 查看待审核列表
echome review --approve-all   # 全部通过（信任 AI）
```

### 新机器 / 新环境

```bash
pip install -e ".[mcp]"
echome init --hub-url http://你的服务器:20000 --token YOUR_TOKEN
echome sync
# 完成！所有记忆自动恢复
```

### 切换项目

```bash
cd ~/work/another-project
echome sync --project user/another-project
```

---

## 8. 更新 EchoMe

### 当前方式（从 GitHub 源码）

```bash
cd ~/path/to/EchoMe
git pull origin main
pip install -e ".[mcp]"
```

### 未来（发布到 PyPI 后）

```bash
echome update
```

### 更新 Hub 服务

```bash
cd ~/path/to/EchoMe
git pull origin main
docker compose up -d --build
```

---

## 9. 常见问题

### Q: 记忆加了但 CLAUDE.md 没变？

检查记忆的 Layer。只有 **L0** 会同步到全局文件：

```bash
echome list --layer L0    # 看哪些是 L0
```

如果记忆是 L2，在 Web 页面编辑改为 L0，然后重新 `echome sync`。

### Q: MCP 配置了但 Claude 不调用？

1. 确认 `~/.claude/mcp.json` 正确
2. **重启 Claude Code**（关掉终端重新打开）
3. 确认 `echome mcp serve` 能正常启动（手动测试）
4. 在 `~/.claude/CLAUDE.md` 里确认有"How to get more context"那段引导文字

### Q: Web 页面添加记忆报 500？

确保你的 Hub 是最新代码。拉取最新并重启：

```bash
git pull origin main
docker compose up -d --build hub
```

### Q: `echome add "xxx"` 报错 unexpected argument？

确保你装的是最新版 CLI：

```bash
git pull origin main
pip install -e ".[mcp]"
```

### Q: 如何删除一条记忆？

```bash
# 通过 Web 页面操作（推荐）
# 或通过 API
curl -X DELETE http://你的服务器:20000/api/v1/memories/UUID \
  -H "Authorization: Bearer TOKEN"
```

### Q: Layer 的选择标准？

| Layer | 适合放什么 | 示例 |
|---|---|---|
| **L0** | 每次对话都必须知道的硬规矩 | PR 规范、禁止操作、沟通风格 |
| **L1** | 特定项目才需要的规则 | 项目技术栈、目录约定 |
| **L2** | 偶尔需要查的知识 | 过往决策、业务术语、代码片段 |

经验法则：如果一条规则你**每次和 AI 对话都想让它知道**，放 L0；如果只在**某些场景**才需要，放 L2 让 MCP 按需查。

---

## 命令速查表

| 命令 | 作用 |
|---|---|
| `echome init` | 初始化 + 连接 Hub + 注册 MCP |
| `echome add` | 添加记忆（交互/快速） |
| `echome list` | 列出记忆 |
| `echome search "xxx"` | 搜索记忆 |
| `echome sync` | 同步到 AI CLI 文件 |
| `echome status` | 查看注入状态 |
| `echome review` | 审核 AI 建议的记忆 |
| `echome mcp install` | 注册 MCP 到 Claude/Codex |
| `echome mcp serve` | 手动启动 MCP server |
| `echome detect` | 检测当前目录的 AI CLI |
| `echome eject` | 移除所有注入内容 |
| `echome update` | 更新到最新版 |
